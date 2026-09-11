#!/usr/bin/env python3
"""
Advanced Spiral Matrix Generator
================================

An improved and extensible version of the original spiral-matrix program.

Features
--------
- Square matrices
- Rectangular matrices
- Clockwise spirals
- Counter-clockwise spirals
- Start from any of four corners
- Custom starting values
- Custom positive or negative increments
- Automatically aligned terminal output
- Optional ASCII table borders
- Matrix statistics
- Export to:
    * TXT
    * CSV
    * JSON
- Interactive mode
- Command-line mode
- Input validation
- Built-in regression/self-tests
- No external libraries required

Examples
--------

Interactive:

    python spiral_matrix.py

5 x 5:

    python spiral_matrix.py 5

4 x 7:

    python spiral_matrix.py 4 7

Counter-clockwise:

    python spiral_matrix.py 5 --direction counterclockwise

Start from bottom-right:

    python spiral_matrix.py 5 --corner bottom-right

Custom number sequence:

    python spiral_matrix.py 5 --start 100 --step 10

Reverse sequence:

    python spiral_matrix.py 5 --start 100 --step -1

ASCII borders:

    python spiral_matrix.py 5 --border

Statistics:

    python spiral_matrix.py 10 --stats

Export:

    python spiral_matrix.py 10 -o spiral.csv
    python spiral_matrix.py 10 -o spiral.json
    python spiral_matrix.py 10 -o spiral.txt

Run built-in tests:

    python spiral_matrix.py --self-test
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import unittest

from pathlib import Path
from typing import Sequence


# =====================================================================
# Type aliases
# =====================================================================

Corner = str
Direction = str
Matrix = list[list[int]]


# =====================================================================
# Constants
# =====================================================================

VALID_CORNERS = (
    "top-left",
    "top-right",
    "bottom-right",
    "bottom-left",
)

VALID_DIRECTIONS = (
    "clockwise",
    "counterclockwise",
)


# =====================================================================
# Validation
# =====================================================================

def _require_positive_int(value: int, name: str) -> None:
    """
    Require a positive integer.

    bool is explicitly rejected because:

        isinstance(True, int)

    evaluates to True in Python.
    """

    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value <= 0
    ):
        raise ValueError(
            f"{name} must be a positive integer; "
            f"received {value!r}"
        )


def _require_int(value: int, name: str) -> None:
    """
    Require a genuine integer.
    """

    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(
            f"{name} must be an integer; "
            f"received {value!r}"
        )


# =====================================================================
# Input normalization
# =====================================================================

def _normalise_corner(corner: str) -> Corner:
    """
    Normalize different ways of specifying a corner.

    Supported examples:

        top-left
        top_left
        top left
        tl

        top-right
        tr

        bottom-left
        bl

        bottom-right
        br
    """

    if not isinstance(corner, str):
        raise TypeError("corner must be a string")

    key = (
        corner
        .strip()
        .lower()
        .replace("_", "-")
        .replace(" ", "-")
    )

    aliases = {
        "tl": "top-left",
        "tr": "top-right",
        "br": "bottom-right",
        "bl": "bottom-left",
    }

    key = aliases.get(key, key)

    if key not in VALID_CORNERS:
        raise ValueError(
            "corner must be one of: "
            + ", ".join(VALID_CORNERS)
            + f"; received {corner!r}"
        )

    return key


def _normalise_direction(direction: str) -> Direction:
    """
    Normalize direction names.

    Accepted aliases include:

        clockwise
        cw

        counterclockwise
        counter-clockwise
        anticlockwise
        anti-clockwise
        ccw
    """

    if not isinstance(direction, str):
        raise TypeError("direction must be a string")

    key = (
        direction
        .strip()
        .lower()
        .replace("_", "-")
        .replace(" ", "-")
    )

    aliases = {
        "cw": "clockwise",
        "clock-wise": "clockwise",

        "ccw": "counterclockwise",

        "counter-clockwise": "counterclockwise",

        "anti-clockwise": "counterclockwise",
        "anticlockwise": "counterclockwise",
    }

    key = aliases.get(key, key)

    if key not in VALID_DIRECTIONS:
        raise ValueError(
            "direction must be "
            "'clockwise' or 'counterclockwise'; "
            f"received {direction!r}"
        )

    return key


# =====================================================================
# Spiral generation engine
# =====================================================================

def generate_spiral_matrix(
    rows: int,
    columns: int | None = None,
    *,
    start: int = 1,
    step: int = 1,
    corner: str = "top-left",
    direction: str = "clockwise",
) -> Matrix:
    """
    Generate a spiral matrix.

    Parameters
    ----------
    rows:
        Number of rows.

    columns:
        Number of columns.

        If omitted:

            columns = rows

        resulting in a square matrix.

    start:
        First number placed into the matrix.

    step:
        Amount added after every cell.

        Examples:

            step = 1
            1, 2, 3, 4 ...

            step = 5
            1, 6, 11, 16 ...

            step = -1
            10, 9, 8, 7 ...

        Zero is not allowed because every position would receive
        the same value.

    corner:
        Starting corner:

            top-left
            top-right
            bottom-right
            bottom-left

    direction:
        Spiral rotation:

            clockwise
            counterclockwise

    Returns
    -------
    list[list[int]]

        Generated matrix.

    Complexity
    ----------
    Let:

        N = rows * columns

    Time:

        O(N)

    Matrix storage:

        O(N)

    The generator touches every matrix position exactly once.
    """

    # ---------------------------------------------------------------
    # Square-matrix convenience
    # ---------------------------------------------------------------

    if columns is None:
        columns = rows

    # ---------------------------------------------------------------
    # Validate input
    # ---------------------------------------------------------------

    _require_positive_int(rows, "rows")
    _require_positive_int(columns, "columns")

    _require_int(start, "start")
    _require_int(step, "step")

    if step == 0:
        raise ValueError(
            "step must be non-zero"
        )

    corner = _normalise_corner(corner)
    direction = _normalise_direction(direction)

    # ---------------------------------------------------------------
    # Allocate output matrix
    # ---------------------------------------------------------------

    matrix: Matrix = [
        [0] * columns
        for _ in range(rows)
    ]

    # Separate visited matrix allows the generated values themselves
    # to contain 0, negatives, or repeated-looking numeric patterns
    # without being confused with unfilled cells.

    visited = [
        [False] * columns
        for _ in range(rows)
    ]

    # ---------------------------------------------------------------
    # Starting coordinates
    # ---------------------------------------------------------------

    start_positions: dict[
        Corner,
        tuple[int, int]
    ] = {

        "top-left":
            (0, 0),

        "top-right":
            (0, columns - 1),

        "bottom-right":
            (rows - 1, columns - 1),

        "bottom-left":
            (rows - 1, 0),
    }

    # ---------------------------------------------------------------
    # Initial clockwise direction vectors
    #
    # (delta row, delta column)
    #
    # right = (0, 1)
    # down  = (1, 0)
    # left  = (0, -1)
    # up    = (-1, 0)
    # ---------------------------------------------------------------

    clockwise_initial: dict[
        Corner,
        tuple[int, int]
    ] = {

        "top-left":
            (0, 1),

        "top-right":
            (1, 0),

        "bottom-right":
            (0, -1),

        "bottom-left":
            (-1, 0),
    }

    # ---------------------------------------------------------------
    # Initial counter-clockwise vectors
    # ---------------------------------------------------------------

    counterclockwise_initial: dict[
        Corner,
        tuple[int, int]
    ] = {

        "top-left":
            (1, 0),

        "bottom-left":
            (0, 1),

        "bottom-right":
            (-1, 0),

        "top-right":
            (0, -1),
    }

    # ---------------------------------------------------------------
    # Select starting position
    # ---------------------------------------------------------------

    row, col = start_positions[corner]

    # ---------------------------------------------------------------
    # Select initial direction
    # ---------------------------------------------------------------

    if direction == "clockwise":

        delta_row, delta_col = (
            clockwise_initial[corner]
        )

    else:

        delta_row, delta_col = (
            counterclockwise_initial[corner]
        )

    # ---------------------------------------------------------------
    # Generation
    # ---------------------------------------------------------------

    value = start

    cell_count = (
        rows * columns
    )

    for index in range(cell_count):

        # Write current value.

        matrix[row][col] = value

        visited[row][col] = True

        # Prepare the value for the next cell.

        value += step

        # Last cell does not require movement.

        if index == cell_count - 1:
            break

        # Predict next location.

        next_row = (
            row + delta_row
        )

        next_col = (
            col + delta_col
        )

        # -----------------------------------------------------------
        # Determine whether movement is blocked.
        # -----------------------------------------------------------

        blocked = (
            next_row < 0
            or next_row >= rows

            or next_col < 0
            or next_col >= columns

            or visited[next_row][next_col]
        )

        # -----------------------------------------------------------
        # Rotate 90 degrees if required.
        # -----------------------------------------------------------

        if blocked:

            if direction == "clockwise":

                # Clockwise vector rotation:
                #
                # (dr, dc)
                #
                # becomes
                #
                # (dc, -dr)

                delta_row, delta_col = (
                    delta_col,
                    -delta_row,
                )

            else:

                # Counter-clockwise vector rotation:
                #
                # (dr, dc)
                #
                # becomes
                #
                # (-dc, dr)

                delta_row, delta_col = (
                    -delta_col,
                    delta_row,
                )

            # Recalculate location after turning.

            next_row = (
                row + delta_row
            )

            next_col = (
                col + delta_col
            )

        # Move.

        row = next_row
        col = next_col

    return matrix


# =====================================================================
# Matrix formatting
# =====================================================================

def format_matrix(
    matrix: Sequence[Sequence[int]],
    *,
    border: bool = False,
) -> str:
    """
    Convert a matrix into aligned text.

    Example:

         1   2   3   4
        12  13  14   5
        11  16  15   6
        10   9   8   7
    """

    if not matrix:
        return ""

    if not matrix[0]:
        return ""

    column_count = len(matrix[0])

    # Ensure rectangular structure.

    if any(
        len(row) != column_count
        for row in matrix
    ):
        raise ValueError(
            "matrix must be rectangular"
        )

    # Determine required width from largest textual value.

    width = max(
        len(str(value))
        for row in matrix
        for value in row
    )

    # ---------------------------------------------------------------
    # Normal aligned output
    # ---------------------------------------------------------------

    if not border:

        return "\n".join(

            "  ".join(
                f"{value:>{width}}"
                for value in row
            )

            for row in matrix
        )

    # ---------------------------------------------------------------
    # Bordered table output
    # ---------------------------------------------------------------

    horizontal = (

        "+"

        + "+".join(

            "-" * (width + 2)

            for _ in range(column_count)
        )

        + "+"
    )

    lines = [
        horizontal
    ]

    for row in matrix:

        formatted_row = (

            "|"

            + "|".join(

                f" {value:>{width}} "

                for value in row
            )

            + "|"
        )

        lines.append(
            formatted_row
        )

        lines.append(
            horizontal
        )

    return "\n".join(lines)


# =====================================================================
# Statistics
# =====================================================================

def matrix_statistics(
    matrix: Sequence[Sequence[int]],
) -> dict[str, int]:
    """
    Calculate basic matrix information.
    """

    if not matrix or not matrix[0]:

        return {
            "rows": 0,
            "columns": 0,
            "cells": 0,
            "minimum": 0,
            "maximum": 0,
        }

    values = [

        value

        for row in matrix

        for value in row
    ]

    return {

        "rows":
            len(matrix),

        "columns":
            len(matrix[0]),

        "cells":
            len(values),

        "minimum":
            min(values),

        "maximum":
            max(values),
    }


# =====================================================================
# File exporting
# =====================================================================

def save_matrix(
    matrix: Sequence[Sequence[int]],
    output: str | Path,
    *,
    file_format: str = "auto",
    border: bool = False,
) -> Path:
    """
    Save the generated matrix.

    Supported formats:

        txt
        csv
        json

    If file_format="auto", the extension determines the format.
    """

    path = Path(
        output
    ).expanduser()

    # Create directories automatically.

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    fmt = (
        file_format
        .strip()
        .lower()
    )

    # ---------------------------------------------------------------
    # Automatically infer format
    # ---------------------------------------------------------------

    if fmt == "auto":

        suffix = (
            path
            .suffix
            .lower()
        )

        fmt = {

            ".csv":
                "csv",

            ".json":
                "json",

            ".txt":
                "txt",

        }.get(
            suffix,
            "txt",
        )

    # ---------------------------------------------------------------
    # Validate format
    # ---------------------------------------------------------------

    if fmt not in {
        "txt",
        "csv",
        "json",
    }:

        raise ValueError(
            "file_format must be one of: "
            "auto, txt, csv, json"
        )

    # ---------------------------------------------------------------
    # CSV
    # ---------------------------------------------------------------

    if fmt == "csv":

        with path.open(
            "w",
            newline="",
            encoding="utf-8",
        ) as handle:

            writer = csv.writer(
                handle
            )

            writer.writerows(
                matrix
            )

    # ---------------------------------------------------------------
    # JSON
    # ---------------------------------------------------------------

    elif fmt == "json":

        with path.open(
            "w",
            encoding="utf-8",
        ) as handle:

            json.dump(
                matrix,
                handle,
                indent=2,
            )

            handle.write(
                "\n"
            )

    # ---------------------------------------------------------------
    # TXT
    # ---------------------------------------------------------------

    else:

        path.write_text(

            format_matrix(
                matrix,
                border=border,
            )
            + "\n",

            encoding="utf-8",
        )

    return path


# =====================================================================
# Interactive input helpers
# =====================================================================

def _prompt_int(
    prompt: str,
    *,
    default: int | None = None,
    positive: bool = False,
) -> int:
    """
    Repeatedly ask until the user enters a valid integer.
    """

    while True:

        default_text = (

            f" [{default}]"

            if default is not None

            else ""
        )

        raw = input(
            f"{prompt}{default_text}: "
        ).strip()

        # Use default if user simply presses Enter.

        if (
            not raw
            and default is not None
        ):

            value = default

        else:

            try:

                value = int(
                    raw
                )

            except ValueError:

                print(
                    "Please enter a whole number."
                )

                continue

        if positive and value <= 0:

            print(
                "Please enter a number greater than zero."
            )

            continue

        return value


def _prompt_choice(
    prompt: str,
    choices: Sequence[str],
    default: str,
) -> str:
    """
    Prompt for one option from a sequence.
    """

    choice_text = "/".join(
        choices
    )

    while True:

        raw = input(

            f"{prompt} "
            f"({choice_text}) "
            f"[{default}]: "

        ).strip()

        if not raw:
            return default

        if raw in choices:
            return raw

        print(
            "Please choose one of: "
            + ", ".join(choices)
        )


# =====================================================================
# Interactive configuration
# =====================================================================

def interactive_arguments() -> argparse.Namespace:
    """
    Ask the user for matrix configuration interactively.
    """

    print(
        "\n"
        "========================================\n"
        "   ADVANCED SPIRAL MATRIX GENERATOR\n"
        "========================================"
    )

    print(
        "\nPress Enter to accept a value "
        "shown inside [brackets].\n"
    )

    rows = _prompt_int(
        "Rows",
        default=5,
        positive=True,
    )

    columns = _prompt_int(
        "Columns",
        default=rows,
        positive=True,
    )

    start = _prompt_int(
        "Starting value",
        default=1,
    )

    # Step may be negative but not zero.

    while True:

        step = _prompt_int(
            "Step / increment",
            default=1,
        )

        if step != 0:
            break

        print(
            "Step cannot be zero."
        )

    corner = _prompt_choice(
        "Starting corner",
        VALID_CORNERS,
        "top-left",
    )

    direction = _prompt_choice(
        "Direction",
        VALID_DIRECTIONS,
        "clockwise",
    )

    return argparse.Namespace(

        rows=rows,

        columns=columns,

        start=start,

        step=step,

        corner=corner,

        direction=direction,

        border=False,

        output=None,

        format="auto",

        stats=False,

        self_test=False,
    )


# =====================================================================
# CLI
# =====================================================================

def build_parser() -> argparse.ArgumentParser:
    """
    Create command-line interface.
    """

    parser = argparse.ArgumentParser(

        description=(
            "Generate clockwise or "
            "counter-clockwise spiral matrices."
        ),

        formatter_class=(
            argparse.ArgumentDefaultsHelpFormatter
        ),
    )

    # ---------------------------------------------------------------
    # Dimensions
    # ---------------------------------------------------------------

    parser.add_argument(
        "rows",
        nargs="?",
        type=int,
        help="number of rows",
    )

    parser.add_argument(
        "columns",
        nargs="?",
        type=int,
        help=(
            "number of columns; "
            "defaults to rows"
        ),
    )

    # ---------------------------------------------------------------
    # Number sequence
    # ---------------------------------------------------------------

    parser.add_argument(
        "--start",
        type=int,
        default=1,
        help="first value",
    )

    parser.add_argument(
        "--step",
        type=int,
        default=1,
        help=(
            "non-zero increment "
            "or decrement"
        ),
    )

    # ---------------------------------------------------------------
    # Geometry
    # ---------------------------------------------------------------

    parser.add_argument(
        "--corner",

        choices=VALID_CORNERS,

        default="top-left",

        help=(
            "corner containing "
            "the first value"
        ),
    )

    parser.add_argument(
        "--direction",

        choices=VALID_DIRECTIONS,

        default="clockwise",

        help=(
            "spiral rotation direction"
        ),
    )

    # ---------------------------------------------------------------
    # Display
    # ---------------------------------------------------------------

    parser.add_argument(
        "--border",

        action="store_true",

        help=(
            "draw an ASCII table border"
        ),
    )

    parser.add_argument(
        "--stats",

        action="store_true",

        help=(
            "display matrix statistics"
        ),
    )

    # ---------------------------------------------------------------
    # Export
    # ---------------------------------------------------------------

    parser.add_argument(
        "-o",
        "--output",

        help=(
            "optional output filename"
        ),
    )

    parser.add_argument(
        "--format",

        choices=(
            "auto",
            "txt",
            "csv",
            "json",
        ),

        default="auto",

        help=(
            "output-file format"
        ),
    )

    # ---------------------------------------------------------------
    # Testing
    # ---------------------------------------------------------------

    parser.add_argument(
        "--self-test",

        action="store_true",

        help=(
            "run built-in regression "
            "tests and exit"
        ),
    )

    return parser


# =====================================================================
# Tests
# =====================================================================

class SpiralMatrixTests(
    unittest.TestCase
):
    """
    Regression tests for the spiral engine.
    """

    # ---------------------------------------------------------------
    # Classic 3 x 3
    # ---------------------------------------------------------------

    def test_default_3_by_3(
        self,
    ) -> None:

        self.assertEqual(

            generate_spiral_matrix(3),

            [
                [1, 2, 3],

                [8, 9, 4],

                [7, 6, 5],
            ],
        )

    # ---------------------------------------------------------------
    # Original-style 4 x 4
    # ---------------------------------------------------------------

    def test_default_4_by_4(
        self,
    ) -> None:

        self.assertEqual(

            generate_spiral_matrix(4),

            [
                [1, 2, 3, 4],

                [12, 13, 14, 5],

                [11, 16, 15, 6],

                [10, 9, 8, 7],
            ],
        )

    # ---------------------------------------------------------------
    # Rectangle
    # ---------------------------------------------------------------

    def test_rectangular_matrix(
        self,
    ) -> None:

        self.assertEqual(

            generate_spiral_matrix(
                3,
                4,
            ),

            [
                [1, 2, 3, 4],

                [10, 11, 12, 5],

                [9, 8, 7, 6],
            ],
        )

    # ---------------------------------------------------------------
    # Counter-clockwise
    # ---------------------------------------------------------------

    def test_counterclockwise(
        self,
    ) -> None:

        self.assertEqual(

            generate_spiral_matrix(

                3,

                direction="counterclockwise",
            ),

            [
                [1, 8, 7],

                [2, 9, 6],

                [3, 4, 5],
            ],
        )

    # ---------------------------------------------------------------
    # Alternate corner
    # ---------------------------------------------------------------

    def test_top_right_clockwise(
        self,
    ) -> None:

        self.assertEqual(

            generate_spiral_matrix(

                3,

                corner="top-right",
            ),

            [
                [7, 8, 1],

                [6, 9, 2],

                [5, 4, 3],
            ],
        )

    # ---------------------------------------------------------------
    # Custom numerical sequence
    # ---------------------------------------------------------------

    def test_custom_start_and_step(
        self,
    ) -> None:

        self.assertEqual(

            generate_spiral_matrix(

                2,

                start=10,

                step=5,
            ),

            [
                [10, 15],

                [25, 20],
            ],
        )

    # ---------------------------------------------------------------
    # Reverse values
    # ---------------------------------------------------------------

    def test_negative_step(
        self,
    ) -> None:

        matrix = generate_spiral_matrix(

            2,
            3,

            start=10,

            step=-2,
        )

        values = sorted(

            value

            for row in matrix

            for value in row
        )

        self.assertEqual(

            values,

            [
                0,
                2,
                4,
                6,
                8,
                10,
            ],
        )

    # ---------------------------------------------------------------
    # Exhaustive small-size orientation checks
    # ---------------------------------------------------------------

    def test_all_orientations_and_small_shapes(
        self,
    ) -> None:

        for rows in range(1, 6):

            for columns in range(1, 6):

                expected = list(
                    range(
                        1,
                        rows * columns + 1,
                    )
                )

                for corner in VALID_CORNERS:

                    for direction in VALID_DIRECTIONS:

                        with self.subTest(

                            rows=rows,

                            columns=columns,

                            corner=corner,

                            direction=direction,
                        ):

                            matrix = (
                                generate_spiral_matrix(

                                    rows,

                                    columns,

                                    corner=corner,

                                    direction=direction,
                                )
                            )

                            flattened = [

                                value

                                for row in matrix

                                for value in row
                            ]

                            self.assertEqual(

                                sorted(flattened),

                                expected,
                            )

    # ---------------------------------------------------------------
    # Invalid dimensions
    # ---------------------------------------------------------------

    def test_invalid_dimensions(
        self,
    ) -> None:

        with self.assertRaises(
            ValueError
        ):

            generate_spiral_matrix(
                0
            )

        with self.assertRaises(
            ValueError
        ):

            generate_spiral_matrix(
                3,
                -1,
            )

    # ---------------------------------------------------------------
    # Zero increment
    # ---------------------------------------------------------------

    def test_zero_step_is_rejected(
        self,
    ) -> None:

        with self.assertRaises(
            ValueError
        ):

            generate_spiral_matrix(

                3,

                step=0,
            )

    # ---------------------------------------------------------------
    # Formatter
    # ---------------------------------------------------------------

    def test_formatter_alignment(
        self,
    ) -> None:

        result = format_matrix(

            [
                [1, 20],

                [300, 4],
            ]
        )

        self.assertEqual(

            result,

            "  1   20\n"
            "300    4",
        )


# =====================================================================
# Self-test runner
# =====================================================================

def run_self_tests() -> bool:
    """
    Execute all built-in regression tests.
    """

    suite = (
        unittest
        .defaultTestLoader
        .loadTestsFromTestCase(
            SpiralMatrixTests
        )
    )

    result = (

        unittest
        .TextTestRunner(
            verbosity=2
        )
        .run(
            suite
        )
    )

    return result.wasSuccessful()


# =====================================================================
# Main program
# =====================================================================

def main(
    argv: Sequence[str] | None = None,
) -> int:
    """
    Application entry point.
    """

    parser = build_parser()

    args = parser.parse_args(
        argv
    )

    # ---------------------------------------------------------------
    # Self-tests
    # ---------------------------------------------------------------

    if args.self_test:

        success = run_self_tests()

        return (
            0
            if success
            else 1
        )

    # ---------------------------------------------------------------
    # If no dimensions were supplied, enter interactive mode.
    # ---------------------------------------------------------------

    if args.rows is None:

        args = interactive_arguments()

    # One dimension means square matrix.

    elif args.columns is None:

        args.columns = args.rows

    # ---------------------------------------------------------------
    # Generate matrix
    # ---------------------------------------------------------------

    try:

        matrix = generate_spiral_matrix(

            args.rows,

            args.columns,

            start=args.start,

            step=args.step,

            corner=args.corner,

            direction=args.direction,
        )

    except (
        TypeError,
        ValueError,
    ) as exc:

        parser.error(
            str(exc)
        )

    # ---------------------------------------------------------------
    # Display
    # ---------------------------------------------------------------

    print()

    print(
        format_matrix(

            matrix,

            border=args.border,
        )
    )

    # ---------------------------------------------------------------
    # Statistics
    # ---------------------------------------------------------------

    if args.stats:

        stats = matrix_statistics(
            matrix
        )

        print()

        print(
            f"Rows: "
            f"{stats['rows']}"
        )

        print(
            f"Columns: "
            f"{stats['columns']}"
        )

        print(
            f"Cells: "
            f"{stats['cells']}"
        )

        print(
            f"Minimum: "
            f"{stats['minimum']}"
        )

        print(
            f"Maximum: "
            f"{stats['maximum']}"
        )

    # ---------------------------------------------------------------
    # Export
    # ---------------------------------------------------------------

    if args.output:

        try:

            saved_to = save_matrix(

                matrix,

                args.output,

                file_format=args.format,

                border=args.border,
            )

        except (
            OSError,
            ValueError,
        ) as exc:

            print(

                f"Error saving matrix: "
                f"{exc}",

                file=sys.stderr,
            )

            return 1

        print()

        print(
            "Saved to: "
            f"{saved_to.resolve()}"
        )

    return 0


# =====================================================================
# Python execution guard
# =====================================================================

if __name__ == "__main__":

    raise SystemExit(
        main()
    )
