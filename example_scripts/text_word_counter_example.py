#!/usr/bin/env python3
"""Count words in sample text and show the most common words."""

from collections import Counter
import re


SAMPLE_TEXT = """
Python examples are useful because examples turn ideas into practice.
Small Python scripts can teach files, strings, loops, functions, and testing.
"""


def count_words(text):
    """Return lowercase word frequencies from a string."""
    words = re.findall(r"[a-zA-Z']+", text.lower())
    return Counter(words)


def main():
    counts = count_words(SAMPLE_TEXT)
    for word, total in counts.most_common(5):
        print(f"{word}: {total}")


if __name__ == "__main__":
    main()
