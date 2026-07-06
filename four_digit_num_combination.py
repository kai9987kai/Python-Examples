#!/usr/bin/env python3
"""
Generate every zero-padded numeric code of a chosen length.

Examples:
    python codes.py
    python codes.py --digits 6
    python codes.py --digits 4 --output codes.txt
"""

from argparse import ArgumentParser
from pathlib import Path
from typing import Iterator


def generate_numeric_codes(digits: int) -> Iterator[str]:
    """Yield every numeric code with exactly `digits` characters.

    Example for digits=3:
        000, 001, 002, ... 999
    """
    if digits < 1:
        raise ValueError("digits must be at least 1.")

    limit = 10 ** digits
    for number in range(limit):
        yield f"{number:0{digits}d}"


def print_codes(digits: int) -> None:
    """Print every possible code to the terminal."""
    for code in generate_numeric_codes(digits):
        print(code)


def save_codes(digits: int, output_file: str) -> None:
    """Save every possible code to a text file."""
    path = Path(output_file)

    with path.open("w", encoding="utf-8") as file:
        for code in generate_numeric_codes(digits):
            file.write(f"{code}\n")

    print(f"Saved {10 ** digits:,} codes to: {path.resolve()}")


def main() -> None:
    parser = ArgumentParser(description="Generate zero-padded numeric codes.")
    parser.add_argument(
        "--digits",
        type=int,
        default=4,
        help="Number of digits per code. Default: 4",
    )
    parser.add_argument(
        "--output",
        type=str,
        help="Optional file to save codes into instead of printing them.",
    )

    args = parser.parse_args()

    try:
        if args.output:
            save_codes(args.digits, args.output)
        else:
            print_codes(args.digits)
    except ValueError as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
