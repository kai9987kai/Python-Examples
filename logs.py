#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Script Name : logs.py
Original    : Craig Richards
Modernised  : Advanced Python Edition
Version     : 3.0
Purpose     : Discover .log files, compress them into timestamped ZIP archives,
              verify the archives, optionally generate SHA-256 hashes, and
              safely remove the original logs only after successful verification.

Compatible with:
    Python 3.10+
    Windows / Linux / macOS

Examples:
    python logs.py
    python logs.py "C:\\puttylogs"
    python logs.py "C:\\puttylogs" --recursive
    python logs.py "C:\\puttylogs" --dry-run
    python logs.py "C:\\puttylogs" --keep-originals
    python logs.py "C:\\puttylogs" --sha256
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import os
import sys
import time
import zipfile

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable


# =============================================================================
# DEFAULT CONFIGURATION
# =============================================================================

DEFAULT_LOG_DIRECTORY = Path(r"C:\puttylogs")

LOG_EXTENSION = ".log"

ZIP_COMPRESSION = zipfile.ZIP_DEFLATED

# Compression level:
# 0 = no compression
# 1 = fastest
# 9 = maximum DEFLATE compression
COMPRESSION_LEVEL = 9

# Timestamp written into archive filename.
TIMESTAMP_FORMAT = "%Y-%m-%d_%H-%M-%S"

# Application log file.
APPLICATION_LOG_NAME = "log_archiver.log"

# Buffer size used when calculating SHA-256.
HASH_BUFFER_SIZE = 1024 * 1024  # 1 MiB


# =============================================================================
# DATA MODEL
# =============================================================================

@dataclass(slots=True)
class ArchiveResult:
    source: Path
    archive: Path | None
    original_size: int
    archive_size: int
    sha256: str | None
    deleted_original: bool
    success: bool
    error: str | None = None

    @property
    def compression_ratio(self) -> float:
        if self.original_size <= 0:
            return 0.0

        return (
            1.0 -
            (self.archive_size / self.original_size)
        ) * 100.0


# =============================================================================
# LOGGING
# =============================================================================

def configure_logging(directory: Path, verbose: bool) -> None:
    """
    Configure console and file logging.
    """

    level = logging.DEBUG if verbose else logging.INFO

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    handlers: list[logging.Handler] = []

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    handlers.append(console_handler)

    try:
        directory.mkdir(parents=True, exist_ok=True)

        file_handler = logging.FileHandler(
            directory / APPLICATION_LOG_NAME,
            encoding="utf-8",
        )

        file_handler.setFormatter(formatter)
        handlers.append(file_handler)

    except OSError as exc:
        print(
            f"WARNING: Unable to create application log file: {exc}",
            file=sys.stderr,
        )

    logging.basicConfig(
        level=level,
        handlers=handlers,
        force=True,
    )


# =============================================================================
# FILE DISCOVERY
# =============================================================================

def discover_logs(
    directory: Path,
    recursive: bool,
) -> Iterable[Path]:
    """
    Yield .log files from the selected directory.
    """

    pattern = f"*{LOG_EXTENSION}"

    iterator = (
        directory.rglob(pattern)
        if recursive
        else directory.glob(pattern)
    )

    for path in iterator:
        try:
            if path.is_file():
                yield path
        except OSError as exc:
            logging.warning(
                "Unable to inspect %s: %s",
                path,
                exc,
            )


# =============================================================================
# HASHING
# =============================================================================

def calculate_sha256(path: Path) -> str:
    """
    Calculate the SHA-256 hash of a file.
    """

    digest = hashlib.sha256()

    with path.open("rb") as file_handle:
        while True:
            block = file_handle.read(HASH_BUFFER_SIZE)

            if not block:
                break

            digest.update(block)

    return digest.hexdigest()


# =============================================================================
# ARCHIVE NAMING
# =============================================================================

def sanitise_timestamp(timestamp: str) -> str:
    """
    Ensure timestamp is safe for filenames.
    """

    return (
        timestamp
        .replace(":", "-")
        .replace("/", "-")
        .replace("\\", "-")
    )


def build_archive_path(source: Path) -> Path:
    """
    Generate a unique timestamped ZIP filename.

    Example:
        server.log
        ->
        server.log.2026-08-14_08-53-27.zip
    """

    timestamp = sanitise_timestamp(
        datetime.now().strftime(TIMESTAMP_FORMAT)
    )

    base_name = f"{source.name}.{timestamp}"

    archive = source.with_name(
        f"{base_name}.zip"
    )

    counter = 1

    while archive.exists():
        archive = source.with_name(
            f"{base_name}.{counter}.zip"
        )

        counter += 1

    return archive


