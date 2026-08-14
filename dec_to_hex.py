#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Decimal / Integer Base Converter
Version: 3.0

Features
--------
• Decimal -> hexadecimal
• Decimal -> binary
• Decimal -> octal
• Upper/lowercase hexadecimal
• Optional 0x / 0b / 0o prefixes
• Configurable zero-padding
• Thousands-separated decimal output
• Character/Unicode representation where valid
• Bit length
• Byte-length estimation
• Signed integer support
• Input validation
• Underscores and commas accepted
• Repeated interactive conversions
• Command-line argument support

Examples
--------
Interactive:
    python converter.py

Direct:
    python converter.py 255
    python converter.py 65535 --uppercase
    python converter.py 255 --width 8
    python converter.py 123456789 --no-prefix
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass


# =============================================================================
# DATA MODEL
# =============================================================================

@dataclass(frozen=True, slots=True)
class NumberInfo:
    """Represent an integer and its common base conversions."""

    value: int
    decimal: str
    hexadecimal: str
    binary: str
    octal: str
    bit_length: int
    byte_length: int
    character: str | None


# =============================================================================
# INPUT PARSING
# =============================================================================

def parse_integer(text: str) -> int:
    """
    Convert user input into an integer.

    Accepted examples:
        255
        -255
        +255
        1,000,000
        1_000_000

    Leading/trailing whitespace is ignored.
    """

    cleaned = (
        text.strip()
        .replace(",", "")
        .replace("_", "")
    )

    if not cleaned:
        raise ValueError("No number was entered.")

    try:
        return int(cleaned, 10)

    except ValueError as exc:
        raise ValueError(
            f"{text!r} is not a valid decimal integer."
        ) from exc


# =============================================================================
# FORMATTING
# =============================================================================

def format_base_number(
    value: int,
    base: int,
    *,
    uppercase: bool = False,
    prefix: bool = True,
    width: int = 0,
) -> str:
    """
    Format an integer in binary, octal or hexadecimal.

    Width applies to the digits rather than the prefix.

    Example:
        value=255, base=16, width=8

        -> 0x000000ff
    """

    if base not in (2, 8, 16):
        raise ValueError(
            "Base must be 2, 8 or 16."
        )

    negative = value < 0
    magnitude = abs(value)

    format_codes = {
        2: "b",
        8: "o",
        16: "X" if uppercase else "x",
    }

    prefixes = {
        2: "0b",
        8: "0o",
        16: "0X" if uppercase else "0x",
    }

    digits = format(
        magnitude,
        format_codes[base],
    )

    if width > 0:
        digits = digits.zfill(width)

    result = (
        prefixes[base] + digits
        if prefix
        else digits
    )

    if negative:
        result = "-" + result

    return result


# =============================================================================
# CHARACTER REPRESENTATION
# =============================================================================

def get_character(value: int) -> str | None:
    """
    Return the corresponding Unicode character where possible.

    Invalid Unicode code points and surrogate values are rejected.
    """

    if not 0 <= value <= 0x10FFFF:
        return None

    # UTF-16 surrogate range is not valid Unicode scalar data.
    if 0xD800 <= value <= 0xDFFF:
        return None

    try:
        character = chr(value)

    except ValueError:
        return None

    if character.isprintable():
        return character

    return None


# =============================================================================
# CONVERSION
# =============================================================================

def analyse_number(
    value: int,
    *,
    uppercase: bool = False,
    prefix: bool = True,
    width: int = 0,
) -> NumberInfo:
    """
    Generate representations and metadata for an integer.
    """

    magnitude = abs(value)

    # Python returns 0 for 0.bit_length().
    # For display purposes, zero still requires one binary digit.
    bits = max(1, magnitude.bit_length())

    bytes_required = max(
        1,
        (bits + 7) // 8,
    )

    return NumberInfo(
        value=value,

        decimal=f"{value:,}",

        hexadecimal=format_base_number(
            value,
            16,
            uppercase=uppercase,
            prefix=prefix,
            width=width,
        ),

        binary=format_base_number(
            value,
            2,
            prefix=prefix,
        ),

        octal=format_base_number(
            value,
            8,
            prefix=prefix,
        ),

        bit_length=bits,

        byte_length=bytes_required,

        character=get_character(value),
    )


# =============================================================================
# HEX BREAKDOWN
# =============================================================================

def hexadecimal_breakdown(value: int) -> list[tuple[int, str, int, int]]:
    """
    Explain each hexadecimal digit by positional value.

    Example:
        0x1AF

        1 × 16² = 256
        A × 16¹ = 160
        F × 16⁰ = 15
    """

    magnitude = abs(value)

    digits = format(magnitude, "X")

    results: list[tuple[int, str, int, int]] = []

    for index, digit in enumerate(digits):

        exponent = (
            len(digits) -
            index -
            1
        )

        digit_value = int(
            digit,
            16,
        )

        contribution = (
            digit_value *
            (16 ** exponent)
        )

        results.append(
            (
                digit_value,
                digit,
                exponent,
                contribution,
            )
        )

    return results


# =============================================================================
# DISPLAY
# =============================================================================

