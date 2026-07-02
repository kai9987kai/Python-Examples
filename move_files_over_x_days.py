```python
#!/usr/bin/env python3
"""
Script Name   : move_files_over_x_days.py
Description   : Move files older than a chosen number of days from a source
                directory to a destination directory.

Examples:
    python move_files_over_x_days.py --dst /archive
    python move_files_over_x_days.py --src ./downloads --dst ./archive --days 30
    python move_files_over_x_days.py --src ./logs --dst ./archive --days 7 --recursive
    python move_files_over_x_days.py --dst ./archive --days 90 --dry-run
"""

from __future__ import annotations

import argparse
import logging
import shutil
import sys
import time
from pathlib import Path


SECONDS_PER_DAY = 24 * 60 * 60


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Move files from a source directory to a destination directory "
            "when they are older than a specified number of days."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument(
        "-src",
        "--src",
        type=Path,
        default=Path("."),
        help="Directory to move files from.",
    )
    parser.add_argument(
        "-dst",
        "--dst",
        type=Path,
        required=True,
        help="Directory to move old files into.",
    )
    parser.add_argument(
        "-days",
        "--days",
        type=float,
        default=240,
        help="Move files whose modified time is older than this many days.",
    )
    parser.add_argument(
        "-r",
        "--recursive",
        action="store_true",
        help="Also scan subdirectories.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would happen without moving any files.",
    )
    parser.add_argument(
        "--flatten",
        action="store_true",
        help=(
            "When using --recursive, place all moved files directly in the "
            "destination instead of preserving their folder structure."
        ),
    )
    parser.add_argument(
        "--on-conflict",
        choices=("rename", "skip", "overwrite"),
        default="rename",
        help="What to do when a file with the same name already exists.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show detailed information while scanning.",
    )

    return parser


def is_relative_to(path: Path, parent: Path) -> bool:
    """Return True when path is inside parent."""
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def unique_destination(path: Path) -> Path:
    """Create a non-conflicting filename such as report_1.txt."""
    if not path.exists():
        return path

    counter = 1
    while True:
        candidate = path.with_name(
            f"{path.stem}_{counter}{path.suffix}"
        )
        if not candidate.exists():
            return candidate
        counter += 1


def resolve_destination(
    source_file: Path,
    source_root: Path,
    destination_root: Path,
    recursive: bool,
    flatten: bool,
    conflict_mode: str,
) -> Path | None:
    """Work out the safe output path for a file."""
    if recursive and not flatten:
        relative_path = source_file.relative_to(source_root)
        target = destination_root / relative_path
    else:
        target = destination_root / source_file.name

    if not target.exists():
        return target

    if conflict_mode == "skip":
        logging.warning("Skipping existing destination: %s", target)
        return None

    if conflict_mode == "overwrite":
        return target

    return unique_destination(target)


def iter_files(source: Path, recursive: bool, destination: Path):
    """Yield normal files from source, avoiding the destination tree."""
    if not recursive:
        for item in source.iterdir():
            if item.is_file() and not item.is_symlink():
                yield item
        return

    for root, directories, files in __import__("os").walk(source):
        current_directory = Path(root)

        # Avoid scanning destination if it sits inside the source directory.
        directories[:] = [
            directory
            for directory in directories
            if not is_relative_to(
                (current_directory / directory).resolve(),
                destination.resolve(),
            )
        ]

        for filename in files:
            file_path = current_directory / filename
            if file_path.is_file() and not file_path.is_symlink():
                yield file_path


def move_old_files(
    source: Path,
    destination: Path,
    days: float,
    recursive: bool,
    dry_run: bool,
    flatten: bool,
    conflict_mode: str,
) -> int:
    """Move eligible files and return the number moved."""
    cutoff_time = time.time() - (days * SECONDS_PER_DAY)
    moved_count = 0
    skipped_count = 0

    for file_path in iter_files(source, recursive, destination):
        try:
            modified_time = file_path.stat().st_mtime
        except OSError as error:
            logging.error("Could not inspect %s: %s", file_path, error)
            skipped_count += 1
            continue

        if modified_time >= cutoff_time:
            logging.debug("Too recent, leaving in place: %s", file_path)
            continue

        target = resolve_destination(
            source_file=file_path,
            source_root=source,
            destination_root=destination,
            recursive=recursive,
            flatten=flatten,
            conflict_mode=conflict_mode,
        )

        if target is None:
            skipped_count += 1
            continue

        logging.info("Moving: %s -> %s", file_path, target)

        if dry_run:
            moved_count += 1
            continue

        try:
            target.parent.mkdir(parents=True, exist_ok=True)

            if target.exists() and conflict_mode == "overwrite":
                if target.is_file():
                    target.unlink()
                else:
                    logging.error(
                        "Cannot overwrite directory with file: %s", target
                    )
                    skipped_count += 1
                    continue

            shutil.move(str(file_path), str(target))
            moved_count += 1

        except (OSError, shutil.Error) as error:
            logging.error("Could not move %s: %s", file_path, error)
            skipped_count += 1

    logging.info(
        "Finished. %d file(s) %s, %d skipped.",
        moved_count,
        "would be moved" if dry_run else "moved",
        skipped_count,
    )
    return moved_count


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    if args.days < 0:
        parser.error("--days cannot be negative.")

    source = args.src.expanduser().resolve()
    destination = args.dst.expanduser().resolve()

    if not source.exists():
        parser.error(f"Source directory does not exist: {source}")

    if not source.is_dir():
        parser.error(f"Source must be a directory: {source}")

    if source == destination:
        parser.error("Source and destination cannot be the same directory.")

    # Moving a parent directory into one of its own children is unsafe.
    if is_relative_to(destination, source) and not args.recursive:
        logging.warning(
            "Destination is inside source. This is safe without --recursive, "
            "but recursive scans will automatically ignore it."
        )

    if not args.dry_run:
        try:
            destination.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            parser.error(f"Could not create destination directory: {error}")

    logging.info(
        "Scanning %s for files older than %s day(s).",
        source,
        args.days,
    )

    if args.dry_run:
        logging.info("Dry-run enabled: no files will actually be moved.")

    move_old_files(
        source=source,
        destination=destination,
        days=args.days,
        recursive=args.recursive,
        dry_run=args.dry_run,
        flatten=args.flatten,
        conflict_mode=args.on_conflict,
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
```
