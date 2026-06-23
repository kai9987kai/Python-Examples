"""
Advanced Palindrome Checker
Checks phrases while ignoring spaces, punctuation, case, and accents.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


SAMPLE_PHRASE = "A man, a plan, a cat, a ham, a yak, a yam, a hat, a canal-Panama!"


@dataclass
class PalindromeResult:
    original: str
    normalized: str
    is_palindrome: bool
    mismatch: str | None = None


def normalize_phrase(text: str) -> str:
    """
    Convert text into a comparison-friendly form.

    Examples:
        "Madam, I'm Adam!" -> "madamimadam"
        "Àbba"             -> "abba"
    """
    decomposed = unicodedata.normalize("NFKD", text)
    without_accents = "".join(
        character
        for character in decomposed
        if not unicodedata.combining(character)
    )

    return re.sub(r"[^a-z0-9]", "", without_accents.casefold())


def find_mismatch(text: str) -> str | None:
    """Return useful information about the first non-matching pair."""
    left = 0
    right = len(text) - 1

    while left < right:
        if text[left] != text[right]:
            return (
                f"Mismatch found: '{text[left]}' at position {left + 1} "
                f"does not match '{text[right]}' at position {right + 1}."
            )

        left += 1
        right -= 1

    return None


def check_palindrome(phrase: str) -> PalindromeResult:
    """Analyse a phrase and return its palindrome result."""
    normalized = normalize_phrase(phrase)

    if not normalized:
        return PalindromeResult(
            original=phrase,
            normalized=normalized,
            is_palindrome=False,
            mismatch="Please enter at least one letter or number.",
        )

    palindrome = normalized == normalized[::-1]

    return PalindromeResult(
        original=phrase,
        normalized=normalized,
        is_palindrome=palindrome,
        mismatch=None if palindrome else find_mismatch(normalized),
    )


def display_result(result: PalindromeResult) -> None:
    """Print a clear result summary."""
    print("\n" + "=" * 52)
    print(f"Original phrase : {result.original}")
    print(f"Normalised text : {result.normalized}")

    if result.is_palindrome:
        print("\n✅ Palindrome detected!")
        print("This phrase reads the same forwards and backwards.")
    else:
        print("\n❌ Not a palindrome.")
        if result.mismatch:
            print(result.mismatch)

    print("=" * 52)


def get_phrase() -> str:
    """Ask for a phrase, using the sample when Enter is pressed."""
    print("\n--- Advanced Palindrome Checker ---")
    print("Press ENTER to test the built-in sample phrase.")
    user_input = input("\nEnter a phrase: ").strip()

    if not user_input:
        print(f"\nUsing sample phrase:\n{SAMPLE_PHRASE}")
        return SAMPLE_PHRASE

    return user_input


def main() -> None:
    """Run the application with repeat checking."""
    try:
        while True:
            phrase = get_phrase()
            result = check_palindrome(phrase)
            display_result(result)

            again = input("\nCheck another phrase? [y/n]: ").strip().casefold()

            if again not in {"y", "yes"}:
                print("\nThanks for using the Palindrome Checker.")
                break

    except KeyboardInterrupt:
        print("\n\nProgram closed safely.")
    except EOFError:
        print("\n\nNo input received. Program closed.")


if __name__ == "__main__":
    main()
