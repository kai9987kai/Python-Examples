```python
#!/usr/bin/env python3
"""
Advanced text-file reader.

Examples:
    python file_reader.py notes.txt
    python file_reader.py notes.txt --lines 5
    python file_reader.py notes.txt --start 10 --lines 4
    python file_reader.py notes.txt --preview
    python file_reader.py notes.txt --encoding latin-1
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO


@dataclass
class FileStats:
    path: Path
    size_bytes: int
    total_lines: int
    total_words: int
    total_characters: int


def get_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read, inspect, rewind, and print text files."
    )

    parser.add_argument(
        "input_file",
        type=Path,
        help="The text file to read.",
    )
    parser.add_argument(
        "--lines",
        "-n",
        type=int,
        default=3,
        help="Number of lines to print after rewinding. Default: 3.",
    )
    parser.add_argument(
        "--start",
        "-s",
        type=int,
        default=1,
        help="Line number to start printing from. Default: 1.",
    )
    parser.add_argument(
        "--encoding",
        default="utf-8",
        help="File encoding to use. Default: utf-8.",
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Show only a short preview instead of printing the whole file.",
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Show file statistics.",
    )

    return parser.parse_args()


def validate_arguments(args: argparse.Namespace) -> None:
    if not args.input_file.is_file():
        raise FileNotFoundError(f"File not found: {args.input_file}")

    if args.lines < 1:
        raise ValueError("--lines must be at least 1.")

    if args.start < 1:
        raise ValueError("--start must be at least 1.")


def calculate_stats(path: Path, content: str) -> FileStats:
    return FileStats(
        path=path,
        size_bytes=path.stat().st_size,
        total_lines=len(content.splitlines()),
        total_words=len(content.split()),
        total_characters=len(content),
    )


def print_stats(stats: FileStats) -> None:
    print("\nFILE STATISTICS")
    print("-" * 40)
    print(f"Path:       {stats.path}")
    print(f"Size:       {stats.size_bytes:,} bytes")
    print(f"Lines:      {stats.total_lines:,}")
    print(f"Words:      {stats.total_words:,}")
    print(f"Characters: {stats.total_characters:,}")


def print_entire_file(file_handle: TextIO) -> None:
    """Print from the current file cursor to the end."""
    print(file_handle.read(), end="")


def rewind(file_handle: TextIO) -> None:
    """Move the file cursor to the first byte."""
    file_handle.seek(0)


def skip_to_line(file_handle: TextIO, target_line: int) -> bool:
    """
    Move the cursor to the requested line.

    Returns False if the file ends before that line.
    """
    for _ in range(target_line - 1):
        if not file_handle.readline():
            return False

    return True


def print_numbered_lines(
    file_handle: TextIO,
    start_line: int,
    number_of_lines: int,
) -> int:
    """
    Print numbered lines with their cursor position.

    Returns the number of lines actually printed.
    """
    printed = 0

    for line_number in range(start_line, start_line + number_of_lines):
        byte_position = file_handle.tell()
        line = file_handle.readline()

        if not line:
            break

        print(f"{line_number:>5} | byte {byte_position:>8} | {line}", end="")
        printed += 1

    return printed


def main() -> int:
    args = get_arguments()

    try:
        validate_arguments(args)

        with args.input_file.open("r", encoding=args.encoding) as current_file:
            full_content = current_file.read()

            if args.stats:
                stats = calculate_stats(args.input_file, full_content)
                print_stats(stats)

            rewind(current_file)

            if args.preview:
                print("\nFILE PREVIEW")
                print("-" * 40)
                preview_lines = print_numbered_lines(
                    current_file,
                    start_line=1,
                    number_of_lines=min(args.lines, 10),
                )

                if preview_lines == 0:
                    print("(The file is empty.)")

                return 0

            print("\nFULL FILE CONTENT")
            print("-" * 40)
            print_entire_file(current_file)

            print("\n\nREWINDING FILE...")
            rewind(current_file)

            print(
                f"\nPRINTING {args.lines} LINE(S), "
                f"STARTING AT LINE {args.start}"
            )
            print("-" * 40)

            if not skip_to_line(current_file, args.start):
                print(f"Line {args.start} does not exist in this file.")
                return 0

            printed = print_numbered_lines(
                current_file,
                start_line=args.start,
                number_of_lines=args.lines,
            )

            if printed < args.lines:
                print("\n(Reached the end of the file.)")

        return 0

    except FileNotFoundError as error:
        print(f"Error: {error}", file=sys.stderr)
    except PermissionError:
        print("Error: Permission denied while reading this file.", file=sys.stderr)
    except UnicodeDecodeError:
        print(
            f"Error: Could not decode file using '{args.encoding}'. "
            "Try --encoding latin-1 or --encoding utf-16.",
            file=sys.stderr,
        )
    except ValueError as error:
        print(f"Error: {error}", file=sys.stderr)
    except OSError as error:
        print(f"System error: {error}", file=sys.stderr)

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
```