# =============================================================================
# ZIP CREATION
# =============================================================================

def create_archive(
    source: Path,
    destination: Path,
) -> None:
    """
    Compress a log file into a ZIP archive.
    """

    with zipfile.ZipFile(
        destination,
        mode="w",
        compression=ZIP_COMPRESSION,
        compresslevel=COMPRESSION_LEVEL,
        allowZip64=True,
    ) as archive:

        archive.write(
            source,
            arcname=source.name,
        )


# =============================================================================
# ZIP VERIFICATION
# =============================================================================

def verify_archive(
    archive_path: Path,
    expected_filename: str,
) -> None:
    """
    Verify the generated ZIP file.

    Raises an exception when verification fails.
    """

    if not archive_path.exists():
        raise FileNotFoundError(
            f"Archive was not created: {archive_path}"
        )

    if archive_path.stat().st_size <= 0:
        raise ValueError(
            f"Archive is empty: {archive_path}"
        )

    with zipfile.ZipFile(
        archive_path,
        mode="r",
    ) as archive:

        bad_file = archive.testzip()

        if bad_file is not None:
            raise zipfile.BadZipFile(
                f"CRC verification failed for {bad_file}"
            )

        filenames = archive.namelist()

        if expected_filename not in filenames:
            raise ValueError(
                f"Expected file '{expected_filename}' "
                f"not found inside archive."
            )


# =============================================================================
# FILE PROCESSING
# =============================================================================

def archive_log(
    source: Path,
    *,
    delete_original: bool,
    generate_hash: bool,
    dry_run: bool,
) -> ArchiveResult:
    """
    Archive one log file.

    Critical behaviour:
        The source file is not removed until ZIP verification succeeds.
    """

    archive_path: Path | None = None

    try:
        original_size = source.stat().st_size

    except OSError as exc:
        return ArchiveResult(
            source=source,
            archive=None,
            original_size=0,
            archive_size=0,
            sha256=None,
            deleted_original=False,
            success=False,
            error=str(exc),
        )

    if dry_run:

        archive_path = build_archive_path(source)

        logging.info(
            "[DRY RUN] %s -> %s",
            source,
            archive_path,
        )

        return ArchiveResult(
            source=source,
            archive=archive_path,
            original_size=original_size,
            archive_size=0,
            sha256=None,
            deleted_original=False,
            success=True,
        )

    sha256_hash: str | None = None

    try:
        logging.info(
            "Processing: %s",
            source,
        )

        if generate_hash:
            logging.debug(
                "Calculating SHA-256..."
            )

            sha256_hash = calculate_sha256(source)

        archive_path = build_archive_path(source)

        logging.debug(
            "Creating archive: %s",
            archive_path,
        )

        create_archive(
            source,
            archive_path,
        )

        logging.debug(
            "Verifying archive integrity..."
        )

        verify_archive(
            archive_path,
            expected_filename=source.name,
        )

        archive_size = archive_path.stat().st_size

        deleted = False

        if delete_original:

            logging.debug(
                "Archive verified; deleting original."
            )

            source.unlink()

            deleted = True

        logging.info(
            "Archived successfully: %s",
            archive_path.name,
        )

        return ArchiveResult(
            source=source,
            archive=archive_path,
            original_size=original_size,
            archive_size=archive_size,
            sha256=sha256_hash,
            deleted_original=deleted,
            success=True,
        )

    except Exception as exc:

        logging.error(
            "Failed to archive %s: %s",
            source,
            exc,
        )

        #
        # Delete incomplete/corrupt archive if creation failed.
        #
        if archive_path is not None:
            try:
                if archive_path.exists():
                    archive_path.unlink()

                    logging.warning(
                        "Removed incomplete archive: %s",
                        archive_path,
                    )

            except OSError as cleanup_error:

                logging.error(
                    "Could not remove incomplete archive %s: %s",
                    archive_path,
                    cleanup_error,
                )

        return ArchiveResult(
            source=source,
            archive=None,
            original_size=original_size,
            archive_size=0,
            sha256=sha256_hash,
            deleted_original=False,
            success=False,
            error=str(exc),
        )


# =============================================================================
# HUMAN READABLE FILE SIZE
# =============================================================================

def human_size(size: int) -> str:
    """
    Convert byte count into a human-readable representation.
    """

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

        if abs(value) < 1024.0:
            return f"{value:,.2f} {unit}"

        value /= 1024.0

    return f"{value:,.2f} EiB"


