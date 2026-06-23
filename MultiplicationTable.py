"""
Advanced Multiplication Table Generator
"""

def get_number(prompt):
    while True:
        try:
            return float(input(prompt))
        except ValueError:
            print("Please enter a valid number.")

def format_number(number):
    """Remove unnecessary .0 from whole numbers."""
    return int(number) if number.is_integer() else number

print("=" * 38)
print("   MULTIPLICATION TABLE GENERATOR")
print("=" * 38)

while True:
    number = get_number("\nEnter a number: ")
    start = int(get_number("Start multiplier: "))
    end = int(get_number("End multiplier: "))

    if start > end:
        start, end = end, start
        print("Start and end were swapped automatically.")

    print(f"\nMultiplication table for {format_number(number)}")
    print("-" * 38)

    for i in range(start, end + 1):
        answer = number * i
        print(f"{format_number(number):>8} × {i:>3} = {format_number(answer):>10}")

    print("-" * 38)

    again = input("Generate another table? (y/n): ").strip().lower()
    if again not in ("y", "yes"):
        print("Goodbye!")
        break
