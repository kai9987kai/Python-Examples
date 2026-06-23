"""Odd Number Generator — improved version."""

def get_amount():
    while True:
        try:
            amount = int(input("How many odd numbers would you like? "))
            if amount < 0:
                print("Please enter 0 or a positive whole number.")
                continue
            return amount
        except ValueError:
            print("Please enter a valid whole number.")


def generate_odd_numbers(amount):
    return [2 * number + 1 for number in range(amount)]


def main():
    n = get_amount()
    odd_numbers = generate_odd_numbers(n)

    print(f"\nFirst {n} odd number{'s' if n != 1 else ''}:")
    for position, number in enumerate(odd_numbers, start=1):
        print(f"{position:>2}. {number}")

    if odd_numbers:
        print(f"\nSum: {sum(odd_numbers)}")
        print(f"Last odd number: {odd_numbers[-1]}")


if __name__ == "__main__":
    main()
