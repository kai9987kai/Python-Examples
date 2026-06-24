#!/usr/bin/env python3
"""
daily_checks.py

Launches the applications and documents needed for routine daily system checks.

Configuration:
    The PuTTY configuration file contains one saved PuTTY session name per line.
    Blank lines and lines beginning with # are ignored.

Example:
    production-db
    web-server-01
    # legacy-server
"""

from __future__ import annotations

import argparse
import getpass
import logging
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from time import strftime


DEFAULT_DAILY_DOC = Path(r"P:\Documentation\Daily Docs\Back office Daily Checks.doc")
DEFAULT_EUROCLEAR_DOC = Path(
    r"\\fs1\pub_b\Pub_Admin\Documentation\Settlements_Files\PWD\Eclr.doc"
)
DEFAULT_RDP_FILE = Path("eclr.rdp")
DEFAULT_CONFIG_NAME = "daily_checks_servers.conf"


class DailyChecksRunner:
    """Runs the daily-check tools while tracking failures."""

    def __init__(self, dry_run: bool = False) -> None:
        self.dry_run = dry_run
        self.failures = 0

    def launch(self, label: str, command: list[str]) -> None:
        """Launch a command without using a shell."""
        logging.info("%s: %s", label, subprocess.list2cmdline(command))

        if self.dry_run:
            print(f"[DRY RUN] {label}")
            return

        try:
            subprocess.Popen(command)
            print(f"Started: {label}")
        except FileNotFoundError:
            self.failures += 1
            logging.exception("Executable not found while starting %s", label)
            print(f"ERROR: Could not find the program needed for: {label}")
        except OSError:
            self.failures += 1
            logging.exception("Could not start %s", label)
            print(f"ERROR: Could not start: {label}")

    def open_file(self, label: str, file_path: Path) -> None:
        """Open a file using its default Windows application."""
        logging.info("%s: %s", label, file_path)

        if not file_path.exists():
            self.failures += 1
            logging.error("File does not exist: %s", file_path)
            print(f"ERROR: File not found: {file_path}")
            return

        if self.dry_run:
            print(f"[DRY RUN] Open: {file_path}")
            return

        try:
            os.startfile(str(file_path))  # Windows-only, opens default application.
            print(f"Opened: {label}")
        except OSError:
            self.failures += 1
            logging.exception("Could not open file: %s", file_path)
            print(f"ERROR: Could not open: {file_path}")


def clear_screen() -> None:
    """Clear the terminal screen."""
    os.system("cls" if os.name == "nt" else "clear")


def configure_logging(log_file: Path | None, verbose: bool) -> None:
    """Configure console and optional file logging."""
    level = logging.DEBUG if verbose else logging.INFO

    handlers: list[logging.Handler] = [logging.StreamHandler()]

    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))

    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=handlers,
    )


def find_word_executable(explicit_path: str | None) -> str | None:
    """Find Microsoft Word, using an explicit path, PATH, or common install paths."""
    if explicit_path:
        path = Path(os.path.expandvars(explicit_path)).expanduser()
        if path.is_file():
            return str(path)

        resolved = shutil.which(explicit_path)
        if resolved:
            return resolved

        return None

    from_path = shutil.which("winword.exe")
    if from_path:
        return from_path

    possible_bases = [
        os.getenv("ProgramFiles"),
        os.getenv("ProgramFiles(x86)"),
        os.getenv("LOCALAPPDATA"),
    ]

    possible_suffixes = [
        Path("Microsoft Office/root/Office16/WINWORD.EXE"),
        Path("Microsoft Office/Office16/WINWORD.EXE"),
        Path("Microsoft Office/Office15/WINWORD.EXE"),
        Path("Microsoft Office/Office14/WINWORD.EXE"),
    ]

    for base in possible_bases:
        if not base:
            continue

        for suffix in possible_suffixes:
            candidate = Path(base) / suffix
            if candidate.is_file():
                return str(candidate)

    return None


def load_putty_sessions(config_path: Path) -> list[str]:
    """Read saved PuTTY session names from the configuration file."""
    if not config_path.is_file():
        raise FileNotFoundError(f"PuTTY configuration file was not found: {config_path}")

    sessions: list[str] = []

    with config_path.open("r", encoding="utf-8") as config_file:
        for line_number, raw_line in enumerate(config_file, start=1):
            session = raw_line.strip()

            if not session or session.startswith("#"):
                continue

            if "\x00" in session:
                logging.warning(
                    "Ignoring invalid PuTTY session on line %d in %s",
                    line_number,
                    config_path,
                )
                continue

            sessions.append(session)

    return sessions


def print_daily_checks(
    runner: DailyChecksRunner,
    daily_doc: Path,
    word_executable: str | None,
) -> None:
    """Print the daily checks document through Microsoft Word."""
    print("\nPrinting Daily Check Sheets...")

    if not daily_doc.is_file():
        runner.failures += 1
        print(f"ERROR: Daily checks document not found: {daily_doc}")
        logging.error("Daily checks document not found: %s", daily_doc)
        return

    if not word_executable:
        runner.failures += 1
        print("ERROR: Microsoft Word was not found.")
        print("       Add winword.exe to PATH or use --word-exe.")
        logging.error("Microsoft Word could not be located")
        return

    runner.launch(
        "Print Daily Check Sheets",
        [
            word_executable,
            str(daily_doc),
            "/mFilePrintDefault",
            "/mFileExit",
        ],
    )


