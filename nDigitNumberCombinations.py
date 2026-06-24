"""
Generate every possible n-digit numeric combination.

Examples:
n = 2  -> 00, 01, 02, ... 99
n = 4  -> 0000 through 9999
"""

from pathlib import Path


def n_digit_combinations(n: int):
    """Yield every n-digit numeric combination, preserving leading zeroes."""
    if not isinstance(n, int):
        raise TypeError("n must be an integer.")

    if n < 1:
        raise ValueError("n must be at least 1.")

    total = 10 ** n

    for number in range(total):
        yield f"{number:0{n}d}"


def save_combinations(n: int, filename: str | None = None) -> Path:
    """Save all combinations to a text file, one combination per line."""
    output_file = Path(filename or f"{n}_digit_combinations.txt")

    with output_file.open("w", encoding="utf-8") as file:
        for combination in n_digit_combinations(n):
            file.write(combination + "\n")

    return output_file


def main():
    print("N-Digit Combination Generator")
    print("-" * 30)

    try:
        n = int(input("How many digits should each combination contain? ").strip())

        total = 10 ** n
        print(f"\nThis will generate {total:,} combinations.")

        if n > 6:
            confirm = input(
                "This may create a very large file. Continue? (yes/no): "
            ).strip().lower()

            if confirm not in {"yes", "y"}:
                print("Cancelled.")
                return

        action = input(
            "Choose output: [1] display, [2] save to file, [3] both: "
        ).strip()

        if action in {"1", "3"}:
            for combination in n_digit_combinations(n):
                print(combination)

        if action in {"2", "3"}:
            saved_file = save_combinations(n)
            print(f"\nSaved combinations to: {saved_file.resolve()}")

    except ValueError as error:
        print(f"Invalid input: {error}")
    except KeyboardInterrupt:
        print("\nOperation cancelled.")


if __name__ == "__main__":
    main()
