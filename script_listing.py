#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
script_listing.py
=================
Modern recursive file inventory / script catalogue utility.

Original concept:
    Craig Richards, 15 February 2012

Modernized edition:
    - Python 3.10+
    - pathlib + os.walk traversal
    - TXT / CSV / JSON / JSONL / HTML reports
    - extension, glob, hidden-file and size filtering
    - SHA hashing and duplicate detection
    - line counting
    - robust error collection
    - deterministic sorting
    - atomic report writes
    - legacy ``scripts`` and ``logs`` environment variable support
    - useful process exit codes for automation

The program intentionally uses only the Python standard library.
"""

from __future__ import annotations

import argparse
import csv
import fnmatch
import hashlib
import html
import io
import json
import logging
import os
import re
import stat
import tempfile
import time
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator, Sequence


PROGRAM_NAME = "script_listing"
VERSION = "3.0.0"
DEFAULT_LOGFILE_STEM = "script_list"

DEFAULT_EXCLUDED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
}

CHUNK_SIZE = 1024 * 1024

LOGGER = logging.getLogger(PROGRAM_NAME)


# ===========================================================================
# DATA MODELS
# ===========================================================================


@dataclass(slots=True)
class ScanConfig:
    """
    Configuration for one directory scan.
    """

    root: Path
    output: Path

    include_extensions: set[str] = field(default_factory=set)
    exclude_extensions: set[str] = field(default_factory=set)

    exclude_dirs: set[str] = field(
        default_factory=lambda: set(DEFAULT_EXCLUDED_DIRS)
    )

    include_globs: list[str] = field(default_factory=list)
    exclude_globs: list[str] = field(default_factory=list)

    include_hidden: bool = False
    follow_symlinks: bool = False

    min_size: int | None = None
    max_size: int | None = None

    hash_algorithm: str | None = None
    count_lines: bool = False
    detect_duplicates: bool = False

    sort_by: str = "path"
    reverse: bool = False
    relative_paths: bool = False

    def __post_init__(self) -> None:
        self.root = Path(self.root).expanduser()
        self.output = Path(self.output).expanduser()

        self.include_extensions = normalize_extensions(
            self.include_extensions
        )

        self.exclude_extensions = normalize_extensions(
            self.exclude_extensions
        )

        self.exclude_dirs = {
            str(name).strip()
            for name in self.exclude_dirs
            if str(name).strip()
        }

        if self.min_size is not None and self.min_size < 0:
            raise ValueError("min_size cannot be negative")

        if self.max_size is not None and self.max_size < 0:
            raise ValueError("max_size cannot be negative")

        if (
            self.min_size is not None
            and self.max_size is not None
            and self.min_size > self.max_size
        ):
            raise ValueError(
                "min_size cannot be greater than max_size"
            )

        if self.hash_algorithm:
            validate_hash_algorithm(self.hash_algorithm)


@dataclass(slots=True)
class FileRecord:
    """
    Metadata for one discovered file.
    """

    full_path: str
    relative_path: str
    name: str
    extension: str

    size_bytes: int
    size_human: str

    modified_utc: str

    is_symlink: bool

    digest: str | None = None
    line_count: int | None = None


@dataclass(slots=True)
class ScanError:
    """
    Non-fatal error encountered during scanning.
    """

    path: str
    operation: str
    message: str


@dataclass(slots=True)
class DuplicateGroup:
    """
    Group of files containing identical data.
    """

    digest: str

    size_bytes: int
    size_human: str

    paths: list[str]

    duplicate_bytes: int


@dataclass(slots=True)
class ScanSummary:
    """
    Aggregate statistics about a completed scan.
    """

    root: str

    total_files: int

    total_bytes: int
    total_human: str

    directories_visited: int
    errors: int

    elapsed_seconds: float

    extension_counts: dict[str, int]

    largest_files: list[dict[str, object]]

    duplicate_groups: int = 0

    reclaimable_duplicate_bytes: int = 0
    reclaimable_duplicate_human: str = "0 B"


@dataclass(slots=True)
class ScanResult:
    """
    Complete result from scan_files().
    """

    records: list[FileRecord]
    errors: list[ScanError]
    summary: ScanSummary

    duplicates: list[DuplicateGroup] = field(
        default_factory=list
    )


@dataclass(slots=True)
class TraversalMetrics:
    """
    Internal traversal statistics.
    """

    directories_visited: int = 0


# ===========================================================================
# SIZE PARSING
# ===========================================================================


_SIZE_RE = re.compile(
    r"^\s*"
    r"(?P<number>\d+(?:\.\d+)?)"
    r"\s*"
    r"(?P<unit>B|KB|MB|GB|TB|KIB|MIB|GIB|TIB)?"
    r"\s*$",
    re.IGNORECASE,
)


_SIZE_MULTIPLIERS = {
    "": 1,
    "B": 1,

    "KB": 1000,
    "MB": 1000**2,
    "GB": 1000**3,
    "TB": 1000**4,

    "KIB": 1024,
    "MIB": 1024**2,
    "GIB": 1024**3,
    "TIB": 1024**4,
}


def parse_size(value: str) -> int:
    """
    Parse a human readable file size.

    Examples:
        500
        10KB
        5MB
        1.5GB
        256KiB
        2GiB
    """

    match = _SIZE_RE.match(value)

    if not match:
        raise argparse.ArgumentTypeError(
            f"Invalid size {value!r}. "
            "Examples: 500, 10KB, 1.5MB, 2GiB"
        )

    number = float(match.group("number"))

    unit = (
        match.group("unit")
        or ""
    ).upper()

    return int(
        number * _SIZE_MULTIPLIERS[unit]
    )


def human_size(size: int) -> str:
    """
    Convert bytes into IEC units.
    """

    if size < 0:
        raise ValueError(
            "size cannot be negative"
        )

    value = float(size)

    units = (
        "B",
        "KiB",
        "MiB",
        "GiB",
        "TiB",
        "PiB",
    )

    for unit in units:

        if (
            value < 1024.0
            or unit == units[-1]
        ):

            if unit == "B":
                return f"{int(value)} B"

            return f"{value:.2f} {unit}"

        value /= 1024.0

    return f"{size} B"


# ===========================================================================
# EXTENSION / HASH / PATH UTILITIES
# ===========================================================================


def normalize_extensions(
    values: Iterable[str],
) -> set[str]:
    """
    Normalize extensions.

    py   -> .py
    PY   -> .py
    .JS  -> .js
    """

    normalized: set[str] = set()

    for raw in values:

        value = str(raw).strip().lower()

        if not value:
            continue

        if value == "*":
            normalized.add("*")

        else:
            normalized.add(
                value
                if value.startswith(".")
                else f".{value}"
            )

    return normalized


def validate_hash_algorithm(
    name: str,
) -> None:
    """
    Validate a hashlib algorithm.
    """

    try:
        hashlib.new(name)

    except (ValueError, TypeError) as exc:

        available = ", ".join(
            sorted(
                hashlib.algorithms_guaranteed
            )
        )

        raise ValueError(
            f"Unsupported hash algorithm "
            f"{name!r}. "
            f"Guaranteed algorithms: "
            f"{available}"
        ) from exc


def iso_utc(
    timestamp: float,
) -> str:
    """
    Convert a UNIX timestamp to ISO-8601 UTC.
    """

    return datetime.fromtimestamp(
        timestamp,
        tz=timezone.utc,
    ).isoformat(
        timespec="seconds"
    )


def is_hidden(
    path: Path,
) -> bool:
    """
    Detect hidden files.

    Supports:
    - Unix dot-files
    - Windows FILE_ATTRIBUTE_HIDDEN
    """

    if path.name.startswith("."):
        return True

    try:
        st = path.stat(
            follow_symlinks=False
        )

    except OSError:
        return False

    attrs = getattr(
        st,
        "st_file_attributes",
        0,
    )

    hidden_flag = getattr(
        stat,
        "FILE_ATTRIBUTE_HIDDEN",
        0,
    )

    return bool(
        hidden_flag
        and attrs & hidden_flag
    )


def hash_file(
    path: Path,
    algorithm: str = "sha256",
) -> str:
    """
    Hash a file using streaming reads.
    """

    validate_hash_algorithm(
        algorithm
    )

    digest = hashlib.new(
        algorithm
    )

    with path.open("rb") as handle:

        for chunk in iter(
            lambda: handle.read(
                CHUNK_SIZE
            ),
            b"",
        ):
            digest.update(chunk)

    return digest.hexdigest()


def analyse_content(
    path: Path,
    algorithm: str | None,
    count_lines: bool,
) -> tuple[str | None, int | None]:
    """
    Hash and/or count lines using one sequential pass.

    This avoids reading a file twice when both operations
    are requested.
    """

    if (
        algorithm is None
        and not count_lines
    ):
        return None, None

    digest = (
        hashlib.new(algorithm)
        if algorithm
        else None
    )

    newline_count = 0

    saw_data = False

    last_byte: int | None = None

    with path.open("rb") as handle:

        for chunk in iter(
            lambda: handle.read(
                CHUNK_SIZE
            ),
            b"",
        ):

            saw_data = True

            if digest is not None:
                digest.update(chunk)

            if count_lines:

                newline_count += (
                    chunk.count(b"\n")
                )

                last_byte = chunk[-1]

    line_count: int | None = None

    if count_lines:

        if not saw_data:
            line_count = 0

        else:

            line_count = (
                newline_count
                + (
                    0
                    if last_byte == 0x0A
                    else 1
                )
            )

    return (
        (
            digest.hexdigest()
            if digest is not None
            else None
        ),
        line_count,
    )


def _path_matches_extension(
    path: Path,
    extensions: set[str],
) -> bool:
    """
    Test extension filters.

    Uses endswith() so compound suffixes such as
    .tar.gz are supported.
    """

    if (
        not extensions
        or "*" in extensions
    ):
        return True

    lower_name = (
        path.name.lower()
    )

    return any(
        lower_name.endswith(ext)
        for ext in extensions
    )


def _matches_any_glob(
    relative_path: str,
    patterns: Sequence[str],
) -> bool:
    """
    Match a path or basename against glob patterns.
    """

    normalized = (
        relative_path.replace(
            os.sep,
            "/",
        )
    )

    basename = Path(
        relative_path
    ).name

    return any(
        fnmatch.fnmatch(
            normalized,
            pattern,
        )
        or fnmatch.fnmatch(
            basename,
            pattern,
        )
        for pattern in patterns
    )


def _same_path(
    a: Path,
    b: Path,
) -> bool:
    """
    Compare two filesystem paths robustly.

    Used to prevent the output report from listing itself.
    """

    try:

        return (
            os.path.normcase(
                str(
                    a.resolve(
                        strict=False
                    )
                )
            )
            ==
            os.path.normcase(
                str(
                    b.resolve(
                        strict=False
                    )
                )
            )
        )

    except OSError:

        return (
            os.path.normcase(
                str(
                    a.absolute()
                )
            )
            ==
            os.path.normcase(
                str(
                    b.absolute()
                )
            )
        )


# ===========================================================================
# FILE DISCOVERY
# ===========================================================================


def _iter_candidate_files(
    config: ScanConfig,
    errors: list[ScanError],
    metrics: TraversalMetrics,
) -> Iterator[
    tuple[Path, str]
]:
    """
    Traverse the directory tree and yield candidate files.
    """

    root = config.root
    output = config.output

    exclude_dir_keys = {
        os.path.normcase(name)
        for name
        in config.exclude_dirs
    }

    # Used when following symlinks to avoid directory loops.
    seen_dirs: set[
        tuple[int, int]
    ] = set()

    if config.follow_symlinks:

        try:

            st = root.stat()

            seen_dirs.add(
                (
                    st.st_dev,
                    st.st_ino,
                )
            )

        except OSError:
            pass

    def on_walk_error(
        exc: OSError,
    ) -> None:

        errors.append(
            ScanError(
                path=str(
                    getattr(
                        exc,
                        "filename",
                        root,
                    )
                ),
                operation="walk",
                message=str(exc),
            )
        )

    for (
        dirpath_text,
        dirnames,
        filenames,
    ) in os.walk(
        root,
        topdown=True,
        onerror=on_walk_error,
        followlinks=config.follow_symlinks,
    ):

        metrics.directories_visited += 1

        dirpath = Path(
            dirpath_text
        )

        # ---------------------------------------------------------------
        # Filter directories before os.walk enters them.
        # ---------------------------------------------------------------

        kept_dirs: list[str] = []

        for dirname in sorted(
            dirnames,
            key=str.casefold,
        ):

            candidate = (
                dirpath / dirname
            )

            if (
                os.path.normcase(
                    dirname
                )
                in exclude_dir_keys
            ):
                continue

            if (
                not config.include_hidden
                and is_hidden(candidate)
            ):
                continue

            try:

                rel_dir = (
                    candidate
                    .relative_to(root)
                    .as_posix()
                )

            except ValueError:

                rel_dir = (
                    candidate.as_posix()
                )

            if (
                config.exclude_globs
                and _matches_any_glob(
                    rel_dir,
                    config.exclude_globs,
                )
            ):
                continue

            # Protect against:
            #
            # A -> B
            # B -> A
            #
            # or similar directory cycles.

            if config.follow_symlinks:

                try:

                    st = candidate.stat()

                    key = (
                        st.st_dev,
                        st.st_ino,
                    )

                    if key in seen_dirs:
                        continue

                    seen_dirs.add(key)

                except OSError as exc:

                    errors.append(
                        ScanError(
                            str(candidate),
                            "stat-directory",
                            str(exc),
                        )
                    )

                    continue

            kept_dirs.append(
                dirname
            )

        dirnames[:] = (
            kept_dirs
        )

        # ---------------------------------------------------------------
        # Process files
        # ---------------------------------------------------------------

        for filename in sorted(
            filenames,
            key=str.casefold,
        ):

            path = (
                dirpath / filename
            )

            # Never inventory our own output report.

            if _same_path(
                path,
                output,
            ):
                continue

            if (
                not config.include_hidden
                and is_hidden(path)
            ):
                continue

            try:

                relative = (
                    path
                    .relative_to(root)
                    .as_posix()
                )

            except ValueError:

                relative = (
                    path.as_posix()
                )

            # Include glob filtering.

            if (
                config.include_globs
                and not _matches_any_glob(
                    relative,
                    config.include_globs,
                )
            ):
                continue

            # Exclude glob filtering.

            if (
                config.exclude_globs
                and _matches_any_glob(
                    relative,
                    config.exclude_globs,
                )
            ):
                continue

            # Extension whitelist.

            if (
                config.include_extensions
                and not _path_matches_extension(
                    path,
                    config.include_extensions,
                )
            ):
                continue

            # Extension blacklist.

            if (
                config.exclude_extensions
                and _path_matches_extension(
                    path,
                    config.exclude_extensions,
                )
            ):
                continue

            yield (
                path,
                relative,
            )


# ===========================================================================
# FILE INSPECTION
# ===========================================================================


def _record_for_file(
    path: Path,
    relative: str,
    config: ScanConfig,
    effective_hash_algorithm: str | None,
) -> FileRecord | None:
    """
    Inspect one file and return its FileRecord.
    """

    # os.walk's followlinks option controls directory traversal.
    #
    # For a file symlink we inspect the target because content analysis
    # opens the target as well. This keeps file size and hashed bytes
    # consistent.

    st = path.stat()

    # ---------------------------------------------------------------
    # Size filters
    # ---------------------------------------------------------------

    if (
        config.min_size is not None
        and st.st_size
        < config.min_size
    ):
        return None

    if (
        config.max_size is not None
        and st.st_size
        > config.max_size
    ):
        return None

    digest, line_count = (
        analyse_content(
            path,
            effective_hash_algorithm,
            config.count_lines,
        )
    )

    return FileRecord(
        full_path=str(
            path.resolve(
                strict=False
            )
        ),

        relative_path=relative,

        name=path.name,

        extension=(
            path.suffix.lower()
        ),

        size_bytes=(
            st.st_size
        ),

        size_human=(
            human_size(
                st.st_size
            )
        ),

        modified_utc=(
            iso_utc(
                st.st_mtime
            )
        ),

        is_symlink=(
            path.is_symlink()
        ),

        digest=digest,

        line_count=line_count,
    )


# ===========================================================================
# SORTING
# ===========================================================================


def _sort_records(
    records: list[FileRecord],
    sort_by: str,
    reverse: bool,
) -> None:
    """
    Deterministically sort inventory records.
    """

    key_map = {

        "path":
            lambda record:
                record
                .relative_path
                .casefold(),

        "name":
            lambda record:
                record
                .name
                .casefold(),

        "extension":
            lambda record:
                (
                    record
                    .extension
                    .casefold(),

                    record
                    .name
                    .casefold(),
                ),

        "size":
            lambda record:
                (
                    record.size_bytes,

                    record
                    .relative_path
                    .casefold(),
                ),

        "modified":
            lambda record:
                (
                    record.modified_utc,

                    record
                    .relative_path
                    .casefold(),
                ),
    }

    records.sort(
        key=key_map[
            sort_by
        ],
        reverse=reverse,
    )


# ===========================================================================
# DUPLICATE DETECTION
# ===========================================================================


def _build_duplicates(
    records: Sequence[FileRecord],
) -> list[DuplicateGroup]:
    """
    Group files sharing the same size and digest.
    """

    groups: dict[
        tuple[int, str],
        list[FileRecord],
    ] = defaultdict(list)

    for record in records:

        if record.digest:

            groups[
                (
                    record.size_bytes,
                    record.digest,
                )
            ].append(
                record
            )

    duplicates: list[
        DuplicateGroup
    ] = []

    for (
        size_bytes,
        digest,
    ), members in groups.items():

        if len(members) < 2:
            continue

        paths = sorted(
            (
                member.relative_path
                for member
                in members
            ),
            key=str.casefold,
        )

        duplicate_bytes = (
            size_bytes
            * (
                len(paths) - 1
            )
        )

        duplicates.append(
            DuplicateGroup(
                digest=digest,

                size_bytes=(
                    size_bytes
                ),

                size_human=(
                    human_size(
                        size_bytes
                    )
                ),

                paths=paths,

                duplicate_bytes=(
                    duplicate_bytes
                ),
            )
        )

    duplicates.sort(
        key=lambda group: (
            -group.duplicate_bytes,
            group.paths[0].casefold(),
        )
    )

    return duplicates


# ===========================================================================
# SCAN ENGINE
# ===========================================================================


def scan_files(
    config: ScanConfig,
) -> ScanResult:
    """
    Recursively scan a directory and build a deterministic inventory.
    """

    started = (
        time.perf_counter()
    )

    errors: list[
        ScanError
    ] = []

    records: list[
        FileRecord
    ] = []

    # ---------------------------------------------------------------
    # Validate root
    # ---------------------------------------------------------------

    if not config.root.exists():

        raise FileNotFoundError(
            f"Scan root does not exist: "
            f"{config.root}"
        )

    if not config.root.is_dir():

        raise NotADirectoryError(
            f"Scan root is not a directory: "
            f"{config.root}"
        )

    # ---------------------------------------------------------------
    # Hashing strategy
    # ---------------------------------------------------------------

    effective_hash_algorithm = (
        config.hash_algorithm
    )

    if effective_hash_algorithm:

        validate_hash_algorithm(
            effective_hash_algorithm
        )

    metrics = (
        TraversalMetrics()
    )

    # ---------------------------------------------------------------
    # Scan
    # ---------------------------------------------------------------

    for (
        path,
        relative,
    ) in _iter_candidate_files(
        config,
        errors,
        metrics,
    ):

        try:

            record = (
                _record_for_file(
                    path,
                    relative,
                    config,
                    effective_hash_algorithm,
                )
            )

        except OSError as exc:

            errors.append(
                ScanError(
                    str(path),
                    "inspect-file",
                    str(exc),
                )
            )

            continue

        if record is not None:

            records.append(
                record
            )

    # ---------------------------------------------------------------
    # Deterministic ordering
    # ---------------------------------------------------------------

    _sort_records(
        records,
        config.sort_by,
        config.reverse,
    )

    # ---------------------------------------------------------------
    # Efficient duplicate hashing
    #
    # If --duplicates was requested but --hash wasn't, files with a
    # unique size cannot possibly be byte-for-byte duplicates.
    #
    # Therefore SHA-256 is only calculated for files belonging to a
    # same-size candidate group.
    # ---------------------------------------------------------------

    if (
        config.detect_duplicates
        and config.hash_algorithm is None
    ):

        same_size: dict[
            int,
            list[FileRecord],
        ] = defaultdict(list)

        for record in records:

            same_size[
                record.size_bytes
            ].append(
                record
            )

        for members in (
            same_size.values()
        ):

            if len(members) < 2:
                continue

            for record in members:

                try:

                    record.digest = (
                        hash_file(
                            Path(
                                record.full_path
                            ),
                            "sha256",
                        )
                    )

                except OSError as exc:

                    errors.append(
                        ScanError(
                            record.full_path,
                            "hash-file",
                            str(exc),
                        )
                    )

    # ---------------------------------------------------------------
    # Duplicate groups
    # ---------------------------------------------------------------

    duplicates = (
        _build_duplicates(
            records
        )
        if config.detect_duplicates
        else []
    )

    # ---------------------------------------------------------------
    # Statistics
    # ---------------------------------------------------------------

    total_bytes = sum(
        record.size_bytes
        for record
        in records
    )

    extension_counts = Counter(
        (
            record.extension
            or "[no extension]"
        )
        for record
        in records
    )

    largest_records = sorted(
        records,
        key=lambda record: (
            -record.size_bytes,
            record
            .relative_path
            .casefold(),
        ),
    )[:10]

    reclaimable = sum(
        group.duplicate_bytes
        for group
        in duplicates
    )

    elapsed = (
        time.perf_counter()
        - started
    )

    summary = ScanSummary(

        root=str(
            config.root.resolve(
                strict=False
            )
        ),

        total_files=(
            len(records)
        ),

        total_bytes=(
            total_bytes
        ),

        total_human=(
            human_size(
                total_bytes
            )
        ),

        directories_visited=(
            metrics
            .directories_visited
        ),

        errors=(
            len(errors)
        ),

        elapsed_seconds=(
            round(
                elapsed,
                6,
            )
        ),

        extension_counts=dict(
            sorted(
                extension_counts.items(),
                key=lambda item:
                    item[0].casefold(),
            )
        ),

        largest_files=[
            {
                "path":
                    record.relative_path,

                "size_bytes":
                    record.size_bytes,

                "size_human":
                    record.size_human,
            }

            for record
            in largest_records
        ],

        duplicate_groups=(
            len(duplicates)
        ),

        reclaimable_duplicate_bytes=(
            reclaimable
        ),

        reclaimable_duplicate_human=(
            human_size(
                reclaimable
            )
        ),
    )

    return ScanResult(
        records=records,
        errors=errors,
        summary=summary,
        duplicates=duplicates,
    )


# ===========================================================================
# ATOMIC OUTPUT
# ===========================================================================


def _atomic_write_text(
    path: Path,
    content: str,
) -> None:
    """
    Safely write a report.

    Data is first written to a temporary file and then moved into
    place atomically with os.replace().

    This avoids leaving a partially-written report after a crash.
    """

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    fd, temp_name = (
        tempfile.mkstemp(
            prefix=(
                f".{path.name}."
            ),
            suffix=".tmp",
            dir=str(
                path.parent
            ),
            text=True,
        )
    )

    temp_path = Path(
        temp_name
    )

    try:

        with os.fdopen(
            fd,
            "w",
            encoding="utf-8",
            newline="",
        ) as handle:

            handle.write(
                content
            )

            handle.flush()

            os.fsync(
                handle.fileno()
            )

        os.replace(
            temp_path,
            path,
        )

    except Exception:

        try:
            temp_path.unlink(
                missing_ok=True
            )

        finally:
            raise


# ===========================================================================
# TEXT REPORT
# ===========================================================================


def _text_report(
    result: ScanResult,
    config: ScanConfig,
) -> str:

    out = io.StringIO()

    summary = (
        result.summary
    )

    generated = (
        datetime.now(
            timezone.utc
        ).isoformat(
            timespec="seconds"
        )
    )

    out.write(
        f"{PROGRAM_NAME} "
        f"{VERSION} - "
        "file inventory\n"
    )

    out.write(
        f"Generated (UTC): "
        f"{generated}\n"
    )

    out.write(
        f"Root: "
        f"{summary.root}\n"
    )

    out.write(
        "=" * 88
        + "\n\n"
    )

    # ---------------------------------------------------------------
    # Files
    # ---------------------------------------------------------------

    for index, record in enumerate(
        result.records,
        start=1,
    ):

        display_path = (
            record.relative_path
            if config.relative_paths
            else record.full_path
        )

        out.write(
            f"[{index:06d}] "
            f"{display_path}\n"
        )

        out.write(
            f"         Size: "
            f"{record.size_human} "
            f"({record.size_bytes} bytes)\n"
        )

        out.write(
            f"     Modified: "
            f"{record.modified_utc}\n"
        )

        if (
            record.line_count
            is not None
        ):

            out.write(
                f"        Lines: "
                f"{record.line_count}\n"
            )

        if (
            record.digest
            is not None
        ):

            algorithm = (
                config.hash_algorithm
                or "sha256"
            )

            out.write(
                f"       "
                f"{algorithm.upper()}: "
                f"{record.digest}\n"
            )

        if record.is_symlink:

            out.write(
                "      Symlink: yes\n"
            )

        out.write("\n")

    # ---------------------------------------------------------------
    # Summary
    # ---------------------------------------------------------------

    out.write(
        "=" * 88
        + "\n"
    )

    out.write(
        "SUMMARY\n"
    )

    out.write(
        f"Files: "
        f"{summary.total_files}\n"
    )

    out.write(
        f"Directories visited: "
        f"{summary.directories_visited}\n"
    )

    out.write(
        f"Total size: "
        f"{summary.total_human} "
        f"({summary.total_bytes} bytes)\n"
    )

    out.write(
        f"Errors: "
        f"{summary.errors}\n"
    )

    out.write(
        f"Elapsed: "
        f"{summary.elapsed_seconds:.3f} "
        "seconds\n"
    )

    # ---------------------------------------------------------------
    # Extension statistics
    # ---------------------------------------------------------------

    if summary.extension_counts:

        out.write(
            "\nExtensions:\n"
        )

        for (
            extension,
            count,
        ) in (
            summary
            .extension_counts
            .items()
        ):

            out.write(
                f"  {extension}: "
                f"{count}\n"
            )

    # ---------------------------------------------------------------
    # Duplicates
    # ---------------------------------------------------------------

    if result.duplicates:

        out.write(
            "\n"
            "DUPLICATE CONTENT GROUPS\n"
        )

        for index, group in enumerate(
            result.duplicates,
            start=1,
        ):

            out.write(
                f"  Group {index}: "
                f"{len(group.paths)} files, "
                f"{group.size_human} each, "
                f"reclaimable "
                f"{human_size(group.duplicate_bytes)}\n"
            )

            out.write(
                f"    Hash: "
                f"{group.digest}\n"
            )

            for path in group.paths:

                out.write(
                    f"    - {path}\n"
                )

    # ---------------------------------------------------------------
    # Errors
    # ---------------------------------------------------------------

    if result.errors:

        out.write(
            "\nERRORS\n"
        )

        for error in result.errors:

            out.write(
                f"  "
                f"[{error.operation}] "
                f"{error.path}: "
                f"{error.message}\n"
            )

    return out.getvalue()


# ===========================================================================
# CSV REPORT
# ===========================================================================


def _csv_report(
    result: ScanResult,
    config: ScanConfig,
) -> str:

    out = io.StringIO(
        newline=""
    )

    fieldnames = [
        "path",
        "relative_path",
        "name",
        "extension",
        "size_bytes",
        "size_human",
        "modified_utc",
        "is_symlink",
        "digest",
        "line_count",
    ]

    writer = csv.DictWriter(
        out,
        fieldnames=fieldnames,
        extrasaction="ignore",
    )

    writer.writeheader()

    for record in (
        result.records
    ):

        data = asdict(
            record
        )

        data["path"] = (
            record.relative_path
            if config.relative_paths
            else record.full_path
        )

        writer.writerow(
            data
        )

    return out.getvalue()


# ===========================================================================
# JSON REPORT
# ===========================================================================


def _json_report(
    result: ScanResult,
    config: ScanConfig,
) -> str:

    payload = {

        "schema_version": 1,

        "generator": {
            "name":
                PROGRAM_NAME,

            "version":
                VERSION,
        },

        "generated_utc":
            datetime.now(
                timezone.utc
            ).isoformat(
                timespec="seconds"
            ),

        "summary":
            asdict(
                result.summary
            ),

        "files": [
            asdict(record)
            for record
            in result.records
        ],

        "duplicates": [
            asdict(group)
            for group
            in result.duplicates
        ],

        "errors": [
            asdict(error)
            for error
            in result.errors
        ],
    }

    return (
        json.dumps(
            payload,
            indent=2,
            ensure_ascii=False,
        )
        + "\n"
    )


# ===========================================================================
# JSON-LINES REPORT
# ===========================================================================


def _jsonl_report(
    result: ScanResult,
) -> str:
    """
    JSONL is especially useful when inventories become extremely large
    because consumers can process one object at a time.
    """

    lines: list[str] = []

    for record in (
        result.records
    ):

        lines.append(
            json.dumps(
                {
                    "type":
                        "file",

                    **asdict(
                        record
                    ),
                },
                ensure_ascii=False,
            )
        )

    for group in (
        result.duplicates
    ):

        lines.append(
            json.dumps(
                {
                    "type":
                        "duplicate",

                    **asdict(
                        group
                    ),
                },
                ensure_ascii=False,
            )
        )

    for error in (
        result.errors
    ):

        lines.append(
            json.dumps(
                {
                    "type":
                        "error",

                    **asdict(
                        error
                    ),
                },
                ensure_ascii=False,
            )
        )

    lines.append(
        json.dumps(
            {
                "type":
                    "summary",

                **asdict(
                    result.summary
                ),
            },
            ensure_ascii=False,
        )
    )

    return (
        "\n".join(lines)
        + "\n"
    )


# ===========================================================================
# HTML REPORT
# ===========================================================================


def _html_report(
    result: ScanResult,
    config: ScanConfig,
) -> str:
    """
    Generate a self-contained interactive HTML report.

    No web server or external JavaScript libraries are required.
    """

    summary = (
        result.summary
    )

    rows: list[str] = []

    for record in (
        result.records
    ):

        display_path = (
            record.relative_path
            if config.relative_paths
            else record.full_path
        )

        escaped_path = html.escape(
            display_path
        )

        escaped_path_value = html.escape(
            display_path,
            quote=True,
        )

        escaped_extension = html.escape(
            record.extension
            or "—"
        )

        escaped_modified = html.escape(
            record.modified_utc
        )

        escaped_digest = html.escape(
            record.digest
            or "—"
        )

        line_value = (
            record.line_count
            if record.line_count
            is not None
            else -1
        )

        line_display = (
            record.line_count
            if record.line_count
            is not None
            else "—"
        )

        rows.append(
            "<tr>"

            f'<td data-value="{escaped_path_value}">'
            f"<code>{escaped_path}</code>"
            "</td>"

            f'<td data-value="{record.size_bytes}">'
            f"{html.escape(record.size_human)}"
            "</td>"

            f"<td>"
            f"{escaped_extension}"
            f"</td>"

            f"<td>"
            f"{escaped_modified}"
            f"</td>"

            f'<td data-value="{line_value}">'
            f"{line_display}"
            "</td>"

            f"<td>"
            f"<code>{escaped_digest}</code>"
            f"</td>"

            "</tr>"
        )

    # ---------------------------------------------------------------
    # Duplicate section
    # ---------------------------------------------------------------

    duplicate_html = ""

    if result.duplicates:

        groups: list[str] = []

        for group in (
            result.duplicates
        ):

            items = "".join(

                f"<li>"
                f"<code>"
                f"{html.escape(path)}"
                f"</code>"
                f"</li>"

                for path
                in group.paths
            )

            groups.append(
                "<details>"

                "<summary>"

                f"{len(group.paths)} files · "
                f"{html.escape(group.size_human)} each · "
                f"reclaimable "
                f"{html.escape(human_size(group.duplicate_bytes))}"

                "</summary>"

                f"<p>"
                f"<code>"
                f"{html.escape(group.digest)}"
                f"</code>"
                f"</p>"

                f"<ul>"
                f"{items}"
                f"</ul>"

                "</details>"
            )

        duplicate_html = (
            "<section>"
            "<h2>Duplicate content</h2>"
            + "".join(groups)
            + "</section>"
        )

    # ---------------------------------------------------------------
    # Error section
    # ---------------------------------------------------------------

    errors_html = ""

    if result.errors:

        items = "".join(

            f"<li>"
            f"<strong>"
            f"{html.escape(error.operation)}"
            f"</strong>"
            f" — "
            f"<code>"
            f"{html.escape(error.path)}"
            f"</code>: "
            f"{html.escape(error.message)}"
            f"</li>"

            for error
            in result.errors
        )

        errors_html = (
            "<section>"
            "<h2>Errors</h2>"
            f"<ul>{items}</ul>"
            "</section>"
        )

    generated = html.escape(
        datetime.now(
            timezone.utc
        ).isoformat(
            timespec="seconds"
        )
    )

    escaped_root = html.escape(
        summary.root
    )

    # ---------------------------------------------------------------
    # Entire HTML report
    # ---------------------------------------------------------------

    return f"""<!doctype html>
