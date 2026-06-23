"""
Advanced Polynomial Sequence Solver
Supports constant, linear, and quadratic sequences.

Examples:
    6 13 22 33
    1, 4, 9, 16
    3/2 3 9/2 6
    0.5 2 4.5 8
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from fractions import Fraction
from typing import List, Optional


@dataclass
class SequenceResult:
    kind: str
    formula: str
    predictions: List[Fraction]
    differences: List[List[Fraction]]
    message: str


def parse_number(value: str) -> Fraction:
    """Parse integers, decimals, and fractions exactly."""
    try:
        return Fraction(value.strip())
    except (ValueError, ZeroDivisionError) as error:
        raise ValueError(f"'{value}' is not a valid number.") from error


def format_number(value: Fraction) -> str:
    """Format a Fraction cleanly."""
    if value.denominator == 1:
        return str(value.numerator)
    return f"{value.numerator}/{value.denominator}"


def format_polynomial(terms: List[tuple[Fraction, str]]) -> str:
    """
    Convert terms like [(2, 'n²'), (-3, 'n'), (1, '')]
    into: 2n² - 3n + 1
    """
    output = []

    for coefficient, variable in terms:
        if coefficient == 0:
            continue

        absolute = abs(coefficient)

        if variable and absolute == 1:
            body = variable
        else:
            body = f"{format_number(absolute)}{variable}"

        if not output:
            output.append(f"-{body}" if coefficient < 0 else body)
        else:
            operator = " - " if coefficient < 0 else " + "
            output.append(f"{operator}{body}")

    return "".join(output) if output else "0"


def build_difference_table(sequence: List[Fraction]) -> List[List[Fraction]]:
    """Return all finite-difference rows."""
    table = [sequence]

    while len(table[-1]) > 1:
        previous = table[-1]
        next_row = [
            previous[index + 1] - previous[index]
            for index in range(len(previous) - 1)
        ]
        table.append(next_row)

    return table


def all_equal(values: List[Fraction]) -> bool:
    """Check whether every value is identical."""
    return bool(values) and all(value == values[0] for value in values)


def evaluate_quadratic(a: Fraction, b: Fraction, c: Fraction, n: int) -> Fraction:
    """Evaluate an² + bn + c."""
    return a * n * n + b * n + c


def solve_sequence(
    sequence: List[Fraction],
    start_index: int = 1,
    prediction_count: int = 3,
) -> SequenceResult:
    """
    Identify constant, linear, or quadratic sequences.

    start_index controls which n-value belongs to the first term.
    Normally, the first term is T1, so start_index defaults to 1.
    """
    if len(sequence) < 2:
        return SequenceResult(
            kind="Unknown",
            formula="",
            predictions=[],
            differences=[sequence],
            message="Enter at least two terms.",
        )

    differences = build_difference_table(sequence)
    first_differences = differences[1]

    # Constant sequence
    if all_equal(sequence):
        c = sequence[0]
        predictions = [c] * prediction_count

        return SequenceResult(
            kind="Constant",
            formula=format_number(c),
            predictions=predictions,
            differences=differences,
            message="Constant sequence detected.",
        )

    # Linear sequence: first differences are constant
    if all_equal(first_differences):
        a = first_differences[0]
        b = sequence[0] - a * start_index

        formula = format_polynomial([
            (a, "n"),
            (b, ""),
        ])

        predictions = [
            a * (start_index + len(sequence) + offset) + b
            for offset in range(prediction_count)
        ]

        return SequenceResult(
            kind="Linear",
            formula=formula,
            predictions=predictions,
            differences=differences,
            message="Linear sequence detected.",
        )

    # Quadratic sequence: second differences are constant
    if len(sequence) >= 4:
        second_differences = differences[2]

        if all_equal(second_differences):
            a = second_differences[0] / 2

            # Difference from T(n) to T(n + 1):
            # a(2n + 1) + b
            b = first_differences[0] - a * (2 * start_index + 1)
            c = sequence[0] - a * start_index * start_index - b * start_index

            formula = format_polynomial([
                (a, "n²"),
                (b, "n"),
                (c, ""),
            ])

            predictions = [
                evaluate_quadratic(
                    a,
                    b,
                    c,
                    start_index + len(sequence) + offset,
                )
                for offset in range(prediction_count)
            ]

            return SequenceResult(
                kind="Quadratic",
                formula=formula,
                predictions=predictions,
                differences=differences,
                message="Quadratic sequence detected.",
            )

    return SequenceResult(
        kind="Unknown",
        formula="",
        predictions=[],
        differences=differences,
        message=(
            "The sequence is not consistently constant, linear, or quadratic. "
            "For reliable quadratic detection, enter at least four terms."
        ),
    )


def print_difference_table(table: List[List[Fraction]]) -> None:
    """Display finite differences in readable rows."""
    labels = ["Terms", "1st differences", "2nd differences", "3rd differences"]

    print("\nDifference table:")
    for index, row in enumerate(table):
        label = labels[index] if index < len(labels) else f"{index}th differences"
        values = "  ".join(format_number(value) for value in row)
        print(f"  {label:<16}: {values}")


def print_result(result: SequenceResult, start_index: int) -> None:
    """Print the analysis result."""
    print(f"\n{result.message}")

    if result.formula:
        print(f"Nth term: Tₙ = {result.formula}")

    if result.predictions:
        print("\nPredicted next terms:")
        first_prediction_index = start_index + len(result.differences[0])

        for offset, value in enumerate(result.predictions):
            term_number = first_prediction_index + offset
            print(f"  T{term_number} = {format_number(value)}")

    print_difference_table(result.differences)


def get_sequence_from_user() -> List[Fraction]:
    """Read terms interactively, accepting spaces or commas."""
    print("Enter sequence terms separated by spaces or commas.")
    print("Examples: 6 13 22 33    |    1, 4, 9, 16    |    3/2 3 9/2 6")

    raw_input = input("> ").replace(",", " ").split()

    if not raw_input:
        raise ValueError("No sequence terms entered.")

    return [parse_number(item) for item in raw_input]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Identify and solve constant, linear, and quadratic sequences."
    )

    parser.add_argument(
        "terms",
        nargs="*",
        help="Sequence terms, such as: 6 13 22 33",
    )

    parser.add_argument(
        "--start-index",
        type=int,
        default=1,
        help="Index for the first supplied term. Default: 1",
    )

    parser.add_argument(
        "--predict",
        type=int,
        default=3,
        help="Number of future terms to predict. Default: 3",
    )

    args = parser.parse_args()

    try:
        if args.predict < 1:
            raise ValueError("--predict must be at least 1.")

        if args.terms:
            sequence = [parse_number(term) for term in args.terms]
        else:
            print("--- Advanced Sequence Solver ---")
            sequence = get_sequence_from_user()

        result = solve_sequence(
            sequence=sequence,
            start_index=args.start_index,
            prediction_count=args.predict,
        )

        print_result(result, args.start_index)

    except ValueError as error:
        print(f"\nInput error: {error}")
    except KeyboardInterrupt:
        print("\n\nSequence solver closed.")


if __name__ == "__main__":
    main()
