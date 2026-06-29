#!/usr/bin/env python3
"""
SQLite File Auditor
Scans a directory tree and identifies genuine SQLite 3 database files
by checking their binary file header.

Examples:
    python check_for_sqlite_files.py
    python check_for_sqlite_files.py C:\\Users\\Kai\\Documents
    python check_for_sqlite_files.py . --report-all
    python check_for_sqlite_files.py . --integrity-check
    python check_for_sqlite_files.py . --json-report sqlite_audit.json
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterator


SQLITE_HEADER = b"SQLite format 3\x00"
MIN_SQLITE_HEADER_SIZE = 100


@dataclass
class ScanResult:
    path: str
    status: str
    size_bytes: int | None = None
    detail: str | None = None


def is_sqlite_database(path: Path) -> tuple[bool, str | None]:
    """
    Check whether a file appears to be a SQLite 3 database by inspecting
    its first 16 bytes.
    """
    try:
        if not path.is_file():
            return False, "Not a regular file"

        file_size = path.stat().st_size
        if file_size < MIN_SQLITE_HEADER_SIZE:
            return False, f"Too small for SQLite header ({file_size} bytes)"

        with path.open("rb") as file:
            header = file.read(len(SQLITE_HEADER))

        if header == SQLITE_HEADER:
            return True, None

        return False, "SQLite header not found"

    except PermissionError:
        return False, "Permission denied"
    except OSError as error:
        return False, f"File error: {error}"


def check_sqlite_integrity(path: Path) -> str:
    """
    Runs SQLite's quick_check in read-only mode.
    This is optional because it may be slow on large databases.
    """
    try:
        database_uri = f"{path.resolve().as_uri()}?mode=ro"

        with sqlite3.connect(database_uri, uri=True) as connection:
            result = connection.execute("PRAGMA quick_check(1)").fetchone()

        if result and result[0].lower() == "ok":
            return "Integrity check passed"

        return f"Integrity issue: {result[0] if result else 'Unknown result'}"

    except sqlite3.DatabaseError as error:
        return f"SQLite error: {error}"
    except OSError as error:
        return f"File error: {error}"


def scan_directory(
    root_directory: Path,
    excluded_directories: set[str],
    integrity_check: bool,
) -> Iterator[ScanResult]:
    """Recursively scan a directory tree for SQLite database files."""

    def walk_error(error: OSError) -> None:
        print(f"[!] Could not access: {error}", file=sys.stderr)

    for current_root, directories, files in os.walk(
        root_directory,
        topdown=True,
        onerror=walk_error,
        followlinks=False,
    ):
        directories[:] = [
            directory
            for directory in directories
            if directory not in excluded_directories
        ]

        current_path = Path(current_root)

        for filename in files:
            file_path = current_path / filename

            try:
                file_size = file_path.stat().st_size
            except OSError:
                file_size = None

            is_sqlite, reason = is_sqlite_database(file_path)

            if is_sqlite:
                detail = "SQLite 3 database detected"

                if integrity_check:
                    detail += f" | {check_sqlite_integrity(file_path)}"

                yield ScanResult(
                    path=str(file_path),
                    status="sqlite",
                    size_bytes=file_size,
                    detail=detail,
                )
            else:
                status = "error" if reason and (
                    "Permission denied" in reason or "error:" in reason.lower()
                ) else "not_sqlite"

                yield ScanResult(
                    path=str(file_path),
                    status=status,
                    size_bytes=file_size,
                    detail=reason,
                )


def write_text_report(results: list[ScanResult], report_path: Path, report_all: bool) -> None:
    """Write a readable audit report."""
    sqlite_count = sum(result.status == "sqlite" for result in results)
    error_count = sum(result.status == "error" for result in results)
    scanned_count = len(results)

    with report_path.open("w", encoding="utf-8") as report:
        report.write("SQLite Database Audit Report\n")
        report.write("=" * 70 + "\n")
        report.write(f"Files scanned: {scanned_count}\n")
        report.write(f"SQLite databases found: {sqlite_count}\n")
        report.write(f"Errors encountered: {error_count}\n")
        report.write("=" * 70 + "\n\n")

        for result in results:
            if not report_all and result.status != "sqlite":
                continue

            size_text = (
                f"{result.size_bytes:,} bytes"
                if result.size_bytes is not None
                else "Unknown size"
            )

            report.write(
                f"[{result.status.upper()}] {result.path}\n"
                f"    Size: {size_text}\n"
                f"    Detail: {result.detail or 'None'}\n\n"
            )


def write_json_report(results: list[ScanResult], report_path: Path) -> None:
    """Write machine-readable JSON report."""
    with report_path.open("w", encoding="utf-8") as report:
        json.dump(
            {
                "summary": {
                    "files_scanned": len(results),
                    "sqlite_databases_found": sum(
                        result.status == "sqlite" for result in results
                    ),
                    "errors": sum(result.status == "error" for result in results),
                },
                "results": [asdict(result) for result in results],
            },
            report,
            indent=2,
        )


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Recursively detect SQLite 3 databases using their file header."
    )

    parser.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="Directory to scan. Defaults to the current directory.",
    )

    parser.add_argument(
        "--report",
        default="sqlite_audit.txt",
        help="Text report output path. Default: sqlite_audit.txt",
    )

    parser.add_argument(
        "--json-report",
        help="Optional JSON report output path.",
    )

    parser.add_argument(
        "--report-all",
        action="store_true",
        help="Include non-SQLite files in the text report.",
    )

    parser.add_argument(
        "--integrity-check",
        action="store_true",
        help="Run SQLite quick_check on detected databases.",
    )

    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="FOLDER",
        help="Folder name to skip. Can be used multiple times.",
    )

    return parser.parse_args()


def main() -> int:
    args = parse_arguments()

    root_directory = Path(args.directory).expanduser()

    if not root_directory.exists():
        print(f"[!] Directory does not exist: {root_directory}", file=sys.stderr)
        return 1

    if not root_directory.is_dir():
        print(f"[!] Path is not a directory: {root_directory}", file=sys.stderr)
        return 1

    excluded_directories = {
        ".git",
        "__pycache__",
        "node_modules",
        *args.exclude,
    }

    print(f"[*] Scanning: {root_directory.resolve()}")
    print(f"[*] Excluding: {', '.join(sorted(excluded_directories))}")
    print()

    results = list(
        scan_directory(
            root_directory=root_directory,
            excluded_directories=excluded_directories,
            integrity_check=args.integrity_check,
        )
    )

    sqlite_files = [result for result in results if result.status == "sqlite"]

    for result in sqlite_files:
        print(f"[+] SQLite database found: {result.path}")
        print(f"    {result.detail}")

    if not sqlite_files:
        print("[-] No SQLite databases found.")

    text_report_path = Path(args.report)
    write_text_report(results, text_report_path, args.report_all)

    print()
    print(f"[*] Text report written to: {text_report_path.resolve()}")
    print(f"[*] Files scanned: {len(results)}")
    print(f"[*] SQLite databases found: {len(sqlite_files)}")

    if args.json_report:
        json_report_path = Path(args.json_report)
        write_json_report(results, json_report_path)
        print(f"[*] JSON report written to: {json_report_path.resolve()}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