<html lang="en">
<head>

<meta charset="utf-8">

<meta
    name="viewport"
    content="width=device-width, initial-scale=1"
>

<title>Script Listing Report</title>

<style>

:root {{
    color-scheme: light dark;

    font-family:
        Inter,
        system-ui,
        -apple-system,
        BlinkMacSystemFont,
        "Segoe UI",
        sans-serif;
}}

* {{
    box-sizing: border-box;
}}

body {{
    margin: 0;

    background: Canvas;
    color: CanvasText;
}}

main {{
    width:
        min(
            1500px,
            calc(100% - 2rem)
        );

    margin:
        2rem auto;
}}

header {{
    display: flex;

    gap: 1rem;

    align-items: end;

    justify-content:
        space-between;

    flex-wrap: wrap;
}}

h1 {{
    margin-bottom: .25rem;
}}

.muted {{
    opacity: .7;
}}

.stats {{
    display: grid;

    grid-template-columns:
        repeat(
            auto-fit,
            minmax(
                160px,
                1fr
            )
        );

    gap: .75rem;

    margin:
        1.5rem 0;
}}

.card {{
    border:
        1px solid
        color-mix(
            in srgb,
            CanvasText 18%,
            transparent
        );

    border-radius:
        14px;

    padding:
        1rem;
}}

