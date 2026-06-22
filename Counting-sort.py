from typing import List


def read_int(prompt: str) -> int:
    """Read a valid integer from the user."""
    while True:
        try:
            return int(input(prompt))
        except ValueError:
            print("Please enter a whole number.")


def counting_sort(values: List[int]) -> List[int]:
    """Return a sorted copy of values using counting sort."""
    if not values:
        return []

    smallest = min(values)
    largest = max(values)
    value_range = largest - smallest + 1

    # Counting sort is inefficient if the numeric range is enormous.
    if value_range > 1_000_000:
        raise ValueError(
            "Number range is too large for counting sort. "
            "Use sorted() or another sorting algorithm."
        )

    counts = [0] * value_range

    # Count each number, shifted by smallest for negative support.
    for value in values:
        counts[value - smallest] += 1

    sorted_values = []

    # Rebuild the sorted list efficiently.
    for offset, frequency in enumerate(counts):
        if frequency:
            sorted_values.extend([offset + smallest] * frequency)

    return sorted_values


def main() -> None:
    amount = read_int("Enter number of elements: ")

    if amount < 0:
        print("Number of elements cannot be negative.")
        return

    values = [
        read_int(f"Enter element {index + 1}: ")
        for index in range(amount)
    ]

    try:
        print("\nOriginal list:", values)
        print("Sorted list:  ", counting_sort(values))
    except ValueError as error:
        print(f"\nSorting error: {error}")


if __name__ == "__main__":
    main()
