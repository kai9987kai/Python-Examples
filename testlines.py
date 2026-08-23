#!/usr/bin/env python3
"""
Script Name : testlines.py
Original    : Craig Richards
Created     : 08 December 2011
Modified by : Beven Nyamande
Modernised  : 2026
Version     : 3.0

Description:
    A modern text-file writing utility.

Features:
    - Python 3 type hints
    - pathlib instead of raw path strings
    - UTF-8 encoding
    - Automatic parent-directory creation
    - Normal write and append modes
    - Atomic writes to reduce file-corruption risk
    - Optional backup creation
    - Command-line interface
    - Logging
    - Detailed error handling
    - File verification
    - Meaningful exit codes
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Final


APP_NAME: Final[str] = "testlines"
VERSION: Final[str] = "3.0"
DEFAULT_FILENAME: Final[str] = "test.txt"
DEFAULT_TEXT: Final[str] = "I am beven"
DEFAULT_ENCODING: Final[str] = "utf-8"


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

logger = logging.getLogger(APP_NAME)


class FileWriteError(Exception):
    """Raised when a file cannot be written successfully."""


def ensure_parent_directory(path: Path) -> None:
    """
    Create the target file's parent directory if necessary.

    Args:
        path:
            Destination file path.
    """
    parent = path.parent

    if parent != Path("."):
        parent.mkdir(
            parents=True,
            exist_ok=True,
        )


def create_backup(path: Path) -> Path | None:
    """
    Create a backup of an existing file.

    Example:
        test.txt -> test.txt.bak

    Args:
        path:
            Original file.

    Returns:
        Path to the backup, or None if the original does not exist.
    """
    if not path.exists():
        return None

    backup_path = path.with_name(f"{path.name}.bak")

    shutil.copy2(
        path,
        backup_path,
    )

    logger.info(
        "Backup created: %s",
        backup_path.resolve(),
    )

    return backup_path


def atomic_write(
    path: Path,
    text: str,
    *,
    encoding: str = DEFAULT_ENCODING,
) -> int:
    """
    Atomically replace a file with new text.

    The text is first written to a temporary file in the same
    directory. os.replace() then swaps the temporary file into the
    destination.

    This helps prevent an interrupted write from leaving a partially
    written destination file.

    Args:
        path:
            Destination file.

        text:
            Text to write.

        encoding:
            Character encoding.

    Returns:
        Number of characters written.

    Raises:
        FileWriteError:
            If the operation fails.
    """
    ensure_parent_directory(path)

    temp_path: Path | None = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding=encoding,
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
            newline="",
        ) as temporary_file:

            temporary_file.write(text)

            # Explicitly flush Python's buffer.
            temporary_file.flush()

            # Ask the operating system to flush buffered data.
            os.fsync(temporary_file.fileno())

            temp_path = Path(temporary_file.name)

        os.replace(
            temp_path,
            path,
        )

        return len(text)

    except (OSError, UnicodeError) as exc:
        if temp_path is not None and temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass

        raise FileWriteError(
            f"Unable to write '{path}': {exc}"
        ) from exc


def append_text(
    path: Path,
    text: str,
    *,
    encoding: str = DEFAULT_ENCODING,
) -> int:
    """
    Append text to a file.

    Args:
        path:
            Destination file.

        text:
            Text to append.

        encoding:
            Character encoding.

    Returns:
        Number of characters appended.

    Raises:
        FileWriteError:
            If appending fails.
    """
    ensure_parent_directory(path)

    try:
        with path.open(
            mode="a",
            encoding=encoding,
            newline="",
        ) as file_object:

            characters_written = file_object.write(text)

            file_object.flush()

            os.fsync(file_object.fileno())

            return characters_written

    except (OSError, UnicodeError) as exc:
        raise FileWriteError(
            f"Unable to append to '{path}': {exc}"
        ) from exc


def verify_file(
    path: Path,
    expected_text: str,
    *,
    append: bool,
    encoding: str = DEFAULT_ENCODING,
) -> bool:
    """
    Verify that the file contains the expected data.

    Args:
        path:
            File to check.

        expected_text:
            Text expected in the output.

        append:
            Whether append mode was used.

        encoding:
            Character encoding.

    Returns:
        True when verification succeeds.
    """
    try:
        actual_text = path.read_text(
            encoding=encoding,
        )

    except OSError as exc:
        logger.error(
            "Unable to verify file: %s",
            exc,
        )

        return False

    if append:
        return actual_text.endswith(expected_text)

    return actual_text == expected_text


def write_to_file(
    filename: str | Path,
    text: str,
    *,
    append: bool = False,
    backup: bool = False,
    verify: bool = True,
    encoding: str = DEFAULT_ENCODING,
) -> int:
    """
    Write text to a file.

    Args:
        filename:
            Destination filename.

        text:
            Text to write.

        append:
            Append rather than replacing the file.

        backup:
            Create a .bak copy before overwriting.

        verify:
            Re-read and verify the resulting file.

        encoding:
            Text encoding.

    Returns:
        Number of characters written.

    Raises:
        FileWriteError:
            If writing or verification fails.
    """
    path = Path(filename).expanduser()

    if path.exists() and path.is_dir():
        raise FileWriteError(
            f"Destination is a directory, not a file: {path}"
        )

    if backup and path.exists():
        create_backup(path)

    if append:
        characters_written = append_text(
            path,
            text,
            encoding=encoding,
        )

    else:
        characters_written = atomic_write(
            path,
            text,
            encoding=encoding,
        )

    if verify:
        success = verify_file(
            path,
            text,
            append=append,
            encoding=encoding,
        )

        if not success:
            raise FileWriteError(
                f"Verification failed for '{path}'."
            )

    logger.info(
        "Successfully wrote %d characters to %s",
        characters_written,
        path.resolve(),
    )

    return characters_written


def build_argument_parser() -> argparse.ArgumentParser:
    """Construct the program's command-line argument parser."""

    parser = argparse.ArgumentParser(
        prog=APP_NAME,
        description=(
            "Safely write or append text to a text file."
        ),
    )

    parser.add_argument(
        "filename",
        nargs="?",
        default=DEFAULT_FILENAME,
        help=(
            "Destination file "
            f"(default: {DEFAULT_FILENAME})"
        ),
    )

    parser.add_argument(
        "text",
        nargs="?",
        default=DEFAULT_TEXT,
        help=(
            "Text to write "
            f"(default: {DEFAULT_TEXT!r})"
        ),
    )

    parser.add_argument(
        "-a",
        "--append",
        action="store_true",
        help="Append text instead of replacing the file.",
    )

    parser.add_argument(
        "-b",
        "--backup",
        action="store_true",
        help="Create a .bak backup of an existing file.",
    )

    parser.add_argument(
        "--newline",
        action="store_true",
        help="Add a newline after the supplied text.",
    )

    parser.add_argument(
        "--no-verify",
        action="store_true",
        help="Disable post-write verification.",
    )

    parser.add_argument(
        "--encoding",
        default=DEFAULT_ENCODING,
        help=(
            "Character encoding "
            f"(default: {DEFAULT_ENCODING})"
        ),
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {VERSION}",
    )

    return parser


def main() -> int:
    """
    Program entry point.

    Returns:
        Process exit status.
    """
    parser = build_argument_parser()
    args = parser.parse_args()

    text = args.text

    if args.newline:
        text += "\n"

    try:
        characters_written = write_to_file(
            filename=args.filename,
            text=text,
            append=args.append,
            backup=args.backup,
            verify=not args.no_verify,
            encoding=args.encoding,
        )

    except FileWriteError as exc:
        logger.error("%s", exc)
        return 1

    except LookupError as exc:
        logger.error(
            "Unknown encoding '%s': %s",
            args.encoding,
            exc,
        )
        return 2

    print(
        f"Written successfully: "
        f"{characters_written} characters"
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