.card strong {{
    display: block;

    font-size:
        1.45rem;

    margin-top:
        .25rem;
}}

.controls {{
    position: sticky;

    top: 0;

    padding:
        .75rem 0;

    background:
        Canvas;

    z-index:
        2;
}}

input {{
    width:
        min(
            600px,
            100%
        );

    padding:
        .75rem .9rem;

    border-radius:
        10px;

    border:
        1px solid
        color-mix(
            in srgb,
            CanvasText 25%,
            transparent
        );

    background:
        Canvas;

    color:
        CanvasText;
}}

.table-wrap {{
    overflow:
        auto;

    border:
        1px solid
        color-mix(
            in srgb,
            CanvasText 18%,
            transparent
        );

    border-radius:
        14px;
}}

table {{
    width:
        100%;

    border-collapse:
        collapse;

    font-size:
        .92rem;
}}

th,
td {{
    text-align:
        left;

    padding:
        .7rem .8rem;

    border-bottom:
        1px solid
        color-mix(
            in srgb,
            CanvasText 12%,
            transparent
        );

    vertical-align:
        top;
}}

th {{
    cursor:
        pointer;

    user-select:
        none;

    white-space:
        nowrap;
}}

tbody tr:hover {{
    background:
        color-mix(
            in srgb,
            CanvasText 5%,
            transparent
        );
}}

