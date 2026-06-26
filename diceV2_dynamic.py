from __future__ import annotations

import random
import re
from dataclasses import dataclass
from statistics import mean


# Uses the operating system's random source rather than predictable pseudo-random values.
RNG = random.SystemRandom()

MAX_DICE = 100
MAX_SIDES = 1_000_000

DICE_PATTERN = re.compile(
    r"^\s*(?P<count>\d*)d(?P<sides>\d+)(?P<modifier>[+-]\d+)?\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Dice:
    """A single die with a fixed number of sides."""

    sides: int

    def __post_init__(self) -> None:
        if not 4 <= self.sides <= MAX_SIDES:
            raise ValueError(
                f"Dice must have between 4 and {MAX_SIDES:,} sides."
            )

    def roll(self) -> int:
        return RNG.randint(1, self.sides)


@dataclass(frozen=True)
class RollRequest:
    """A parsed request such as 2d6+3."""

    count: int
    sides: int
    modifier: int = 0

    def __post_init__(self) -> None:
        if not 1 <= self.count <= MAX_DICE:
            raise ValueError(
                f"You can roll between 1 and {MAX_DICE} dice at once."
            )

        if not 4 <= self.sides <= MAX_SIDES:
            raise ValueError(
                f"Dice must have between 4 and {MAX_SIDES:,} sides."
            )

    @property
    def display(self) -> str:
        modifier = f"{self.modifier:+d}" if self.modifier else ""
        return f"{self.count}d{self.sides}{modifier}"


@dataclass
class RollResult:
    request: RollRequest
    rolls: list[int]

    @property
    def dice_total(self) -> int:
        return sum(self.rolls)

    @property
    def total(self) -> int:
        return self.dice_total + self.request.modifier

    @property
    def average(self) -> float:
        return mean(self.rolls)


def parse_dice_notation(text: str) -> RollRequest:
    """
    Supports:
      d20
      2d6
      4d8+2
      3d10-1
    """
    match = DICE_PATTERN.match(text)

    if not match:
        raise ValueError(
            "Invalid dice notation. Try: d20, 2d6, 4d8+2, or 3d10-1."
        )

    count_text = match.group("count")
    sides_text = match.group("sides")
    modifier_text = match.group("modifier")

    return RollRequest(
        count=int(count_text) if count_text else 1,
        sides=int(sides_text),
        modifier=int(modifier_text) if modifier_text else 0,
    )


def roll_dice(request: RollRequest) -> RollResult:
    die = Dice(request.sides)
    rolls = [die.roll() for _ in range(request.count)]
    return RollResult(request=request, rolls=rolls)


def display_result(result: RollResult) -> None:
    rolls_text = ", ".join(map(str, result.rolls))
    modifier = result.request.modifier

    print(f"\nRoll: {result.request.display}")
    print(f"Dice results: [{rolls_text}]")
    print(f"Dice total: {result.dice_total}")

    if modifier:
        print(f"Modifier: {modifier:+d}")

    print(f"Final total: {result.total}")
    print(
        f"Statistics: min={min(result.rolls)}, "
        f"max={max(result.rolls)}, "
        f"average={result.average:.2f}"
    )


def display_history(history: list[RollResult]) -> None:
    if not history:
        print("\nNo rolls recorded yet.")
        return

    print("\n=== Roll History ===")
    for number, result in enumerate(history, start=1):
        print(
            f"{number}. {result.request.display:<10} "
            f"rolls={result.rolls} total={result.total}"
        )


def display_help() -> None:
    print(
        """
=== Dice Roller Help ===
Enter dice notation:
  d20       Roll one 20-sided die
  2d6       Roll two 6-sided dice
  4d8+2     Roll four 8-sided dice and add 2
  3d10-1    Roll three 10-sided dice and subtract 1

Commands:
  help      Show this help text
  history   Show previous rolls
  quit      Exit the program
"""
    )


def main() -> None:
    history: list[RollResult] = []

    print("=== Advanced Dice Roller ===")
    print("Type 'help' for instructions.\n")

    while True:
        user_input = input("Enter dice notation: ").strip().lower()

        if user_input in {"quit", "exit", "q"}:
            print(f"\nGoodbye. You made {len(history)} roll(s).")
            break

        if user_input in {"help", "h", "?"}:
            display_help()
            continue

        if user_input in {"history", "his"}:
            display_history(history)
            continue

        try:
            request = parse_dice_notation(user_input)
            result = roll_dice(request)
            history.append(result)
            display_result(result)

        except ValueError as error:
            print(f"\nError: {error}")


if __name__ == "__main__":
    main()
