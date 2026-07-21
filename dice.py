#!/usr/bin/env python3
"""
Advanced dice roller.

Examples:
    python dice.py
    python dice.py 2d6
    python dice.py 4d6+3 --times 5
    python dice.py d20 --advantage
    python dice.py 2d8-1 --json
    python dice.py 3d6 --simulate 100000
"""

from __future__ import annotations

import argparse
import json
import random
import re
import statistics
from collections import Counter
from dataclasses import asdict, dataclass
from typing import Protocol, Sequence


DICE_PATTERN = re.compile(
    r"^\s*(?P<count>\d*)\s*[dD]\s*(?P<sides>\d+)"
    r"\s*(?P<modifier>[+-]\s*\d+)?\s*$"
)


class RandomSource(Protocol):
    def randint(self, a: int, b: int) -> int:
        """Return a random integer N such that a <= N <= b."""


@dataclass(frozen=True, slots=True)
class DiceExpression:
    count: int
    sides: int
    modifier: int = 0

    def __post_init__(self) -> None:
        if self.count < 1:
            raise ValueError("Dice count must be at least 1.")
        if self.count > 10_000:
            raise ValueError("Dice count cannot exceed 10,000.")
        if self.sides < 2:
            raise ValueError("A die must have at least 2 sides.")
        if self.sides > 1_000_000:
            raise ValueError("Die sides cannot exceed 1,000,000.")

    @classmethod
    def parse(cls, value: str) -> "DiceExpression":
        match = DICE_PATTERN.fullmatch(value)
        if not match:
            raise ValueError(
                f"Invalid dice expression {value!r}. "
                "Use notation such as d20, 2d6, 4d8+3, or 3d10-2."
            )

        count_text = match.group("count")
        modifier_text = match.group("modifier")

        count = int(count_text) if count_text else 1
        sides = int(match.group("sides"))
        modifier = int(modifier_text.replace(" ", "")) if modifier_text else 0
        return cls(count=count, sides=sides, modifier=modifier)

    @property
    def minimum(self) -> int:
        return self.count + self.modifier

    @property
    def maximum(self) -> int:
        return self.count * self.sides + self.modifier

    @property
    def average(self) -> float:
        return self.count * (self.sides + 1) / 2 + self.modifier

    def __str__(self) -> str:
        modifier = f"{self.modifier:+d}" if self.modifier else ""
        return f"{self.count}d{self.sides}{modifier}"


@dataclass(frozen=True, slots=True)
class RollResult:
    expression: DiceExpression
    rolls: tuple[int, ...]
    kept: tuple[int, ...]
    dropped: tuple[int, ...]
    modifier: int
    total: int

    def to_dict(self) -> dict[str, object]:
        return {
            "expression": str(self.expression),
            "rolls": list(self.rolls),
            "kept": list(self.kept),
            "dropped": list(self.dropped),
            "modifier": self.modifier,
            "total": self.total,
        }


class DiceRoller:
    def __init__(self, rng: RandomSource | None = None) -> None:
        self.rng: RandomSource = rng if rng is not None else random.SystemRandom()

    def roll(
        self,
        expression: DiceExpression,
        *,
        keep_highest: int | None = None,
        keep_lowest: int | None = None,
    ) -> RollResult:
        if keep_highest is not None and keep_lowest is not None:
            raise ValueError("Choose either keep_highest or keep_lowest, not both.")

        rolls = tuple(
            self.rng.randint(1, expression.sides)
            for _ in range(expression.count)
        )

        keep_count = keep_highest if keep_highest is not None else keep_lowest
        if keep_count is None:
            kept = rolls
            dropped: tuple[int, ...] = ()
        else:
            if not 1 <= keep_count <= expression.count:
                raise ValueError(
                    f"Keep count must be between 1 and {expression.count}."
                )

            indexed = list(enumerate(rolls))
            reverse = keep_highest is not None
            selected_indices = {
                index
                for index, _ in sorted(
                    indexed, key=lambda item: item[1], reverse=reverse
                )[:keep_count]
            }
            kept = tuple(
                value for index, value in indexed if index in selected_indices
            )
            dropped = tuple(
                value for index, value in indexed if index not in selected_indices
            )

        return RollResult(
            expression=expression,
            rolls=rolls,
            kept=kept,
            dropped=dropped,
            modifier=expression.modifier,
            total=sum(kept) + expression.modifier,
        )

    def roll_with_advantage(
        self,
        expression: DiceExpression,
        *,
        advantage: bool = False,
        disadvantage: bool = False,
    ) -> tuple[RollResult, tuple[RollResult, ...]]:
        if advantage and disadvantage:
            raise ValueError("Advantage and disadvantage cannot both be enabled.")

        if not advantage and not disadvantage:
            result = self.roll(expression)
            return result, (result,)

        candidates = (self.roll(expression), self.roll(expression))
        chosen = max(candidates, key=lambda result: result.total)
        if disadvantage:
            chosen = min(candidates, key=lambda result: result.total)
        return chosen, candidates