code {{
    overflow-wrap:
        anywhere;
}}

details {{
    margin:
        .5rem 0;

    padding:
        .75rem;

    border:
        1px solid
        color-mix(
            in srgb,
            CanvasText 14%,
            transparent
        );

    border-radius:
        10px;
}}

section {{
    margin-top:
        2rem;
}}

</style>

</head>

<body>

<main>

<header>

<div>

<h1>
Script Listing Report
</h1>

<div class="muted">
Root: {escaped_root}
</div>

</div>

<div class="muted">
Generated {generated}
</div>

</header>


<div class="stats">

<div class="card">
Files
<strong>
{summary.total_files:,}
</strong>
</div>

<div class="card">
Total size
<strong>
{html.escape(summary.total_human)}
</strong>
</div>

<div class="card">
Directories
<strong>
{summary.directories_visited:,}
</strong>
</div>

<div class="card">
Errors
<strong>
{summary.errors:,}
</strong>
</div>

<div class="card">
Duplicate groups
<strong>
{summary.duplicate_groups:,}
</strong>
</div>

<div class="card">
Potential reclaim
<strong>
{html.escape(summary.reclaimable_duplicate_human)}
</strong>
</div>

</div>


<div class="controls">

<input
    id="filter"
    type="search"
    placeholder="Filter files…"
    aria-label="Filter files"
