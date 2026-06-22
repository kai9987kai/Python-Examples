from collections.abc import Sequence


def two_sum(nums: Sequence[int], target: int) -> list[int]:
    """
    Return the indices of two distinct values in nums that add up to target.

    Raises:
        ValueError: If no valid pair exists.
    """
    seen: dict[int, int] = {}

    for index, value in enumerate(nums):
        complement = target - value

        if complement in seen:
            return [seen[complement], index]

        seen[value] = index

    raise ValueError("No two numbers add up to the target.")


# Example
nums = [2, 7, 11, 15]
target = 9

print(two_sum(nums, target))  # [0, 1]