def print_number_info(
    info: NumberInfo,
    *,
    show_breakdown: bool = False,
) -> None:
    """
    Print a formatted conversion report.
    """

    print()
    print("=" * 72)
    print(" INTEGER BASE CONVERSION")
    print("=" * 72)

    print(
        f"{'Decimal':<18}: {info.decimal}"
    )

    print(
        f"{'Hexadecimal':<18}: {info.hexadecimal}"
    )

    print(
        f"{'Binary':<18}: {info.binary}"
    )

    print(
        f"{'Octal':<18}: {info.octal}"
    )

    print("-" * 72)

    print(
        f"{'Bit length':<18}: {info.bit_length}"
    )

    print(
        f"{'Minimum bytes':<18}: {info.byte_length}"
    )

    if info.character is not None:

        print(
            f"{'Unicode character':<18}: "
            f"{info.character!r}"
        )

        print(
            f"{'Unicode code point':<18}: "
            f"U+{info.value:04X}"
        )

    if show_breakdown:

        print()
        print("HEXADECIMAL POSITIONAL BREAKDOWN")
        print("-" * 72)

        sign = "-" if info.value < 0 else ""

        for (
            digit_value,
            digit,
            exponent,
            contribution,
        ) in hexadecimal_breakdown(info.value):

            print(
                f"{digit} × 16^{exponent:<2} "
                f"= {digit_value} × {16 ** exponent:,} "
                f"= {contribution:,}"
            )

        if info.value < 0:
            print(
                "\nNegative sign applies to the complete magnitude."
            )

    print("=" * 72)


# =============================================================================
# INTERACTIVE MODE
# =============================================================================

def interactive_mode(
    *,
    uppercase: bool,
    prefix: bool,
    width: int,
    show_breakdown: bool,
) -> int:
    """
    Continuously accept decimal values until the user exits.
    """

    print(
        """
╔══════════════════════════════════════════════════════════════════════╗
║                 ADVANCED DECIMAL CONVERTER                         ║
╠══════════════════════════════════════════════════════════════════════╣
║ Enter a decimal integer to convert it.                              ║
║                                                                    ║
║ Examples:                                                          ║
║   255                                                              ║
║   65535                                                            ║
║   -42                                                              ║
║   1,000,000                                                        ║
║                                                                    ║
║ Enter q, quit or exit to finish.                                   ║
╚══════════════════════════════════════════════════════════════════════╝
"""
    )

    while True:

        try:
            raw_value = input(
                "\nDecimal number > "
            ).strip()

        except EOFError:
            print()
            return 0

        except KeyboardInterrupt:
            print(
                "\nConversion cancelled."
            )
            return 130

        if raw_value.lower() in {
            "q",
            "quit",
            "exit",
        }:
            print(
                "Converter closed."
            )
            return 0

        try:
            value = parse_integer(
                raw_value
            )

            info = analyse_number(
                value,
                uppercase=uppercase,
                prefix=prefix,
                width=width,
            )

            print_number_info(
                info,
                show_breakdown=show_breakdown,
            )

        except ValueError as exc:

            print(
                f"ERROR: {exc}",
                file=sys.stderr,
            )


# =============================================================================
# CLI
# =============================================================================

def parse_arguments() -> argparse.Namespace:

    parser = argparse.ArgumentParser(
        description=(
            "Convert decimal integers into hexadecimal, "
            "binary and octal representations."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument(
        "number",
        nargs="?",
        help=(
            "Decimal integer. "
            "Interactive mode starts when omitted."
        ),
    )

    parser.add_argument(
        "-u",
        "--uppercase",
        action="store_true",
        help="Use uppercase hexadecimal digits.",
    )

    parser.add_argument(
        "--no-prefix",
        action="store_true",
        help=(
            "Remove 0x, 0b and 0o prefixes."
        ),
    )

    parser.add_argument(
        "-w",
        "--width",
        type=int,
        default=0,
        help=(
            "Minimum hexadecimal digit width "
            "using zero padding."
        ),
    )

    parser.add_argument(
        "--breakdown",
        action="store_true",
        help=(
            "Explain hexadecimal positional notation."
        ),
    )

    args = parser.parse_args()

    if args.width < 0:

        parser.error(
            "--width cannot be negative."
        )

    return args


# =============================================================================
# MAIN
# =============================================================================

def main() -> int:

    args = parse_arguments()

    prefix = not args.no_prefix

    if args.number is None:

        return interactive_mode(
            uppercase=args.uppercase,
            prefix=prefix,
            width=args.width,
            show_breakdown=args.breakdown,
        )

    try:

        value = parse_integer(
            args.number
        )

        information = analyse_number(
            value,
            uppercase=args.uppercase,
            prefix=prefix,
            width=args.width,
        )

        print_number_info(
            information,
            show_breakdown=args.breakdown,
        )

        return 0

    except ValueError as exc:

        print(
            f"ERROR: {exc}",
            file=sys.stderr,
        )

        return 2


# =============================================================================
# ENTRY POINT
# =============================================================================

if __name__ == "__main__":

    sys.exit(
        main()
    )
