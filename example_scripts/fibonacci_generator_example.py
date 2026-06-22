#!/usr/bin/env python3
"""Generate Fibonacci numbers with a Python generator."""


def fibonacci(limit):
    """Yield Fibonacci numbers less than or equal to limit."""
    first, second = 0, 1
    while first <= limit:
        yield first
        first, second = second, first + second


def main():
    numbers = list(fibonacci(100))
    print("Fibonacci numbers up to 100:")
    print(", ".join(str(number) for number in numbers))


if __name__ == "__main__":
    main()
