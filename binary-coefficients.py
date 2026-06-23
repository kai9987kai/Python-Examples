from math import comb


def pascal_triangle(rows: int) -> list[list[int]]:
    """Return Pascal's triangle with the requested number of rows."""
    if not isinstance(rows, int) or rows < 1:
        raise ValueError("rows must be a positive integer.")

    triangle = []

    for row_index in range(rows):
        row = [1] * (row_index + 1)

        for column in range(1, row_index):
            row[column] = triangle[row_index - 1][column - 1] + triangle[row_index - 1][column]

        triangle.append(row)

    return triangle


def binomial_coefficient(n: int, k: int) -> int:
    """Return n choose k: the coefficient of x^k in (a + x)^n."""
    if not isinstance(n, int) or not isinstance(k, int):
        raise TypeError("n and k must be integers.")
    if n < 0:
        raise ValueError("n must be zero or greater.")
    if not 0 <= k <= n:
        raise ValueError("k must be between 0 and n.")

    return comb(n, k)


def print_pascal_triangle(rows: int) -> None:
    """Print a centred Pascal triangle."""
    triangle = pascal_triangle(rows)
    width = len(" ".join(map(str, triangle[-1])))

    for row in triangle:
        print(" ".join(map(str, row)).center(width))


if __name__ == "__main__":
    print("Pascal's Triangle:\n")
    print_pascal_triangle(8)

    n = 6
    k = 2
    print(f"\nC({n}, {k}) = {binomial_coefficient(n, k)}")
