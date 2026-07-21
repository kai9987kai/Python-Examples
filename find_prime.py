#!/usr/bin/env python3
"""
Advanced Prime Number Generator
================================

Generate prime numbers using either:

1. A highly efficient Sieve of Eratosthenes
2. A memory-efficient segmented sieve

Examples
--------
Generate primes up to 100:

    python find_prime.py 100

Generate primes between 1,000 and 2,000:

    python find_prime.py 2000 --start 1000

Print one prime per line:

    python find_prime.py 100 --format lines

Count primes without printing them:

    python find_prime.py 1000000 --count-only

Save the result as JSON:

    python find_prime.py 10000 --format json --output primes.json

Force the segmented sieve:

    python find_prime.py 100000000 --method segmented --stats
"""

from __future__ import annotations

import argparse
import sys
import time
from contextlib import nullcontext
from math import isqrt
from pathlib import Path
from typing import Iterable, Iterator, TextIO


CLASSIC_SIEVE_LIMIT = 20_000_000
DEFAULT_SEGMENT_SIZE = 1_000_000


def simple_sieve(limit: int) -> list[int]:
    """
    Return every prime number from 2 through ``limit``.

    This implementation uses a bytearray to reduce memory usage and starts
    removing multiples at p² because smaller multiples have already been
    handled by earlier primes.

    Time complexity:
        O(n log log n)

    Space complexity:
        O(n)
    """
    if limit < 2:
        return []

    sieve = bytearray(b"\x01") * (limit + 1)
    sieve[0:2] = b"\x00\x00"

    for prime in range(2, isqrt(limit) + 1):
        if not sieve[prime]:
            continue

        first_multiple = prime * prime
        number_of_multiples = (
            (limit - first_multiple) // prime
        ) + 1

        sieve[first_multiple : limit + 1 : prime] = (
            b"\x00" * number_of_multiples
        )

    return [
        number
        for number in range(2, limit + 1)
        if sieve[number]
    ]


def segmented_sieve(
    start: int,
    limit: int,
    segment_size: int = DEFAULT_SEGMENT_SIZE,
) -> Iterator[int]:
    """
    Yield prime numbers between ``start`` and ``limit`` inclusive.

    Unlike the classic sieve, this function processes the requested range in
    smaller blocks. It is useful when ``limit`` is very large because it does
    not allocate one byte for every number up to the limit.

    Space complexity:
        O(sqrt(n) + segment_size)
    """
    if start > limit or limit < 2:
        return

    if segment_size < 1:
        raise ValueError("segment_size must be at least 1")

    start = max(start, 2)

    base_primes = simple_sieve(isqrt(limit))

    for low in range(start, limit + 1, segment_size):
        high = min(low + segment_size - 1, limit)

        segment = bytearray(b"\x01") * (high - low + 1)

        for prime in base_primes:
            first_multiple = max(
                prime * prime,
                ((low + prime - 1) // prime) * prime,
            )

            if first_multiple > high:
                continue

            offset = first_multiple - low
            number_of_multiples = (
                (high - first_multiple) // prime
            ) + 1

            segment[offset::prime] = (
                b"\x00" * number_of_multiples
            )

        for offset, is_prime in enumerate(segment):
            if is_prime:
                yield low + offset


def generate_primes(
    start: int,
    limit: int,
    method: str = "auto",
    segment_size: int = DEFAULT_SEGMENT_SIZE,
) -> tuple[Iterable[int], str]:
    """
    Select a prime-generation method and return its result.

    Returns
    -------
    tuple
        ``(prime_iterable, selected_method)``
    """
    if start > limit:
        raise ValueError(
            f"Start value {start:,} cannot be greater than "
            f"limit {limit:,}."
        )

    selected_method = method

    if method == "auto":
        if start <= 2 and limit <= CLASSIC_SIEVE_LIMIT:
            selected_method = "classic"
        else:
            selected_method = "segmented"

    if selected_method == "classic":
        all_primes = simple_sieve(limit)

        primes = (
            prime
            for prime in all_primes
            if prime >= start
        )

        return primes, selected_method

    if selected_method == "segmented":
        return (
            segmented_sieve(start, limit, segment_size),
            selected_method,
        )

    raise ValueError(f"Unknown sieve method: {method}")


def write_primes(
    primes: Iterable[int],
    output_format: str,
    stream: TextIO,
) -> int:
    """
    Write primes to a text stream without requiring the complete result to
    remain in memory.

    Returns the number of primes written.
    """
    count = 0
    first_item = True

    if output_format in {"list", "json"}:
        stream.write("[")

    elif output_format == "csv":
        stream.write("prime\n")

    for prime in primes:
        if output_format == "lines":
            stream.write(f"{prime}\n")

        elif output_format == "csv":
            stream.write(f"{prime}\n")

        elif output_format == "json":
            if not first_item:
                stream.write(",")

            stream.write(str(prime))

        elif output_format == "list":
            if not first_item:
                stream.write(", ")

            stream.write(str(prime))

        else:
            raise ValueError(
                f"Unsupported output format: {output_format}"
            )

        first_item = False
        count += 1

    if output_format in {"list", "json"}:
        stream.write("]\n")

    return count


def count_primes(primes: Iterable[int]) -> int:
    """Count values from a prime-number iterable."""
    return sum(1 for _ in primes)


def positive_integer(value: str) -> int:
    """Argparse validator for positive integer arguments."""
    try:
        number = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            f"{value!r} is not an integer."
        ) from error

    if number < 1:
        raise argparse.ArgumentTypeError(
            "Value must be greater than zero."
        )

    return number


