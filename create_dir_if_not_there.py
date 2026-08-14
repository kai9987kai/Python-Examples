from pathlib import Path
import py_compile

code = r'''#!/usr/bin/env python3
"""
Script Name : create_dir_if_not_there.py
Purpose     : Safely ensure that a directory exists.
Version     : 3.0.0

Modern improvements:
- pathlib instead of os.path
- Reusable functions
- Explicit exception handling
- Optional CLI path
- Defaults to ~/testdir
- Optional recursive parent creation
- Optional POSIX permission mode
- Optional JSON output
- Dry-run mode
- Clear exit codes
- Idempotent operation
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence


APP_VERSION = "3.0.0"
DEFAULT_DIRECTORY_NAME = "testdir"


@dataclass(slots=True)
class DirectoryResult:
    path: str
    existed_before: bool
    exists_after: bool
    created: bool
    is_directory: bool
    dry_run: bool
    mode_applied: str | None
    message: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class DirectoryCreationError(RuntimeError):
    """Raised when the requested directory cannot be safely created."""


def parse_mode(value: str) -> int:
    """
    Parse a POSIX permission mode such as 755, 0755, or 0o755.
    """
    cleaned = value.strip().lower()

    if cleaned.startswith("0o"):
        cleaned = cleaned[2:]

    if cleaned.startswith("0") and len(cleaned) > 1:
        cleaned = cleaned[1:]

    if not cleaned or any(character not in "01234567" for character in cleaned):
        raise argparse.ArgumentTypeError(
            "mode must be an octal permission value such as 755 or 0o755"
        )

    mode = int(cleaned, 8)

    if mode < 0 or mode > 0o7777:
        raise argparse.ArgumentTypeError(
            "mode must be between 0000 and 7777"
        )

    return mode


def resolve_target_path(raw_path: str | None) -> Path:
    """
    Resolve the target directory.

    If no path is supplied, use ~/testdir.
    """
    if raw_path is None:
        target = Path.home() / DEFAULT_DIRECTORY_NAME
    else:
        target = Path(raw_path).expanduser()

    try:
        return target.resolve(strict=False)
    except OSError:
        # resolve() can fail on unusual filesystems or inaccessible parents.
        return target.absolute()


def ensure_directory(
    path: Path,
    *,
    parents: bool = True,
    mode: int | None = None,
    dry_run: bool = False,
) -> DirectoryResult:
    """
    Ensure that `path` exists and is a directory.

    Returns a structured DirectoryResult describing the operation.

    Raises:
        DirectoryCreationError:
            If the path exists but is not a directory, or creation fails.
    """
    existed_before = path.exists()

    if existed_before:
        if not path.is_dir():
            raise DirectoryCreationError(
                f"Path already exists but is not a directory: {path}"
            )

        return DirectoryResult(
            path=str(path),
            existed_before=True,
            exists_after=True,
            created=False,
            is_directory=True,
            dry_run=dry_run,
            mode_applied=None,
            message="Directory already exists.",
        )

    if dry_run:
        return DirectoryResult(
            path=str(path),
            existed_before=False,
            exists_after=False,
            created=False,
            is_directory=False,
            dry_run=True,
            mode_applied=oct(mode) if mode is not None else None,
            message="Dry run: directory would be created.",
        )

    try:
        path.mkdir(
            mode=mode if mode is not None else 0o777,
            parents=parents,
            exist_ok=True,
        )
    except PermissionError as exc:
        raise DirectoryCreationError(
            f"Permission denied while creating directory: {path}"
        ) from exc
    except FileExistsError as exc:
        raise DirectoryCreationError(
            f"A non-directory filesystem object already exists at: {path}"
        ) from exc
    except OSError as exc:
        raise DirectoryCreationError(
            f"Operating system error while creating {path}: {exc}"
        ) from exc

    # mkdir(mode=...) is filtered through the process umask.
    # chmod is optional and only used when the caller explicitly requested a mode.
    if mode is not None:
        try:
            os.chmod(path, mode)
        except PermissionError as exc:
            raise DirectoryCreationError(
                f"Directory was created, but permissions could not be applied: {path}"
            ) from exc
        except OSError as exc:
            raise DirectoryCreationError(
                f"Directory was created, but chmod failed for {path}: {exc}"
            ) from exc

    exists_after = path.exists()
    is_directory = path.is_dir()

    if not exists_after or not is_directory:
        raise DirectoryCreationError(
            f"Directory creation did not produce a usable directory: {path}"
        )

    return DirectoryResult(
        path=str(path),
        existed_before=False,
        exists_after=True,
        created=True,
        is_directory=True,
        dry_run=False,
        mode_applied=oct(mode) if mode is not None else None,
        message="Directory created successfully.",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Ensure that a directory exists. "
            f"If no path is given, defaults to ~/{DEFAULT_DIRECTORY_NAME}."
        )
    )

    parser.add_argument(
        "path",
        nargs="?",
        help=(
            "Directory to create or verify. "
            f"Default: ~/{DEFAULT_DIRECTORY_NAME}"
        ),
    )

    parser.add_argument(
        "--mode",
        type=parse_mode,
        help=(
            "POSIX permissions to apply after creation, "
            "for example 755 or 0o700."
        ),
    )

    parser.add_argument(
        "--no-parents",
        action="store_true",
        help="Do not automatically create missing parent directories.",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would happen without changing the filesystem.",
    )

    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Print the result as JSON.",
    )

    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress normal human-readable output.",
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {APP_VERSION}",
    )

    return parser


def print_result(
    result: DirectoryResult,
    *,
    json_output: bool,
    quiet: bool,
) -> None:
    if json_output:
        print(
            json.dumps(
                result.to_dict(),
                indent=2,
                ensure_ascii=False,
            )
        )
        return

    if quiet:
        return

    print(f"Path: {result.path}")
    print(f"Status: {result.message}")

    if result.mode_applied is not None:
        print(f"Mode: {result.mode_applied}")

    if result.dry_run:
        print("Filesystem changed: no")
    else:
        print(f"Filesystem changed: {'yes' if result.created else 'no'}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    target = resolve_target_path(args.path)

    try:
        result = ensure_directory(
            target,
            parents=not args.no_parents,
            mode=args.mode,
            dry_run=args.dry_run,
        )
    except DirectoryCreationError as exc:
        if args.json_output:
            print(
                json.dumps(
                    {
                        "success": False,
                        "path": str(target),
                        "error": str(exc),
                    },
                    indent=2,
                    ensure_ascii=False,
                )
            )
        else:
            print(f"Error: {exc}", file=sys.stderr)

        return 1

    print_result(
        result,
        json_output=args.json_output,
        quiet=args.quiet,
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''

path = Path("/mnt/data/create_dir_if_not_there.py")
path.write_text(code, encoding="utf-8")
py_compile.compile(str(path), doraise=True)

print(f"Syntax check passed: {path}")
