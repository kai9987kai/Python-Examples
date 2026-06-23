"""
Chaotic Behaviour Demonstrator
Uses the logistic map: x(n+1) = r * x(n) * (1 - x(n))
"""

def get_float(prompt, minimum=None, maximum=None):
    """Read and validate a floating-point number from the user."""
    while True:
        try:
            value = float(input(prompt))

            if minimum is not None and value <= minimum:
                print(f"Please enter a number greater than {minimum}.")
                continue

            if maximum is not None and value >= maximum:
                print(f"Please enter a number less than {maximum}.")
                continue

            return value

        except ValueError:
            print("Invalid input. Please enter a valid number.")


def logistic_map(x, r):
    """Calculate the next value in the logistic map sequence."""
    return r * x * (1 - x)


def main():
    print("=" * 55)
    print("         CHAOTIC BEHAVIOUR DEMONSTRATOR")
    print("=" * 55)
    print("Formula: x(n+1) = r × x(n) × (1 - x(n))")
    print("Values near r = 4 can produce chaotic behaviour.\n")

    x = get_float("Enter an initial value between 0 and 1: ", 0, 1)
    r = get_float("Enter a growth rate r (usually 0 to 4): ", 0, 4)

    while True:
        try:
            iterations = int(input("How many iterations would you like? "))

            if iterations > 0:
                break

            print("Please enter a positive whole number.")
        except ValueError:
            print("Please enter a whole number.")

    print("\nIteration | Value")
    print("-" * 25)

    for iteration in range(1, iterations + 1):
        x = logistic_map(x, r)
        print(f"{iteration:9} | {x:.10f}")

    print("\nExperiment with very similar starting values, such as:")
    print("0.500000 and 0.500001, using r = 3.9 or r = 4.0.")


if __name__ == "__main__":
    main()