>

</div>


<div class="table-wrap">

<table id="files">

<thead>

<tr>

<th data-type="text">
Path ↕
</th>

<th data-type="number">
Size ↕
</th>

<th data-type="text">
Ext ↕
</th>

<th data-type="text">
Modified UTC ↕
</th>

<th data-type="number">
Lines ↕
</th>

<th data-type="text">
Digest ↕
</th>

</tr>

</thead>

<tbody>
{''.join(rows)}
</tbody>

</table>

</div>

{duplicate_html}

{errors_html}

</main>


<script>

(() => {{

    const table =
        document.querySelector(
            '#files'
        );

    const body =
        table.tBodies[0];

    const filter =
        document.querySelector(
            '#filter'
        );

    // ---------------------------------------------------------------
    // Live text filtering
    // ---------------------------------------------------------------

    filter.addEventListener(
        'input',
        () => {{

            const query =
                filter
                .value
                .toLowerCase();

            for (
                const row
                of body.rows
            ) {{

                row.hidden =
                    !row
                    .textContent
                    .toLowerCase()
                    .includes(
                        query
                    );
            }}
        }}
    );

    // ---------------------------------------------------------------
    // Clickable table sorting
    // ---------------------------------------------------------------

    table
        .querySelectorAll(
            'th'
        )
        .forEach(
            (
                th,
                column
            ) => {{

                let ascending =
                    true;

                th.addEventListener(
                    'click',
                    () => {{

                        const type =
                            th.dataset.type;

                        const rows =
                            Array.from(
                                body.rows
                            );

                        rows.sort(
                            (
                                rowA,
                                rowB
                            ) => {{

                                const cellA =
                                    rowA
                                    .cells[
                                        column
                                    ];

                                const cellB =
                                    rowB
                                    .cells[
                                        column
                                    ];

                                const valueA =
                                    cellA
                                    .dataset
                                    .value
                                    ??
                                    cellA
                                    .textContent
                                    .trim();

                                const valueB =
                                    cellB
                                    .dataset
                                    .value
                                    ??
                                    cellB
                                    .textContent
                                    .trim();

                                if (
                                    type ===
                                    'number'
                                ) {{

                                    return (
                                        (
                                            Number(
                                                valueA
                                            )
                                            -
                                            Number(
                                                valueB
                                            )
                                        )
                                        *
                                        (
                                            ascending
                                            ? 1
                                            : -1
                                        )
                                    );
                                }}

                                return (
                                    valueA
                                    .localeCompare(
                                        valueB,
                                        undefined,
                                        {{
                                            numeric:
                                                true,

                                            sensitivity:
                                                'base'
                                        }}
                                    )
                                    *
                                    (
                                        ascending
                                        ? 1
                                        : -1
                                    )
                                );
                            }}
                        );

                        ascending =
                            !ascending;

                        rows.forEach(
                            row =>
                                body.appendChild(
                                    row
                                )
                        );
                    }}
                );
            }}
        );

}})();

