#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Advanced Text Separator / Hyphen Replacer
-----------------------------------------
Replaces whitespace in text with a chosen separator.

Features:
- Replaces spaces, tabs and other whitespace
- Handles repeated spaces intelligently
- Optional URL/filename-safe slug mode
- Custom separator support
- Unicode normalization
- Optional lowercase conversion
- Optional punctuation removal
- Shows before/after statistics
- Interactive menu
- Clean reusable functions
- No external libraries required
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


@dataclass
class ReplacementOptions:
    """Configuration for text transformation."""

    separator: str = "-"
    collapse_whitespace: bool = True
    lowercase: bool = False
    strip_edges: bool = True
    remove_punctuation: bool = False
    unicode_to_ascii: bool = False


@dataclass
class TextStatistics:
    """Statistics describing a text transformation."""

    original_length: int
    result_length: int
    whitespace_groups: int
    whitespace_characters: int
    words: int
    replacements: int


def normalize_unicode(text: str, ascii_only: bool = False) -> str:
    """
    Normalize Unicode text.

    Example:
        café → cafe

    Only removes accents when ascii_only=True.
    """

    text = unicodedata.normalize("NFKC", text)

    if ascii_only:
        text = unicodedata.normalize("NFKD", text)
        text = text.encode("ascii", "ignore").decode("ascii")

    return text


def remove_punctuation_except_separator(
    text: str,
    separator: str
) -> str:
    """
    Remove punctuation while keeping letters, numbers,
    whitespace and the chosen separator.
    """

    result = []

    for char in text:
        if (
            char.isalnum()
            or char.isspace()
            or char in separator
        ):
            result.append(char)

    return "".join(result)


def replace_whitespace(
    text: str,
    options: ReplacementOptions
) -> tuple[str, TextStatistics]:
    """
    Transform whitespace into the selected separator.

    Returns:
        tuple:
            transformed text
            statistics
    """

    if not options.separator:
        raise ValueError("Separator cannot be empty.")

    original = text

    # Normalize Unicode first
    text = normalize_unicode(
        text,
        ascii_only=options.unicode_to_ascii
    )

    # Optional lowercase conversion
    if options.lowercase:
        text = text.lower()

    # Optional punctuation removal
    if options.remove_punctuation:
        text = remove_punctuation_except_separator(
            text,
            options.separator
        )

    whitespace_groups = len(re.findall(r"\s+", text))
    whitespace_characters = len(re.findall(r"\s", text))

    words = len(re.findall(r"\S+", text))

    if options.collapse_whitespace:

        # Convert one or more whitespace characters
        # into exactly one separator.
        result = re.sub(
            r"\s+",
            lambda _: options.separator,
            text
        )

    else:

        # Every individual whitespace character becomes
        # one separator.
        result = re.sub(
            r"\s",
            lambda _: options.separator,
            text
        )

    if options.collapse_whitespace:

        # If separator already exists next to another one,
        # collapse runs into one separator.
        escaped_separator = re.escape(options.separator)

        result = re.sub(
            rf"(?:{escaped_separator})+",
            options.separator,
            result
        )

    if options.strip_edges:

        result = result.strip(options.separator)

    replacements = whitespace_groups if options.collapse_whitespace \
        else whitespace_characters

    statistics = TextStatistics(
        original_length=len(original),
        result_length=len(result),
        whitespace_groups=whitespace_groups,
        whitespace_characters=whitespace_characters,
        words=words,
        replacements=replacements
    )

    return result, statistics


def create_slug(text: str) -> str:
    """
    Turn text into a URL/filename-friendly slug.

    Example:

        "Hello, This is Café Python!"

    becomes:

        "hello-this-is-cafe-python"
    """

    options = ReplacementOptions(
        separator="-",
        collapse_whitespace=True,
        lowercase=True,
        strip_edges=True,
        remove_punctuation=True,
        unicode_to_ascii=True
    )

    result, _ = replace_whitespace(text, options)

    # Keep only ASCII letters, numbers and hyphens.
    result = re.sub(r"[^a-z0-9-]", "", result)

    # Collapse duplicate hyphens.
    result = re.sub(r"-+", "-", result)

    return result.strip("-")


