#!/usr/bin/env python3
"""
backup_automator_services.py

Back up selected macOS Automator Service workflows listed in services.conf.

Environment variables supported:
    my_config or MY_CONFIG  -> directory containing services.conf
    dropbox or DROPBOX      -> Dropbox folder path

Example services.conf:
    My Service.workflow
    Resize Images.workflow
    # Lines beginning with # are ignored
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import os
import shutil
import sys
from pathlib import Path


APP_NAME = "Automator Services Backup"
DEFAULT_CONFIG_NAME = "services.conf"
DEFAULT_SOURCE_DIR = Path.home() / "Library" / "Services"


def get_environment_path(*names: str) -> Path | None:
    """Return the first configured environment-variable path."""
    for name in names:
        value = os.getenv(name)
        if value:
            return Path(value).expanduser()
    return None


def read_service_list(config_file: Path) -> list[str]:
    """Read workflow names, ignoring blank lines and comments."""
    services = []

    with config_file.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            entry = line.strip()

            if not entry or entry.startswith("#"):
                continue

            # Avoid accidental absolute paths or directory traversal.
            if Path(entry).is_absolute() or ".." in Path(entry).parts:
                logging.warning(
                    "Skipping unsafe entry on line %d: %s",
                    line_number,
                    entry,
                )
                continue

            services.append(entry)

    return services


def make_backup_directory(dropbox_dir: Path) -> Path:
    """Create a unique dated backup folder."""
    timestamp = dt.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    backup_dir = (
        dropbox_dir
        / "My_backups"
        / "Automator_services"
        / timestamp
    )

    backup_dir.mkdir(parents=True, exist_ok=False)
    return backup_dir


def copy_service(source: Path, destination: Path, dry_run: bool = False) -> None:
    """Copy either a workflow bundle/directory or a normal file."""
    if dry_run:
        logging.info("[DRY RUN] Would copy: %s -> %s", source, destination)
        return

    if source.is_dir():
        shutil.copytree(source, destination, symlinks=True)
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination, follow_symlinks=False)


def backup_services(
    source_dir: Path,
    config_file: Path,
    dropbox_dir: Path,
    dry_run: bool = False,
) -> int:
    """Perform the backup and return a process exit code."""
    if not source_dir.is_dir():
        logging.error("Automator Services directory not found: %s", source_dir)
        return 1

    if not config_file.is_file():
        logging.error("Configuration file not found: %s", config_file)
        return 1

    if not dropbox_dir.is_dir():
        logging.error("Dropbox directory not found: %s", dropbox_dir)
        return 1

    services = read_service_list(config_file)

    if not services:
        logging.warning("No services were listed in: %s", config_file)
        return 0

    backup_dir = (
        dropbox_dir
        / "My_backups"
        / "Automator_services"
        / dt.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    )

    if dry_run:
        logging.info("[DRY RUN] Backup folder would be: %s", backup_dir)
    else:
        backup_dir = make_backup_directory(dropbox_dir)
        logging.info("Created backup folder: %s", backup_dir)

    copied = 0
    missing = 0
    failed = 0

    for service_name in services:
        source = source_dir / service_name
        destination = backup_dir / service_name

        if not source.exists():
            logging.warning("Missing service: %s", source)
            missing += 1
            continue

        try:
            copy_service(source, destination, dry_run=dry_run)
            logging.info("Backed up: %s", service_name)
            copied += 1
        except OSError as error:
            logging.error("Could not copy %s: %s", service_name, error)
            failed += 1

    logging.info(
        "Backup complete — copied: %d, missing: %d, failed: %d",
        copied,
        missing,
        failed,
    )

    return 1 if failed else 0


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Back up selected macOS Automator Service workflows."
    )

    parser.add_argument(
        "--source",
        type=Path,
        default=DEFAULT_SOURCE_DIR,
        help=f"Automator Services directory (default: {DEFAULT_SOURCE_DIR})",
    )

    parser.add_argument(
        "--config",
        type=Path,
        help="Path to services.conf. Defaults to my_config/services.conf.",
    )

    parser.add_argument(
        "--dropbox",
        type=Path,
        help="Dropbox folder. Defaults to the dropbox environment variable.",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be copied without changing files.",
    )

    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show detailed logging.",
    )

    return parser.parse_args()


def main() -> int:
    args = parse_arguments()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    config_dir = get_environment_path("my_config", "MY_CONFIG")
    dropbox_dir = args.dropbox or get_environment_path("dropbox", "DROPBOX")

    config_file = args.config
    if config_file is None:
        if config_dir is None:
            logging.error(
                "Set my_config/MY_CONFIG or provide --config /path/to/services.conf"
            )
            return 1
        config_file = config_dir / DEFAULT_CONFIG_NAME

    if dropbox_dir is None:
        logging.error(
            "Set dropbox/DROPBOX or provide --dropbox /path/to/Dropbox"
        )
        return 1

    return backup_services(
        source_dir=args.source.expanduser(),
        config_file=config_file.expanduser(),
        dropbox_dir=dropbox_dir.expanduser(),
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    sys.exit(main())
