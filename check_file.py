#!/usr/bin/env python3
"""
check_file.py

Check whether one or more files exist and can be read, then display their contents.

Examples:
    python check_file.py notes.txt report.txt
    python check_file.py --line-numbers file.txt
    python check_file.py --max-chars 5000 file.txt
    python check_file.py --full large_file.txt
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


SEPARATOR = "#" * 80


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check that files exist and are readable, then print their contents."
    )

    parser.add_argument(
        "files",
        nargs="+",
        type=Path,
        help="One or more files to check.",
    )

    parser.add_argument(
        "--encoding",
        default="utf-8",
        help="Text encoding to use when reading files. Default: utf-8",
    )

    parser.add_argument(
        "--max-chars",
        type=int,
        default=20_000,
        help="Maximum characters shown per file. Default: 20000",
    )

    parser.add_argument(
        "--full",
        action="store_true",
        help="Show the complete file, even if it is very large.",
    )

    parser.add_argument(
        "--line-numbers",
        action="store_true",
        help="Display line numbers beside file contents.",
    )

    return parser


def format_with_line_numbers(content: str) -> str:
    lines = content.splitlines()

    if not lines:
        return "(File is empty)"

    width = len(str(len(lines)))
    return "\n".join(
        f"{number:>{width}} | {line}"
        for number, line in enumerate(lines, start=1)
    )


def read_and_display_file(
    path: Path,
    encoding: str,
    max_chars: int,
    show_full_file: bool,
    line_numbers: bool,
) -> bool:
    """Read and display a file. Returns True when successful."""

    if not path.exists():
        print(f"[-] {path}: file does not exist.")
        return False

    if not path.is_file():
        print(f"[-] {path}: not a regular file.")
        return False

    try:
        with path.open("r", encoding=encoding, errors="replace") as file:
            limit = -1 if show_full_file else max_chars + 1
            content = file.read(limit)

    except PermissionError:
        print(f"[-] {path}: access denied.")
        return False
    except OSError as error:
        print(f"[-] {path}: could not be read ({error}).")
        return False

    truncated = not show_full_file and len(content) > max_chars

    if truncated:
        content = content[:max_chars]

    print(f"[+] Reading from: {path.resolve()}")
    print(f"    Encoding: {encoding}")

    if line_numbers:
        print(format_with_line_numbers(content))
    else:
        print(content if content else "(File is empty)")

    if truncated:
        print(
            f"\n[!] Output truncated after {max_chars:,} characters. "
            "Use --full to show everything."
        )

    print(f"\n{SEPARATOR}\n")
    return True


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.max_chars < 1:
        parser.error("--max-chars must be at least 1.")

    failures = 0

    for file_path in args.files:
        success = read_and_display_file(
            path=file_path,
            encoding=args.encoding,
            max_chars=args.max_chars,
            show_full_file=args.full,
            line_numbers=args.line_numbers,
        )

        if not success:
            failures += 1

    if failures:
        print(f"[!] Finished with {failures} file error(s).")
        return 1

    print("[+] All files were read successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
