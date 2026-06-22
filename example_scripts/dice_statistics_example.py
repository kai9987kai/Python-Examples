#!/usr/bin/env python3
"""Roll dice many times and summarize the results."""

from collections import Counter
from random import Random


def roll_dice(sides=6, rolls=1000, seed=42):
    """Return a Counter containing simulated dice-roll totals."""
    random = Random(seed)
    return Counter(random.randint(1, sides) for _ in range(rolls))


def print_summary(counts, rolls):
    """Print roll counts and percentages."""
    for side in sorted(counts):
        percentage = counts[side] / rolls * 100
        print(f"{side}: {counts[side]:4d} rolls ({percentage:5.2f}%)")


def main():
    rolls = 1000
    counts = roll_dice(rolls=rolls)
    print_summary(counts, rolls)


if __name__ == "__main__":
    main()
