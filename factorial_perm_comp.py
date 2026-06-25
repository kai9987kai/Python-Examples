#!/usr/bin/env python3
"""
Script Name : factorial_perm_comp.py
Description : Calculate factorials, permutations, and combinations.
"""

from math import prod


def factorial(n: int) -> int:
    """Return n! for a non-negative integer."""
    if n < 0:
        raise ValueError("n must be zero or greater.")

    return prod(range(1, n + 1)) if n > 0 else 1


def validate_n_and_r(n: int, r: int) -> None:
    """Validate values used in permutations and combinations."""
    if n < 0:
        raise ValueError("n must be zero or greater.")
    if r < 0:
        raise ValueError("r must be zero or greater.")
    if r > n:
        raise ValueError("r cannot be greater than n.")


def permutation(n: int, r: int) -> int:
    """Return nPr."""
    validate_n_and_r(n, r)
    return factorial(n) // factorial(n - r)


def combination(n: int, r: int) -> int:
    """Return nCr."""
    validate_n_and_r(n, r)
    return permutation(n, r) // factorial(r)


def get_integer(prompt: str) -> int:
    """Keep asking until the user enters a valid integer."""
    while True:
        try:
            return int(input(prompt))
        except ValueError:
            print("Invalid input. Please enter a whole number.")


def show_menu() -> None:
    print("\n" + "=" * 42)
    print(" FACTORIAL, PERMUTATION & COMBINATION")
    print("=" * 42)
    print("1) Factorial (n!)")
    print("2) Permutation (nPr)")
    print("3) Combination (nCr)")
    print("4) Exit")


def main() -> None:
    while True:
        show_menu()
        operation = input("\nChoose an option (1-4): ").strip()

        try:
            if operation == "1":
                n = get_integer("Enter a value for n: ")
                print(f"\n{n}! = {factorial(n)}")

            elif operation == "2":
                n = get_integer("Enter a value for n: ")
                r = get_integer("Enter a value for r: ")
                print(f"\n{n}P{r} = {permutation(n, r)}")

            elif operation == "3":
                n = get_integer("Enter a value for n: ")
                r = get_integer("Enter a value for r: ")
                print(f"\n{n}C{r} = {combination(n, r)}")

            elif operation == "4":
                print("\nGoodbye.")
                break

            else:
                print("\nPlease choose a number from 1 to 4.")

        except ValueError as error:
            print(f"\nError: {error}")


if __name__ == "__main__":
    main()
