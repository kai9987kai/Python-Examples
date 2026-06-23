def get_number():
    """Keep asking until the user enters a valid whole number."""
    while True:
        try:
            return int(input("Enter a number for its multiplication table: "))
        except ValueError:
            print("Please enter a valid whole number.\n")


def print_table(number, limit=12):
    """Print a neatly formatted multiplication table."""
    print(f"\n{'=' * 30}")
    print(f" Multiplication Table for {number}")
    print(f"{'=' * 30}")

    for multiplier in range(1, limit + 1):
        answer = number * multiplier
        print(f"{number:>4} × {multiplier:>2} = {answer:>6}")

    print(f"{'=' * 30}")


def main():
    number = get_number()

    while True:
        try:
            limit = int(input("How far should the table go? [default 12]: ") or 12)
            if limit < 1:
                print("Use a number greater than zero.")
                continue
            break
        except ValueError:
            print("Please enter a valid whole number.")

    print_table(number, limit)


if __name__ == "__main__":
    main()
