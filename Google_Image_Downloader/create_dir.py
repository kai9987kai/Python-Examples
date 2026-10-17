"""Safe, cross-platform folder management and verified ZIP backups.

Python >= 3.10; standard library only.

All *managed* relative paths are resolved inside ``root`` (default: user's
home directory). Archives and copy/move destinations may be elsewhere when
explicitly supplied. No operation silently overwrites an existing target.

Examples:
    from advanced_directory_manager import DirectoryManager
    fm = DirectoryManager()                         # Path.home()
    fm.create_directory('demo/subfolder')
    fm.backup_zip('demo', '~/demo-backup.zip')
    fm.verify_archive('~/demo-backup.zip')
    fm.restore_zip('~/demo-backup.zip', 'recovered-demo')

    python advanced_directory_manager.py --root . create demo/subfolder
    python advanced_directory_manager.py --root . backup demo ~/demo.zip
    python advanced_directory_manager.py --root . restore ~/demo.zip restored
    python advanced_directory_manager.py --root . delete demo --recursive --dry-run
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath
from typing import Any

_CHUNK = 1024 * 1024
_MANIFEST = 'directory_manager_manifest.json'
_BACKUP_VERSION = 1


class DirectoryManagerError(ValueError):
    """Invalid or unsafe path or operation."""


def _present(path: Path) -> bool:
    """True for actual paths, including dangling symbolic links."""
    return path.exists() or path.is_symlink()


def _external_path(path: str | os.PathLike[str]) -> Path:
    """Resolve explicitly supplied backup/restore destinations."""
    return Path(path).expanduser().resolve()


def _drive_or_path(destination: str | os.PathLike[str]) -> Path:
    """Accept legacy 'D' drive notation on Windows, or normal paths."""
    value = os.fspath(destination)
    if os.name == 'nt' and len(value) == 1 and value.isalpha():
        return Path(value.upper() + ':\\')
    return Path(value).expanduser()


def _hash_stream(source: Any, sink: Any = None) -> tuple[int, str]:
    hasher = hashlib.sha256()
    size = 0
    while chunk := source.read(_CHUNK):
        size += len(chunk)
        hasher.update(chunk)
        if sink is not None:
            sink.write(chunk)
    return size, hasher.hexdigest()


def _valid_zip_relative(name: str) -> bool:
    """Disallow traversal, Windows special names, and ambiguous archive paths."""
    parts = name.split('/')
    return bool(name) and all(
        part not in {'', '.', '..'}
        and '\\' not in part
        and ':' not in part
        and not part.endswith((' ', '.'))
        and part.upper().split('.')[0] not in
            {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)),
             *(f'LPT{i}' for i in range(1, 10))}
        for part in parts
    )


class DirectoryManager:
    """Operate inside an explicit safe root; only destinations may be external.

    For destructive actions against hostile concurrently-mutating directory
    trees, rely on operating-system permissions/sandboxing, not path checks.
    """
