# Even Number Generator

def get_non_negative_integer(prompt):
    """Keep asking until the user enters a valid non-negative whole number."""
    while True:
        try:
            value = int(input(prompt))
            if value < 0:
                print("Please enter 0 or a positive whole number.")
                continue
            return value
        except ValueError:
            print("Invalid input. Please enter a whole number.")

def generate_even_numbers(amount, start=0):
    """Return a list containing the requested number of even values."""
    return [start + 2 * index for index in range(amount)]

amount = get_non_negative_integer("How many even numbers would you like? ")

numbers = generate_even_numbers(amount)

if numbers:
    print("\nEven numbers:")
    print(", ".join(map(str, numbers)))
else:
    print("\nNo numbers requested.")
