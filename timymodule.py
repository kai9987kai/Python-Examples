#!/usr/bin/env python3
"""
timy_benchmark.py

Install:
    python -m pip install timy

Examples:
    python timy_benchmark.py
    python timy_benchmark.py --limit 1000000 --loops 10
    python timy_benchmark.py --clock wall --log
    python timy_benchmark.py --checkpoints
"""

from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass
from collections.abc import Callable
from typing import TypeVar

import timy
from timy.settings import TrackingMode, timy_config

T = TypeVar("T")


@dataclass(frozen=True)
class BenchmarkConfig:
    limit: int
    step: int
    loops: int
    include_sleeptime: bool


def build_with_list_comprehension(limit: int, step: int) -> list[int]:
    """Create even numbers using a list comprehension."""
    return [number for number in range(0, limit, step)]


def build_with_append_loop(limit: int, step: int) -> list[int]:
    """Create even numbers using an explicit append loop."""
    values: list[int] = []
    append = values.append  # Local binding slightly reduces loop overhead.

    for number in range(0, limit, step):
        append(number)

    return values


def run_timed(
    label: str,
    function: Callable[[int, int], T],
    config: BenchmarkConfig,
) -> T:
    """
    Apply timy's decorator dynamically so loops and clock mode
    can be configured from the command line.
    """
    timed_function = timy.timer(
        ident=label,
        loops=config.loops,
        include_sleeptime=config.include_sleeptime,
    )(function)

    return timed_function(config.limit, config.step)


def profile_append_loop(config: BenchmarkConfig) -> list[int]:
    """
    Demonstrate timy's context-manager checkpoints.

    This is intentionally separate from the benchmark so checkpoint
    logging does not distort the append-loop comparison.
    """
    values: list[int] = []
    numbers = range(0, config.limit, config.step)
    halfway_index = len(numbers) // 2

    with timy.Timer(
        ident="append-loop profile",
        include_sleeptime=config.include_sleeptime,
    ) as timer:
        for index, number in enumerate(numbers):
            values.append(number)

            if index == halfway_index:
                timer.track("50% complete")

    return values


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare list construction approaches with timy."
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100_000,
        help="Upper bound of the range (default: 100000).",
    )
    parser.add_argument(
        "--step",
        type=int,
        default=2,
        help="Step used by range() (default: 2).",
    )
    parser.add_argument(
        "--loops",
        type=int,
        default=5,
        help="Number of timed executions per method (default: 5).",
    )
    parser.add_argument(
        "--clock",
        choices=("cpu", "wall"),
        default="cpu",
        help="Use CPU time for computation or wall time for end-to-end timing.",
    )
    parser.add_argument(
        "--log",
        action="store_true",
        help="Send timy output through Python logging instead of print().",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Disable timy timing output.",
    )
    parser.add_argument(
        "--checkpoints",
        action="store_true",
        help="Run the separate context-manager checkpoint example.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_arguments()

    if args.limit < 0:
        raise ValueError("--limit must be zero or greater.")
    if args.step <= 0:
        raise ValueError("--step must be greater than zero.")
    if args.loops <= 0:
        raise ValueError("--loops must be greater than zero.")

    if args.log:
        logging.basicConfig(
            level=logging.INFO,
            format="%(levelname)s | %(name)s | %(message)s",
        )
        timy_config.tracking_mode = TrackingMode.LOGGING

    timy_config.tracking = not args.quiet

    config = BenchmarkConfig(
        limit=args.limit,
        step=args.step,
        loops=args.loops,
        include_sleeptime=(args.clock == "wall"),
    )

    print(
        f"\nBenchmarking range(0, {config.limit}, {config.step}) "
        f"over {config.loops} run(s) using {args.clock} time.\n"
    )

    comprehension_result = run_timed(
        "list-comprehension",
        build_with_list_comprehension,
        config,
    )

    append_result = run_timed(
        "append-loop",
        build_with_append_loop,
        config,
    )

    if comprehension_result != append_result:
        raise RuntimeError("Benchmark implementations produced different results.")

    print("\nValidation passed")
    print(f"Items created: {len(comprehension_result):,}")
    print(f"Checksum: {sum(comprehension_result):,}")

    if args.checkpoints:
        print("\nCheckpoint demonstration:")
        profiled_result = profile_append_loop(config)

        if profiled_result != comprehension_result:
            raise RuntimeError("Checkpoint profile produced an unexpected result.")


if __name__ == "__main__":
    main()
