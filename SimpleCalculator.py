"""
Advanced Python Calculator
Features:
- Add, subtract, multiply, divide
- Power and modulus
- Input validation
- Division-by-zero protection
- Calculation history
- Repeat until user exits
"""

from datetime import datetime


def add(a, b):
    return a + b


def subtract(a, b):
    return a - b


def multiply(a, b):
    return a * b


def divide(a, b):
    if b == 0:
        raise ZeroDivisionError("Cannot divide by zero.")
    return a / b


def power(a, b):
    return a ** b


def modulus(a, b):
    if b == 0:
        raise ZeroDivisionError("Cannot use modulus with zero.")
    return a % b


def get_number(message):
    """Keep asking until the user enters a valid number."""
    while True:
        try:
            return float(input(message))
        except ValueError:
            print("Invalid number. Please try again.")


def show_menu():
    print("\n" + "=" * 35)
    print("      ADVANCED CALCULATOR")
    print("=" * 35)
    print("1. Add")
    print("2. Subtract")
    print("3. Multiply")
    print("4. Divide")
    print("5. Power")
    print("6. Modulus")
    print("7. Show calculation history")
    print("8. Clear calculation history")
    print("0. Exit")


def main():
    history = []

    operations = {
        "1": ("+", add),
        "2": ("-", subtract),
        "3": ("*", multiply),
        "4": ("/", divide),
        "5": ("**", power),
        "6": ("%", modulus),
    }

    print("Welcome to the Advanced Calculator!")

    while True:
        show_menu()
        choice = input("\nEnter your choice: ").strip()

        if choice == "0":
            print("\nThanks for using the calculator. Goodbye!")
            break

        if choice == "7":
            print("\n--- Calculation History ---")

            if not history:
                print("No calculations have been made yet.")
            else:
                for item in history:
                    print(item)

            continue

        if choice == "8":
            history.clear()
            print("\nCalculation history cleared.")
            continue

        if choice not in operations:
            print("\nInvalid choice. Please choose a valid option.")
            continue

        num1 = get_number("Enter first number: ")
        num2 = get_number("Enter second number: ")

        symbol, operation = operations[choice]

        try:
            result = operation(num1, num2)

            calculation = f"{num1:g} {symbol} {num2:g} = {result:g}"
            timestamp = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

            print(f"\nResult: {calculation}")

            history.append(f"[{timestamp}] {calculation}")

        except ZeroDivisionError as error:
            print(f"\nError: {error}")

        except OverflowError:
            print("\nError: The result is too large to calculate.")

        except Exception as error:
            print(f"\nUnexpected error: {error}")


if __name__ == "__main__":
    main()
