#!/usr/bin/env python3
"""
Chicken and Rabbit Puzzle Solver

Classic puzzle:
    A farm contains 35 heads and 94 legs.
    Every chicken has 2 legs.
    Every rabbit has 4 legs.

Find the number of chickens and rabbits.

Original author:
    Anurag Kumar

Modernised version:
    - Uses an O(1) algebraic solution
    - Validates all inputs
    - Supports custom animal names and leg counts
    - Includes a command-line interface
    - Produces a clear explanation
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass


@dataclass(frozen=True)
class Solution:
    """Represents the result of an animal-count puzzle."""

    first_animal: str
    first_count: int
    second_animal: str
    second_count: int
    total_heads: int
    total_legs: int

    def __str__(self) -> str:
        return (
            f"{self.first_animal.title()}: {self.first_count}\n"
            f"{self.second_animal.title()}: {self.second_count}\n"
            f"Total animals: {self.total_heads}\n"
            f"Total legs: {self.total_legs}"
        )


class NoSolutionError(ValueError):
    """Raised when the supplied puzzle has no whole-number solution."""


def solve(
    num_heads: int,
    num_legs: int,
    first_legs: int = 2,
    second_legs: int = 4,
    first_name: str = "chickens",
    second_name: str = "rabbits",
) -> Solution:
    """
    Solve a two-animal heads-and-legs puzzle.

    Equations:
        first_count + second_count = num_heads

        first_legs * first_count
        + second_legs * second_count
        = num_legs

    Args:
        num_heads: Total number of animal heads.
        num_legs: Total number of animal legs.
        first_legs: Legs possessed by each first animal.
        second_legs: Legs possessed by each second animal.
        first_name: Name of the first animal.
        second_name: Name of the second animal.

    Returns:
        A Solution object containing both animal counts.

    Raises:
        TypeError: If numeric arguments are not integers.
        ValueError: If arguments are invalid.
        NoSolutionError: If no non-negative whole-number solution exists.
    """
    numeric_values = {
        "num_heads": num_heads,
        "num_legs": num_legs,
        "first_legs": first_legs,
        "second_legs": second_legs,
    }

    for name, value in numeric_values.items():
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"{name} must be an integer.")

    if num_heads < 0:
        raise ValueError("The number of heads cannot be negative.")

    if num_legs < 0:
        raise ValueError("The number of legs cannot be negative.")

    if first_legs < 0 or second_legs < 0:
        raise ValueError("Leg counts cannot be negative.")

    if first_legs == second_legs:
        raise ValueError(
            "The two animal types must have different leg counts."
        )

    if not first_name.strip() or not second_name.strip():
        raise ValueError("Animal names cannot be empty.")

    leg_difference = second_legs - first_legs

    # Derived from:
    # first_legs * (num_heads - second_count)
    # + second_legs * second_count = num_legs
    numerator = num_legs - first_legs * num_heads

    quotient, remainder = divmod(numerator, leg_difference)

    if remainder != 0:
        raise NoSolutionError(
            "No whole-number solution exists for these values."
        )

    second_count = quotient
    first_count = num_heads - second_count

    if first_count < 0 or second_count < 0:
        raise NoSolutionError(
            "The equations produce a negative animal count."
        )

    # Defensive verification.
    calculated_legs = (
        first_count * first_legs
        + second_count * second_legs
    )

    if first_count + second_count != num_heads:
        raise RuntimeError("Internal head-count verification failed.")

    if calculated_legs != num_legs:
        raise RuntimeError("Internal leg-count verification failed.")

    return Solution(
        first_animal=first_name,
        first_count=first_count,
        second_animal=second_name,
        second_count=second_count,
        total_heads=num_heads,
        total_legs=num_legs,
    )


def explain_solution(
    solution: Solution,
    first_legs: int,
    second_legs: int,
) -> str:
    """Return a human-readable verification of the solution."""
    first_total = solution.first_count * first_legs
    second_total = solution.second_count * second_legs

    return (
        "\nVerification\n"
        "------------\n"
        f"Heads: {solution.first_count} + "
        f"{solution.second_count} = {solution.total_heads}\n"
        f"Legs: ({solution.first_count} × {first_legs}) + "
        f"({solution.second_count} × {second_legs})\n"
        f"      {first_total} + {second_total} = "
        f"{solution.total_legs}"
    )


def create_parser() -> argparse.ArgumentParser:
    """Create and configure the command-line argument parser."""
    parser = argparse.ArgumentParser(
        description="Solve a two-animal heads-and-legs puzzle."
    )

    parser.add_argument(
        "--heads",
        type=int,
        default=35,
        help="Total number of heads. Default: 35",
    )

    parser.add_argument(
        "--legs",
        type=int,
        default=94,
        help="Total number of legs. Default: 94",
    )

    parser.add_argument(
        "--first-name",
        default="chickens",
        help="Name of the first animal. Default: chickens",
    )

    parser.add_argument(
        "--first-legs",
        type=int,
        default=2,
        help="Legs per first animal. Default: 2",
    )

    parser.add_argument(
        "--second-name",
        default="rabbits",
        help="Name of the second animal. Default: rabbits",
    )

    parser.add_argument(
        "--second-legs",
        type=int,
        default=4,
        help="Legs per second animal. Default: 4",
    )

    parser.add_argument(
        "--no-explanation",
        action="store_true",
        help="Hide the calculation verification.",
    )

    return parser


def main() -> int:
    """Run the command-line application."""
    parser = create_parser()
    args = parser.parse_args()

    try:
        solution = solve(
            num_heads=args.heads,
            num_legs=args.legs,
            first_legs=args.first_legs,
            second_legs=args.second_legs,
            first_name=args.first_name,
            second_name=args.second_name,
        )
    except (TypeError, ValueError) as error:
        parser.error(str(error))
        return 2

    print("\nSolution")
    print("--------")
    print(solution)

    if not args.no_explanation:
        print(
            explain_solution(
                solution,
                first_legs=args.first_legs,
                second_legs=args.second_legs,
            )
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
