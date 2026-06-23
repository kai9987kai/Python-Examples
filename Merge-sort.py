from typing import List


def merge(left: List[int], right: List[int]) -> List[int]:
    """Merge two already-sorted lists into one sorted list."""
    merged = []
    i = j = 0

    while i < len(left) and j < len(right):
        # <= keeps the sort stable when values are equal.
        if left[i] <= right[j]:
            merged.append(left[i])
            i += 1
        else:
            merged.append(right[j])
            j += 1

    # Add remaining values without another comparison loop.
    merged.extend(left[i:])
    merged.extend(right[j:])

    return merged


def merge_sort(values: List[int]) -> List[int]:
    """Return a new sorted list using merge sort."""
    if len(values) <= 1:
        return values.copy()

    middle = len(values) // 2

    left_half = merge_sort(values[:middle])
    right_half = merge_sort(values[middle:])

    return merge(left_half, right_half)


def read_integer(prompt: str) -> int:
    """Keep asking until the user provides a valid integer."""
    while True:
        try:
            return int(input(prompt))
        except ValueError:
            print("Please enter a whole number.")


def main() -> None:
    count = read_integer("Enter number of elements: ")

    if count < 0:
        print("The number of elements cannot be negative.")
        return

    numbers = []

    for index in range(count):
        numbers.append(read_integer(f"Enter element {index + 1}: "))

    sorted_numbers = merge_sort(numbers)

    print("\nOriginal list:", numbers)
    print("Sorted list:  ", sorted_numbers)


if __name__ == "__main__":
    main()