</script>

</body>
</html>
"""


# ===========================================================================
# REPORT DISPATCH
# ===========================================================================


def write_report(
    result: ScanResult,
    config: ScanConfig,
    report_format: str,
) -> None:
    """
    Write a report using the selected format.
    """

    report_format = (
        report_format.lower()
    )

    if report_format == "txt":

        content = _text_report(
            result,
            config,
        )

    elif report_format == "csv":

        content = _csv_report(
            result,
            config,
        )

    elif report_format == "json":

        content = _json_report(
            result,
            config,
        )

    elif report_format == "jsonl":

        content = _jsonl_report(
            result
        )

    elif report_format == "html":

        content = _html_report(
            result,
            config,
        )

    else:

        raise ValueError(
            f"Unsupported report format: "
            f"{report_format}"
        )

    _atomic_write_text(
        config.output,
        content,
    )


# ===========================================================================
# FORMAT INFERENCE
# ===========================================================================


def infer_format(
    output: Path | None,
    requested: str,
) -> str:
    """
    Infer report format from the output filename.
    """

    if requested != "auto":
        return requested

    if output:

        suffix = (
            output
            .suffix
            .lower()
        )

        return {

            ".txt":
                "txt",

            ".log":
                "txt",

            ".csv":
                "csv",

            ".json":
                "json",

            ".jsonl":
                "jsonl",

            ".ndjson":
                "jsonl",

            ".html":
                "html",

            ".htm":
                "html",

        }.get(
            suffix,
            "txt",
        )

    return "txt"


# ===========================================================================
# LEGACY ENVIRONMENT VARIABLE SUPPORT
# ===========================================================================


def default_output_path(
    report_format: str,
) -> Path:
    """
    Preserve support for the original 'logs' environment variable.

    If it is missing, ./logs is used.
    """

    logdir = (
        os.getenv("logs")
        or
        os.getenv("LOGS")
    )

    base = (
        Path(logdir).expanduser()
        if logdir
        else Path.cwd() / "logs"
    )

    suffix = {

        "txt":
            ".log",

        "csv":
            ".csv",

        "json":
            ".json",

        "jsonl":
            ".jsonl",

        "html":
            ".html",

    }[
        report_format
    ]

    return (
        base
        /
        f"{DEFAULT_LOGFILE_STEM}"
        f"{suffix}"
    )


def default_scan_root() -> Path:
    """
    Preserve support for the original 'scripts' environment variable.

    If it is missing, the current directory is scanned.
    """

    scripts = (
        os.getenv("scripts")
        or
        os.getenv("SCRIPTS")
    )

    return (
        Path(scripts).expanduser()
        if scripts
        else Path.cwd()
    )


# ===========================================================================
# ARGUMENT PARSER
# ===========================================================================


def build_parser() -> argparse.ArgumentParser:
    """
    Build the command-line interface.
    """

    parser = argparse.ArgumentParser(

        prog="script_listing.py",

        description=(
            "Recursively inventory files and generate "
            "TXT, CSV, JSON, JSONL or interactive HTML "
            "reports. Defaults to the legacy 'scripts' "
            "and 'logs' environment variables when present."
        ),

        formatter_class=(
            argparse.ArgumentDefaultsHelpFormatter
        ),
    )

    # ---------------------------------------------------------------
    # Input / output
    # ---------------------------------------------------------------

    parser.add_argument(
        "-p",
        "--path",
        type=Path,
        help="Directory to scan",
    )

    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Report output path",
    )

    parser.add_argument(
        "-f",
        "--format",

        choices=(
            "auto",
            "txt",
            "csv",
            "json",
            "jsonl",
            "html",
        ),

        default="auto",

        help=(
            "Report format; auto infers "
            "from --output suffix"
        ),
    )

    # ---------------------------------------------------------------
    # Extension filtering
    # ---------------------------------------------------------------

    parser.add_argument(
        "--extensions",

        nargs="+",

        default=[],

        metavar="EXT",

        help=(
            "Only include these extensions, "
            "e.g. py ps1 .js .tar.gz"
        ),
    )

    parser.add_argument(
        "--exclude-extensions",

        nargs="+",

        default=[],

        metavar="EXT",

        help=(
            "Exclude these extensions"
        ),
    )

    # ---------------------------------------------------------------
    # Directory filtering
    # ---------------------------------------------------------------

    parser.add_argument(
        "--exclude-dir",

        action="append",

        default=[],

        metavar="NAME",

        help=(
            "Directory name to skip; "
            "may be repeated"
        ),
    )

    parser.add_argument(
        "--no-default-excludes",

        action="store_true",

        help=(
            "Do not automatically exclude "
            ".git/.hg/.svn/__pycache__"
        ),
    )

    # ---------------------------------------------------------------
    # Glob filters
    # ---------------------------------------------------------------

    parser.add_argument(
        "--include-glob",

        action="append",

        default=[],

        metavar="PATTERN",

        help=(
            "Include only matching glob "
            "paths/names; may be repeated"
        ),
    )

    parser.add_argument(
        "--exclude-glob",

        action="append",

        default=[],

        metavar="PATTERN",

        help=(
            "Exclude matching glob paths/names; "
            "may be repeated"
        ),
    )

    # ---------------------------------------------------------------
    # Filesystem behaviour
    # ---------------------------------------------------------------

    parser.add_argument(
        "--hidden",

        action="store_true",

        help=(
            "Include hidden files/directories"
        ),
    )

    parser.add_argument(
        "--follow-symlinks",

        action="store_true",

        help=(
            "Follow directory symlinks "
            "with cycle protection"
        ),
    )

    # ---------------------------------------------------------------
    # Size filtering
    # ---------------------------------------------------------------

    parser.add_argument(
        "--min-size",

        type=parse_size,

        help=(
            "Minimum file size, e.g. 1KiB"
        ),
    )

    parser.add_argument(
        "--max-size",

        type=parse_size,

        help=(
            "Maximum file size, e.g. 10MB"
        ),
    )

    # ---------------------------------------------------------------
    # Content analysis
    # ---------------------------------------------------------------

    parser.add_argument(
        "--hash",

        dest="hash_algorithm",

        metavar="ALGORITHM",

        help=(
            "Hash every included file, "
            "e.g. sha256 or blake2b"
        ),
    )

    parser.add_argument(
        "--lines",

        action="store_true",

        help=(
            "Count lines in each included file"
        ),
    )

    parser.add_argument(
        "--duplicates",

        action="store_true",

        help=(
            "Detect duplicate content "
            "(uses SHA-256 when --hash "
            "is omitted)"
        ),
    )

    # ---------------------------------------------------------------
    # Sorting
    # ---------------------------------------------------------------

    parser.add_argument(
        "--sort",

        choices=(
            "path",
            "name",
            "extension",
            "size",
            "modified",
        ),

        default="path",

        help=(
            "Sort report records"
        ),
    )

    parser.add_argument(
        "--reverse",

        action="store_true",

        help=(
            "Reverse the selected sort"
        ),
    )

    parser.add_argument(
        "--relative",

        action="store_true",

        help=(
            "Prefer relative paths in "
            "TXT/CSV/HTML display columns"
        ),
    )

    # ---------------------------------------------------------------
    # Console behaviour
    # ---------------------------------------------------------------

    parser.add_argument(
        "-q",
        "--quiet",

        action="store_true",

        help=(
            "Suppress normal console output"
        ),
    )

    parser.add_argument(
        "-v",
        "--verbose",

        action="store_true",

        help=(
            "Enable diagnostic logging"
        ),
    )

    parser.add_argument(
        "--version",

        action="version",

        version=(
            f"%(prog)s {VERSION}"
        ),
    )

    return parser


# ===========================================================================
# LOGGING
# ===========================================================================


def configure_logging(
    verbose: bool,
) -> None:

    logging.basicConfig(

        level=(
            logging.DEBUG
            if verbose
            else logging.WARNING
        ),

        format=(
            "%(levelname)s: "
            "%(message)s"
        ),
    )


# ===========================================================================
# CONSOLE SUMMARY
# ===========================================================================


def _console_summary(
    result: ScanResult,
    output: Path,
) -> str:

    summary = (
        result.summary
    )

    lines = [

        (
            f"Report created: "
            f"{output}"
        ),

        (
            f"Files: "
            f"{summary.total_files:,}"
            f" | "

            f"Size: "
            f"{summary.total_human}"
            f" | "

            f"Directories: "
            f"{summary.directories_visited:,}"
            f" | "

            f"Errors: "
            f"{summary.errors:,}"
            f" | "

            f"Time: "
            f"{summary.elapsed_seconds:.3f}s"
        ),
    ]

    if result.duplicates:

        lines.append(
            f"Duplicate groups: "
            f"{summary.duplicate_groups:,}"
            f" | "
            f"Potential reclaim: "
            f"{summary.reclaimable_duplicate_human}"
        )

    return "\n".join(
        lines
    )


# ===========================================================================
# MAIN
# ===========================================================================


def main(
    argv: Sequence[str] | None = None,
) -> int:
    """
    Main command-line entry point.

    Exit codes
    ----------
    0
        Successful scan with no filesystem errors.

    1
        Report created but some files/directories could not be inspected.

    2
        Invalid configuration or fatal filesystem problem.
    """

    parser = (
        build_parser()
    )

    args = (
        parser.parse_args(
            argv
        )
    )

    configure_logging(
        args.verbose
    )

    # ---------------------------------------------------------------
    # Determine input path
    # ---------------------------------------------------------------

    root = (
        args.path.expanduser()
        if args.path
        else default_scan_root()
    )

    requested_output = (
        args.output.expanduser()
        if args.output
        else None
    )

    # ---------------------------------------------------------------
    # Resolve report format
    # ---------------------------------------------------------------

    report_format = (
        infer_format(
            requested_output,
            args.format,
        )
    )

    # ---------------------------------------------------------------
    # Resolve output path
    # ---------------------------------------------------------------

    output = (
        requested_output
        or
        default_output_path(
            report_format
        )
    )

    # ---------------------------------------------------------------
    # Directory exclusions
    # ---------------------------------------------------------------

    excludes = (
        set()
        if args.no_default_excludes
        else set(
            DEFAULT_EXCLUDED_DIRS
        )
    )

    excludes.update(
        args.exclude_dir
    )

    # ---------------------------------------------------------------
    # Create configuration
    # ---------------------------------------------------------------

    try:

        config = ScanConfig(

            root=root,

            output=output,

            include_extensions=set(
                args.extensions
            ),

            exclude_extensions=set(
                args.exclude_extensions
            ),

            exclude_dirs=excludes,

            include_globs=list(
                args.include_glob
            ),

            exclude_globs=list(
                args.exclude_glob
            ),

            include_hidden=(
                args.hidden
            ),

            follow_symlinks=(
                args.follow_symlinks
            ),

            min_size=(
                args.min_size
            ),

            max_size=(
                args.max_size
            ),

            hash_algorithm=(
                args.hash_algorithm
            ),

            count_lines=(
                args.lines
            ),

            detect_duplicates=(
                args.duplicates
            ),

            sort_by=(
                args.sort
            ),

            reverse=(
                args.reverse
            ),

            relative_paths=(
                args.relative
            ),
        )

        # -----------------------------------------------------------
        # Run scanner
        # -----------------------------------------------------------

        result = (
            scan_files(
                config
            )
        )

        # -----------------------------------------------------------
        # Generate report
        # -----------------------------------------------------------

        write_report(
            result,
            config,
            report_format,
        )

    except (
        ValueError,
        FileNotFoundError,
        NotADirectoryError,
        PermissionError,
    ) as exc:

        parser.exit(
            2,
            f"error: {exc}\n",
        )

    except OSError as exc:

        LOGGER.exception(
            "Operating-system error"
        )

        parser.exit(
            2,
            f"error: {exc}\n",
        )

    # ---------------------------------------------------------------
    # Console output
    # ---------------------------------------------------------------

    if not args.quiet:

        print(
            _console_summary(
                result,
                config.output,
            )
        )

    # A partial filesystem failure gets exit code 1,
    # making the program useful in scheduled jobs and CI systems.

    return (
        1
        if result.errors
        else 0
    )


# ===========================================================================
# ENTRY POINT
# ===========================================================================


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