# =============================================================================
# SUMMARY
# =============================================================================

def display_summary(
    results: list[ArchiveResult],
    elapsed: float,
) -> None:
    """
    Display execution statistics.
    """

    successful = [
        result
        for result in results
        if result.success
    ]

    failed = [
        result
        for result in results
        if not result.success
    ]

    original_bytes = sum(
        result.original_size
        for result in successful
    )

    archive_bytes = sum(
        result.archive_size
        for result in successful
    )

    if original_bytes:
        saving = (
            1.0 -
            archive_bytes / original_bytes
        ) * 100.0
    else:
        saving = 0.0

    print()
    print("=" * 72)
    print(" LOG ARCHIVER SUMMARY")
    print("=" * 72)

    print(
        f"Files discovered : {len(results)}"
    )

    print(
        f"Successful       : {len(successful)}"
    )

    print(
        f"Failed           : {len(failed)}"
    )

    print(
        f"Original size    : {human_size(original_bytes)}"
    )

    print(
        f"Archive size     : {human_size(archive_bytes)}"
    )

    print(
        f"Space reduction  : {saving:.2f}%"
    )

    print(
        f"Execution time   : {elapsed:.3f} seconds"
    )

    print("=" * 72)

    if failed:

        print()
        print("FAILED FILES")
        print("-" * 72)

        for result in failed:
            print(
                f"{result.source}: {result.error}"
            )

    hash_results = [
        result
        for result in successful
        if result.sha256
    ]

    if hash_results:

        print()
        print("SHA-256")
        print("-" * 72)

        for result in hash_results:

            print(
                f"{result.source.name}"
            )

            print(
                f"  {result.sha256}"
            )


# =============================================================================
# COMMAND LINE
# =============================================================================

def parse_arguments() -> argparse.Namespace:
    """
    Parse CLI arguments.
    """

    parser = argparse.ArgumentParser(
        description=(
            "Safely compress .log files into timestamped ZIP archives."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument(
        "directory",
        nargs="?",
        type=Path,
        default=DEFAULT_LOG_DIRECTORY,
        help="Directory containing log files.",
    )

    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Search through subdirectories.",
    )

    parser.add_argument(
        "--keep-originals",
        action="store_true",
        help="Do not delete original log files after archiving.",
    )

    parser.add_argument(
        "--sha256",
        action="store_true",
        help="Calculate SHA-256 for each original log file.",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Show what would be processed without creating "
            "or deleting anything."
        ),
    )

    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable detailed diagnostic output.",
    )

    return parser.parse_args()


# =============================================================================
# MAIN
# =============================================================================

def main() -> int:

    args = parse_arguments()

    logs_directory = (
        args.directory
        .expanduser()
        .resolve()
    )

    configure_logging(
        logs_directory,
        args.verbose,
    )

    logging.info(
        "Log Archiver 3.0"
    )

    logging.info(
        "Directory: %s",
        logs_directory,
    )

    if not logs_directory.exists():

        logging.error(
            "Directory does not exist: %s",
            logs_directory,
        )

        return 1

    if not logs_directory.is_dir():

        logging.error(
            "Path is not a directory: %s",
            logs_directory,
        )

        return 1

    start_time = time.perf_counter()

    log_files = sorted(
        discover_logs(
            logs_directory,
            recursive=args.recursive,
        )
    )

    if not log_files:

        logging.info(
            "No %s files found.",
            LOG_EXTENSION,
        )

        return 0

    logging.info(
        "Found %d log file(s).",
        len(log_files),
    )

    results: list[ArchiveResult] = []

    for log_file in log_files:

        result = archive_log(
            log_file,
            delete_original=not args.keep_originals,
            generate_hash=args.sha256,
            dry_run=args.dry_run,
        )

        results.append(result)

    elapsed = (
        time.perf_counter() -
        start_time
    )

    display_summary(
        results,
        elapsed,
    )

    failures = sum(
        not result.success
        for result in results
    )

    if failures:
        return 2

    return 0


# =============================================================================
# ENTRY POINT
# =============================================================================

if __name__ == "__main__":

    try:
        exit_code = main()

    except KeyboardInterrupt:

        print(
            "\nOperation cancelled by user.",
            file=sys.stderr,
        )

        exit_code = 130

    except Exception as exc:

        logging.exception(
            "Unexpected fatal error: %s",
            exc,
        )

        exit_code = 1

    sys.exit(exit_code)
