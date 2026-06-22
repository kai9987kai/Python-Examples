#!/usr/bin/env python3
"""
Character Frequency Analyzer

Counts every character in a text file and displays a readable report.

Examples:
    python char_counter.py myfile.txt
    python char_counter.py myfile.txt --ignore-case
    python char_counter.py myfile.txt --ignore-space
    python char_counter.py myfile.txt --top 10
"""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path


def read_text_file(file_path: Path) -> str:
    """Read a UTF-8 text file safely."""
    try:
        return file_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise FileNotFoundError(f"File not found: {file_path}")
    except PermissionError:
        raise PermissionError(f"Permission denied: {file_path}")
    except UnicodeDecodeError:
        raise UnicodeDecodeError(
            "utf-8",
            b"",
            0,
            1,
            "The file is not valid UTF-8 text."
        )


def clean_text(text: str, ignore_case: bool, ignore_space: bool) -> str:
    """Apply user-selected text cleanup rules."""
    if ignore_case:
        text = text.upper()

    if ignore_space:
        text = "".join(char for char in text if not char.isspace())

    return text


def display_character(char: str) -> str:
    """Make invisible characters readable in the report."""
    special_characters = {
        " ": "[SPACE]",
        "\n": "[NEWLINE]",
        "\t": "[TAB]",
        "\r": "[CARRIAGE RETURN]",
    }

    return special_characters.get(char, repr(char))


def print_report(counter: Counter[str], total_characters: int, top: int | None) -> None:
    """Print counts sorted from most common to least common."""
    print("\n" + "=" * 55)
    print("CHARACTER FREQUENCY REPORT")
    print("=" * 55)

    unique_characters = len(counter)

    print(f"Total characters:  {total_characters}")
    print(f"Unique characters: {unique_characters}")
    print("-" * 55)

    sorted_items = counter.most_common(top)

    for character, amount in sorted_items:
        percentage = (amount / total_characters * 100) if total_characters else 0
        label = display_character(character)

        print(f"{label:<22} {amount:>8}  ({percentage:>6.2f}%)")

    if top is not None and len(counter) > top:
        print("-" * 55)
        print(f"Showing top {top} most common characters.")

    print("=" * 55)


def get_interactive_file_path() -> Path:
    """Keep asking until a valid file path is supplied."""
    while True:
        user_input = input("File name or path: ").strip().strip('"')

        if not user_input:
            print("Please enter a file name.")
            continue

        file_path = Path(user_input)

        if file_path.is_file():
            return file_path

        print(f"Could not find a valid file: {file_path}")


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Count the frequency of every character in a text file."
    )

    parser.add_argument(
        "file",
        nargs="?",
        help="Text file to analyse"
    )

    parser.add_argument(
        "--ignore-case",
        action="store_true",
        help="Treat uppercase and lowercase characters as the same"
    )

    parser.add_argument(
        "--ignore-space",
        action="store_true",
        help="Ignore spaces, tabs, and line breaks"
    )

    parser.add_argument(
        "--top",
        type=int,
        default=None,
        help="Only show the top N most common characters"
    )

    return parser.parse_args()


def main() -> None:
    args = parse_arguments()

    if args.top is not None and args.top <= 0:
        print("Error: --top must be greater than 0.")
        return

    file_path = Path(args.file) if args.file else get_interactive_file_path()

    try:
        text = read_text_file(file_path)
    except (FileNotFoundError, PermissionError, UnicodeDecodeError) as error:
        print(f"\nError: {error}")
        return

    cleaned_text = clean_text(
        text,
        ignore_case=args.ignore_case,
        ignore_space=args.ignore_space
    )

    character_counts = Counter(cleaned_text)

    print_report(
        counter=character_counts,
        total_characters=len(cleaned_text),
        top=args.top
    )


if __name__ == "__main__":
    main()