def launch_putty_sessions(
    runner: DailyChecksRunner,
    config_path: Path,
    putty_executable: str,
) -> None:
    """Launch all configured PuTTY saved sessions."""
    print("\nLoading PuTTY Sessions...")

    try:
        sessions = load_putty_sessions(config_path)
    except (OSError, UnicodeError) as error:
        runner.failures += 1
        logging.exception("Could not load PuTTY configuration")
        print(f"ERROR: Could not load PuTTY configuration: {error}")
        return

    if not sessions:
        print("No PuTTY sessions were found in the configuration file.")
        return

    for session in sessions:
        runner.launch(f"PuTTY session: {session}", [putty_executable, "-load", session])


def launch_rdp_session(
    runner: DailyChecksRunner,
    rdp_file: Path,
) -> None:
    """Launch the configured Remote Desktop connection."""
    print("\nLoading RDP Session...")

    if not rdp_file.is_file():
        runner.failures += 1
        print(f"ERROR: RDP file not found: {rdp_file}")
        logging.error("RDP file not found: %s", rdp_file)
        return

    runner.launch("Remote Desktop", ["mstsc.exe", str(rdp_file)])


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Launch applications and documents for daily operational checks."
    )

    parser.add_argument(
        "--config",
        type=Path,
        help="Path to the PuTTY sessions configuration file.",
    )
    parser.add_argument(
        "--putty-exe",
        default="putty.exe",
        help="PuTTY executable or full path. Default: putty.exe",
    )
    parser.add_argument(
        "--word-exe",
        help="Microsoft Word executable or full path.",
    )
    parser.add_argument(
        "--daily-doc",
        type=Path,
        default=DEFAULT_DAILY_DOC,
        help="Daily checks document path.",
    )
    parser.add_argument(
        "--rdp-file",
        type=Path,
        default=DEFAULT_RDP_FILE,
        help="Remote Desktop connection file.",
    )
    parser.add_argument(
        "--euroclear-doc",
        type=Path,
        default=DEFAULT_EUROCLEAR_DOC,
        help="Euroclear password document path.",
    )
    parser.add_argument(
        "--skip-print",
        action="store_true",
        help="Do not print the daily checks document.",
    )
    parser.add_argument(
        "--skip-putty",
        action="store_true",
        help="Do not launch PuTTY sessions.",
    )
    parser.add_argument(
        "--skip-rdp",
        action="store_true",
        help="Do not launch the RDP session.",
    )
    parser.add_argument(
        "--skip-euroclear",
        action="store_true",
        help="Do not open the Euroclear document.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show intended actions without launching anything.",
    )
    parser.add_argument(
        "--no-clear",
        action="store_true",
        help="Do not clear the terminal before running.",
    )
    parser.add_argument(
        "--log-file",
        type=Path,
        help="Optional path for a log file.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable detailed logging.",
    )

    return parser.parse_args()


def get_default_config_path() -> Path:
    """Build the default config path from the my_config environment variable."""
    config_directory = os.getenv("my_config")

    if not config_directory:
        raise EnvironmentError(
            "The my_config environment variable is not set. "
            "Set it or supply --config."
        )

    return Path(config_directory) / DEFAULT_CONFIG_NAME


def main() -> int:
    args = parse_arguments()
    configure_logging(args.log_file, args.verbose)

    if not args.no_clear:
        clear_screen()

    script_name = Path(sys.argv[0]).name
    username = os.getenv("USERNAME") or getpass.getuser()

    print(
        f"Good morning {username}. "
        f"{script_name} ran at {strftime('%Y-%m-%d %H:%M:%S')} "
        f"on {platform.node()} from {Path.cwd()}"
    )

    logging.info("Daily checks started")
    runner = DailyChecksRunner(dry_run=args.dry_run)

    if not args.skip_print:
        word_executable = find_word_executable(args.word_exe)
        print_daily_checks(runner, args.daily_doc, word_executable)

    if not args.skip_putty:
        try:
            config_path = args.config or get_default_config_path()
            launch_putty_sessions(runner, config_path, args.putty_exe)
        except EnvironmentError as error:
            runner.failures += 1
            logging.error("%s", error)
            print(f"\nERROR: {error}")

    if not args.skip_rdp:
        launch_rdp_session(runner, args.rdp_file)

    if not args.skip_euroclear:
        print("\nOpening Euroclear Document...")
        runner.open_file("Euroclear document", args.euroclear_doc)

    if runner.failures:
        print(f"\nCompleted with {runner.failures} issue(s). Check the log for details.")
        logging.warning("Daily checks completed with %d issue(s)", runner.failures)
        return 1

    print("\nDaily checks launched successfully.")
    logging.info("Daily checks completed successfully")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
