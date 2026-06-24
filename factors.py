import math


def get_positive_integer():
    """Keep asking until the user enters a positive whole number."""
    while True:
        try:
            number = int(input("Type a positive whole number: "))
            if number > 0:
                return number
            print("Please enter a number greater than 0.")
        except ValueError:
            print("That is not a valid whole number.")


def find_factors(number):
    """Return all factors of a positive integer in ascending order."""
    small_factors = []
    large_factors = []

    for factor in range(1, math.isqrt(number) + 1):
        if number % factor == 0:
            small_factors.append(factor)

            paired_factor = number // factor
            if paired_factor != factor:  # Avoid duplicate square roots
                large_factors.append(paired_factor)

    return small_factors + large_factors[::-1]


def main():
    print("This program displays every factor of a number.")

    number = get_positive_integer()
    factors = find_factors(number)

    print(f"\nFactors of {number}:")
    for factor in factors:
        print(factor)

    print(f"\nTotal factors found: {len(factors)}")


if __name__ == "__main__":
    main()