@dataclass(frozen=True, slots=True)
class SimulationSummary:
    expression: str
    trials: int
    minimum: int
    maximum: int
    mean: float
    median: float
    mode: int
    standard_deviation: float
    most_common_totals: tuple[tuple[int, int], ...]

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["most_common_totals"] = [
            {"total": total, "count": count}
            for total, count in self.most_common_totals
        ]
        return data


def simulate(
    roller: DiceRoller,
    expression: DiceExpression,
    trials: int,
) -> SimulationSummary:
    if trials < 1:
        raise ValueError("Simulation trials must be at least 1.")
    if trials > 5_000_000:
        raise ValueError("Simulation trials cannot exceed 5,000,000.")

    totals = [roller.roll(expression).total for _ in range(trials)]
    counts = Counter(totals)

    return SimulationSummary(
        expression=str(expression),
        trials=trials,
        minimum=min(totals),
        maximum=max(totals),
        mean=statistics.fmean(totals),
        median=statistics.median(totals),
        mode=counts.most_common(1)[0][0],
        standard_deviation=(
            statistics.pstdev(totals) if len(totals) > 1 else 0.0
        ),
        most_common_totals=tuple(counts.most_common(10)),
    )


def format_roll(result: RollResult, number: int | None = None) -> str:
    prefix = f"Roll {number}: " if number is not None else ""
    details = f"{list(result.rolls)}"

    if result.dropped:
        details += f" -> kept {list(result.kept)}, dropped {list(result.dropped)}"

    if result.modifier:
        details += f" {result.modifier:+d}"

    return f"{prefix}{result.expression}: {details} = {result.total}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Roll dice using expressions such as 2d6, d20, or 4d8+3.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "expression",
        nargs="?",
        default="2d6",
        help="Dice expression in NdS±M notation.",
    )
    parser.add_argument(
        "-n",
        "--times",
        type=int,
        default=1,
        help="Number of independent rolls.",
    )
    parser.add_argument(
        "--keep-highest",
        type=int,
        metavar="N",
        help="Keep only the highest N dice in each roll.",
    )
    parser.add_argument(
        "--keep-lowest",
        type=int,
        metavar="N",
        help="Keep only the lowest N dice in each roll.",
    )

    advantage_group = parser.add_mutually_exclusive_group()
    advantage_group.add_argument(
        "--advantage",
        action="store_true",
        help="Roll twice and use the higher total.",
    )
    advantage_group.add_argument(
        "--disadvantage",
        action="store_true",
        help="Roll twice and use the lower total.",
    )

    randomness_group = parser.add_mutually_exclusive_group()
    randomness_group.add_argument(
        "--seed",
        type=int,
        help="Use a repeatable pseudo-random seed.",
    )
    randomness_group.add_argument(
        "--secure",
        action="store_true",
        help="Use operating-system randomness.",
    )

    parser.add_argument(
        "--simulate",
        type=int,
        metavar="TRIALS",
        help="Run a statistical simulation instead of normal rolls.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )
    parser.add_argument(
        "--show-odds",
        action="store_true",
        help="Show theoretical minimum, maximum, and average.",
    )
    return parser


def create_rng(seed: int | None, secure: bool) -> RandomSource:
    if secure:
        return random.SystemRandom()
    return random.Random(seed)


def validate_args(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
    expression: DiceExpression,
) -> None:
    if args.times < 1:
        parser.error("--times must be at least 1.")

    if args.keep_highest is not None and args.keep_lowest is not None:
        parser.error("--keep-highest and --keep-lowest cannot be combined.")

    keep_count = (
        args.keep_highest
        if args.keep_highest is not None
        else args.keep_lowest
    )
    if keep_count is not None and not 1 <= keep_count <= expression.count:
        parser.error(
            f"The keep count must be between 1 and {expression.count}."
        )

    if (args.advantage or args.disadvantage) and keep_count is not None:
        parser.error(
            "Advantage/disadvantage cannot currently be combined with "
            "--keep-highest or --keep-lowest."
        )

    if args.simulate is not None and (
        args.times != 1
        or args.advantage
        or args.disadvantage
        or keep_count is not None
    ):
        parser.error(
            "--simulate cannot be combined with --times, advantage, "
            "disadvantage, or keep options."
        )


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        expression = DiceExpression.parse(args.expression)
    except ValueError as exc:
        parser.error(str(exc))

    validate_args(parser, args, expression)
    roller = DiceRoller(create_rng(args.seed, args.secure))

    if args.simulate is not None:
        try:
            summary = simulate(roller, expression, args.simulate)
        except ValueError as exc:
            parser.error(str(exc))

        if args.json:
            print(json.dumps(summary.to_dict(), indent=2))
        else:
            print(f"Simulation for {summary.expression}")
            print(f"Trials:             {summary.trials:,}")
            print(f"Observed range:     {summary.minimum} to {summary.maximum}")
            print(f"Mean:               {summary.mean:.4f}")
            print(f"Median:             {summary.median:.4f}")
            print(f"Mode:               {summary.mode}")
            print(f"Standard deviation: {summary.standard_deviation:.4f}")
            print("Most common totals:")
            for total, count in summary.most_common_totals:
                percentage = count / summary.trials * 100
                print(f"  {total:>6}: {count:>10,} ({percentage:6.2f}%)")
        return 0

    if args.advantage or args.disadvantage:
        chosen, candidates = roller.roll_with_advantage(
            expression,
            advantage=args.advantage,
            disadvantage=args.disadvantage,
        )
        if args.json:
            print(
                json.dumps(
                    {
                        "mode": (
                            "advantage" if args.advantage else "disadvantage"
                        ),
                        "candidates": [
                            candidate.to_dict() for candidate in candidates
                        ],
                        "chosen": chosen.to_dict(),
                    },
                    indent=2,
                )
            )
        else:
            mode = "Advantage" if args.advantage else "Disadvantage"
            print(f"{mode}:")
            for index, candidate in enumerate(candidates, start=1):
                print(f"  Candidate {index}: {format_roll(candidate)}")
            print(f"  Chosen total: {chosen.total}")
    else:
        results = [
            roller.roll(
                expression,
                keep_highest=args.keep_highest,
                keep_lowest=args.keep_lowest,
            )
            for _ in range(args.times)
        ]

        if args.json:
            print(
                json.dumps(
                    {
                        "expression": str(expression),
                        "results": [result.to_dict() for result in results],
                    },
                    indent=2,
                )
            )
        else:
            for index, result in enumerate(results, start=1):
                number = index if len(results) > 1 else None
                print(format_roll(result, number))

            if len(results) > 1:
                totals = [result.total for result in results]
                print(
                    f"Summary: min={min(totals)}, max={max(totals)}, "
                    f"mean={statistics.fmean(totals):.2f}, "
                    f"sum={sum(totals)}"
                )

    if args.show_odds and not args.json:
        print(
            f"Theoretical: min={expression.minimum}, "
            f"max={expression.maximum}, "
            f"average={expression.average:.2f}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