def display_statistics(stats: TextStatistics) -> None:
    """Pretty-print transformation statistics."""

    print("\n" + "=" * 55)
    print("TEXT STATISTICS")
    print("=" * 55)

    print(f"Original characters : {stats.original_length}")
    print(f"Output characters   : {stats.result_length}")
    print(f"Words detected      : {stats.words}")
    print(f"Whitespace chars    : {stats.whitespace_characters}")
    print(f"Whitespace groups   : {stats.whitespace_groups}")
    print(f"Replacements made   : {stats.replacements}")

    difference = stats.result_length - stats.original_length

    if difference > 0:
        print(f"Length change       : +{difference}")
    else:
        print(f"Length change       : {difference}")

    print("=" * 55)


def ask_yes_no(question: str, default: bool = False) -> bool:
    """Read a yes/no option safely."""

    suffix = "[Y/n]" if default else "[y/N]"

    while True:

        answer = input(f"{question} {suffix}: ").strip().lower()

        if answer == "":
            return default

        if answer in {"y", "yes"}:
            return True

        if answer in {"n", "no"}:
            return False

        print("Please enter y or n.")


def advanced_mode(text: str) -> None:
    """Run the customizable transformer."""

    print("\nADVANCED MODE")
    print("-" * 55)

    separator = input(
        "Separator character/string [default '-']: "
    )

    if not separator:
        separator = "-"

    options = ReplacementOptions(
        separator=separator,
        collapse_whitespace=ask_yes_no(
            "Collapse multiple spaces into one separator?",
            True
        ),
        lowercase=ask_yes_no(
            "Convert text to lowercase?",
            False
        ),
        strip_edges=ask_yes_no(
            "Remove separators from the beginning/end?",
            True
        ),
        remove_punctuation=ask_yes_no(
            "Remove punctuation?",
            False
        ),
        unicode_to_ascii=ask_yes_no(
            "Convert accented Unicode characters to ASCII?",
            False
        )
    )

    result, statistics = replace_whitespace(text, options)

    print("\nRESULT")
    print("=" * 55)
    print(result)
    print("=" * 55)

    display_statistics(statistics)


def standard_mode(text: str) -> None:
    """Standard smart hyphen replacement."""

    options = ReplacementOptions(
        separator="-",
        collapse_whitespace=True,
        lowercase=False,
        strip_edges=True,
        remove_punctuation=False,
        unicode_to_ascii=False
    )

    result, statistics = replace_whitespace(text, options)

    print("\nChanged text:")
    print(result)

    display_statistics(statistics)


def slug_mode(text: str) -> None:
    """Create a URL-safe slug."""

    result = create_slug(text)

    print("\nURL / filename-friendly slug:")
    print(result)


def main() -> None:
    """Application entry point."""

    print(
        r"""
╔═══════════════════════════════════════════════════════╗
║            ADVANCED TEXT TRANSFORMER                 ║
║                                                       ║
║   Replace whitespace with clean separators           ║
╚═══════════════════════════════════════════════════════╝
"""
    )

    while True:

        print("\nChoose a mode:")
        print("1. Smart hyphen replacement")
        print("2. Advanced customizable replacement")
        print("3. URL / filename slug generator")
        print("4. Exit")

        choice = input("\nSelection [1-4]: ").strip()

        if choice == "4":
            print("\nGoodbye.")
            break

        if choice not in {"1", "2", "3"}:
            print("Invalid choice. Please select 1-4.")
            continue

        print(
            "\nEnter your text below.\n"
            "Press ENTER when finished:"
        )

        text = input("> ")

        if not text:
            print("No text was entered.")
            continue

        try:

            if choice == "1":
                standard_mode(text)

            elif choice == "2":
                advanced_mode(text)

            elif choice == "3":
                slug_mode(text)

        except ValueError as error:
            print(f"\nError: {error}")

        print()


if __name__ == "__main__":
    main()