def build_parser() -> argparse.ArgumentParser:
    """Create the command-line argument parser."""
    parser = argparse.ArgumentParser(
        prog="find_prime.py",
        description=(
            "Generate prime numbers efficiently with a classic or "
            "segmented Sieve of Eratosthenes."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument(
        "limit",
        type=int,
        help="inclusive upper limit",
    )

    parser.add_argument(
        "-s",
        "--start",
        type=int,
        default=2,
        help="inclusive lower limit",
    )

    parser.add_argument(
        "-m",
        "--method",
        choices=("auto", "classic", "segmented"),
        default="auto",
        help="prime-generation algorithm",
    )

    parser.add_argument(
        "--segment-size",
        type=positive_integer,
        default=DEFAULT_SEGMENT_SIZE,
        help="numbers processed in each segmented-sieve block",
    )

    parser.add_argument(
        "-f",
        "--format",
        choices=("list", "lines", "json", "csv"),
        default="list",
        help="result output format",
    )

    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="write results to this file instead of standard output",
    )

    parser.add_argument(
        "-c",
        "--count-only",
        action="store_true",
        help="only display the number of discovered primes",
    )

    parser.add_argument(
        "--stats",
        action="store_true",
        help="display execution and algorithm statistics",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the command-line application."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.start > args.limit:
        parser.error("--start cannot be greater than limit")

    started_at = time.perf_counter()

    try:
        primes, selected_method = generate_primes(
            start=args.start,
            limit=args.limit,
            method=args.method,
            segment_size=args.segment_size,
        )

        if args.count_only:
            prime_count = count_primes(primes)
            print(prime_count)

        else:
            output_context = (
                args.output.open("w", encoding="utf-8")
                if args.output
                else nullcontext(sys.stdout)
            )

            with output_context as output_stream:
                prime_count = write_primes(
                    primes,
                    args.format,
                    output_stream,
                )

    except (OSError, ValueError, MemoryError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    elapsed = time.perf_counter() - started_at

    if args.stats:
        destination = (
            str(args.output)
            if args.output
            else "standard output"
        )

        print(
            "\nPrime generation statistics",
            f"Range:          {args.start:,} to {args.limit:,}",
            f"Prime count:    {prime_count:,}",
            f"Method:         {selected_method}",
            f"Segment size:   {args.segment_size:,}",
            f"Output:         {destination}",
            f"Elapsed time:   {elapsed:.6f} seconds",
            sep="\n",
            file=sys.stderr,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
