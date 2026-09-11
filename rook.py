"""
Advanced Sliding Maze / Rook-Movement Shortest Path Solver
===========================================================

Rules
-----
- Start at S.
- Reach E.
- X cells are obstacles.
- A move can travel ANY number of cells:
      UP
      DOWN
      LEFT
      RIGHT
- You cannot move through an obstacle.
- Every complete slide counts as exactly ONE move.

Example:
    S . . . . . . .
    X X X X . . . .
    . . . . . . . .
    ...
    . . . . . . . E

The optimal route is:
    (0, 0) -> (0, 7) -> (7, 7)

Therefore:
    2 moves
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import (
    Deque,
    Dict,
    Iterable,
    Iterator,
    List,
    Optional,
    Set,
    Tuple,
)


# ============================================================
# TYPE DEFINITIONS
# ============================================================

Point = Tuple[int, int]


# ============================================================
# RESULT DATA STRUCTURES
# ============================================================

@dataclass(frozen=True)
class SearchStats:
    """
    Diagnostic information about the BFS search.
    """

    expanded_nodes: int
    discovered_nodes: int
    maximum_queue_size: int


@dataclass
class MazeResult:
    """
    Complete result produced by the maze solver.
    """

    found: bool
    moves: int
    path: List[Point]
    stats: SearchStats


# ============================================================
# MAZE SOLVER
# ============================================================

class SlidingMazeSolver:
    """
    Finds a minimum-move path through a rectangular grid.

    Movement behaves like a chess rook:
    each action may move any unobstructed distance horizontally
    or vertically.

    Because every slide costs exactly one move, Breadth-First
    Search guarantees the minimum number of moves.
    """

    DIRECTIONS: Tuple[Point, ...] = (
        (-1, 0),   # up
        (1, 0),    # down
        (0, -1),   # left
        (0, 1),    # right
    )

    DIRECTION_NAMES = {
        (-1, 0): "UP",
        (1, 0): "DOWN",
        (0, -1): "LEFT",
        (0, 1): "RIGHT",
    }

    def __init__(
        self,
        rows: int,
        columns: int,
        blocked: Iterable[Point] = (),
    ) -> None:

        if rows <= 0:
            raise ValueError("rows must be greater than zero.")

        if columns <= 0:
            raise ValueError("columns must be greater than zero.")

        self.rows = rows
        self.columns = columns

        # Set gives average O(1) membership checks.
        self.blocked: Set[Point] = set(blocked)

        self._validate_obstacles()

    # ========================================================
    # VALIDATION
    # ========================================================

    def in_bounds(self, point: Point) -> bool:
        """Return True when a coordinate lies inside the board."""

        row, column = point

        return (
            0 <= row < self.rows
            and 0 <= column < self.columns
        )

    def _validate_obstacles(self) -> None:
        """Make sure every obstacle is actually inside the board."""

        invalid = [
            point
            for point in self.blocked
            if not self.in_bounds(point)
        ]

        if invalid:
            raise ValueError(
                "Obstacle coordinates outside board: "
                + ", ".join(map(str, invalid))
            )

    def _validate_endpoint(
        self,
        point: Point,
        name: str,
    ) -> None:

        if not self.in_bounds(point):
            raise ValueError(
                f"{name} position {point} is outside the board."
            )

        if point in self.blocked:
            raise ValueError(
                f"{name} position {point} is occupied by an obstacle."
            )

    # ========================================================
    # MOVEMENT GENERATOR
    # ========================================================

    def neighbours(
        self,
        point: Point,
    ) -> Iterator[Point]:
        """
        Generate every square reachable from `point`
        using exactly ONE sliding move.

        Example:

            . . .
            . S .
            . . .

        S can reach every square in the same row and column.
        """

        row, column = point

        for delta_row, delta_column in self.DIRECTIONS:

            new_row = row + delta_row
            new_column = column + delta_column

            while (
                0 <= new_row < self.rows
                and 0 <= new_column < self.columns
            ):

                candidate = (
                    new_row,
                    new_column,
                )

                # Obstacles terminate movement in this direction.
                if candidate in self.blocked:
                    break

                yield candidate

                new_row += delta_row
                new_column += delta_column

    # ========================================================
    # SHORTEST PATH SEARCH
    # ========================================================

    def solve(
        self,
        start: Point,
        end: Point,
    ) -> MazeResult:
        """
        Find the minimum number of sliding moves required to
        travel from start to end.
        """

        self._validate_endpoint(start, "Start")
        self._validate_endpoint(end, "End")

        # Start and destination are identical.
        if start == end:
            return MazeResult(
                found=True,
                moves=0,
                path=[start],
                stats=SearchStats(
                    expanded_nodes=0,
                    discovered_nodes=1,
                    maximum_queue_size=1,
                ),
            )

        # ----------------------------------------------------
        # BFS structures
        # ----------------------------------------------------

        queue: Deque[Point] = deque([start])

        # IMPORTANT:
        # Mark nodes when they enter the queue rather than when
        # they leave it. This prevents duplicate queue entries.
        discovered: Set[Point] = {start}

        parent: Dict[Point, Optional[Point]] = {
            start: None
        }

        distance: Dict[Point, int] = {
            start: 0
        }

        expanded_nodes = 0
        maximum_queue_size = 1

        # ----------------------------------------------------
        # Breadth-first search
        # ----------------------------------------------------

        while queue:

            current = queue.popleft()

            expanded_nodes += 1

            current_distance = distance[current]

            for neighbour in self.neighbours(current):

                if neighbour in discovered:
                    continue

                discovered.add(neighbour)

                parent[neighbour] = current

                distance[neighbour] = (
                    current_distance + 1
                )

                # --------------------------------------------
                # Destination found
                # --------------------------------------------

                if neighbour == end:

                    path = self._reconstruct_path(
                        parent,
                        end,
                    )

                    stats = SearchStats(
                        expanded_nodes=expanded_nodes,
                        discovered_nodes=len(discovered),
                        maximum_queue_size=max(
                            maximum_queue_size,
                            len(queue) + 1,
                        ),
                    )

                    return MazeResult(
                        found=True,
                        moves=distance[end],
                        path=path,
                        stats=stats,
                    )

                queue.append(neighbour)

                maximum_queue_size = max(
                    maximum_queue_size,
                    len(queue),
                )

        # ----------------------------------------------------
        # No solution
        # ----------------------------------------------------

        stats = SearchStats(
            expanded_nodes=expanded_nodes,
            discovered_nodes=len(discovered),
            maximum_queue_size=maximum_queue_size,
        )

        return MazeResult(
            found=False,
            moves=-1,
            path=[],
            stats=stats,
        )

    # ========================================================
    # PATH RECONSTRUCTION
    # ========================================================

    @staticmethod
    def _reconstruct_path(
        parent: Dict[Point, Optional[Point]],
        end: Point,
    ) -> List[Point]:
        """
        Follow parent references backwards from the destination.
        """

        path: List[Point] = []

        node: Optional[Point] = end

        while node is not None:

            path.append(node)

            node = parent[node]

        path.reverse()

        return path

    # ========================================================
    # EXPAND PATH INTO ALL CELLS TRAVERSED
    # ========================================================

    @staticmethod
    def expanded_path_cells(
        path: List[Point],
    ) -> Set[Point]:
        """
        Convert slide endpoints into every cell actually crossed.

        Example:

            (0,0) -> (0,4)

        becomes:

            (0,1)
            (0,2)
            (0,3)
        """

        cells: Set[Point] = set()

        for start, end in zip(
            path,
            path[1:],
        ):

            start_row, start_column = start
            end_row, end_column = end

            # Horizontal movement
            if start_row == end_row:

                step = (
                    1
                    if end_column > start_column
                    else -1
                )

                for column in range(
                    start_column + step,
                    end_column,
                    step,
                ):

                    cells.add(
                        (
                            start_row,
                            column,
                        )
                    )

            # Vertical movement
            elif start_column == end_column:

                step = (
                    1
                    if end_row > start_row
                    else -1
                )

                for row in range(
                    start_row + step,
                    end_row,
                    step,
                ):

                    cells.add(
                        (
                            row,
                            start_column,
                        )
                    )

            else:
                raise ValueError(
                    "Invalid path: diagonal movement detected."
                )

        return cells

    # ========================================================
    # DIRECTION DESCRIPTION
    # ========================================================

    @staticmethod
    def describe_move(
        start: Point,
        end: Point,
    ) -> Tuple[str, int]:

        start_row, start_column = start
        end_row, end_column = end

        delta_row = end_row - start_row
        delta_column = end_column - start_column

        if delta_row < 0 and delta_column == 0:
            return "UP", abs(delta_row)

        if delta_row > 0 and delta_column == 0:
            return "DOWN", delta_row

        if delta_column < 0 and delta_row == 0:
            return "LEFT", abs(delta_column)

        if delta_column > 0 and delta_row == 0:
            return "RIGHT", delta_column

        raise ValueError(
            f"Invalid slide from {start} to {end}"
        )

    # ========================================================
    # PRINT MOVE INSTRUCTIONS
    # ========================================================

    def path_instructions(
        self,
        path: List[Point],
    ) -> str:

        if not path:
            return "No route."

        if len(path) == 1:
            return "Already at destination."

        lines: List[str] = []

        for move_number, (
            current,
            target,
        ) in enumerate(
            zip(path, path[1:]),
            start=1,
        ):

            direction, distance = self.describe_move(
                current,
                target,
            )

            cell_word = (
                "cell"
                if distance == 1
                else "cells"
            )

            lines.append(
                f"{move_number:>2}. "
                f"{current} -> {target}   "
                f"{direction:<5} "
                f"{distance} {cell_word}"
            )

        return "\n".join(lines)

    # ========================================================
    # BOARD RENDERING
    # ========================================================

    def render(
        self,
        start: Point,
        end: Point,
        path: Optional[List[Point]] = None,
    ) -> str:
        """
        Render the board using:

            S = start
            E = end
            X = obstacle
            ● = slide stopping point
            · = traversed square
            . = unused square
        """

        board = [
            [
                "."
                for _ in range(self.columns)
            ]
            for _ in range(self.rows)
        ]

        # Obstacles
        for row, column in self.blocked:
            board[row][column] = "X"

        # Path
        if path:

            traversed = self.expanded_path_cells(
                path
            )

            stopping_points = set(
                path[1:-1]
            )

            # Cells passed through
            for row, column in traversed:

                if (
                    row,
                    column,
                ) not in self.blocked:

                    board[row][column] = "·"

            # Cells where the player actually stops.
            for row, column in stopping_points:

                board[row][column] = "●"

        start_row, start_column = start
        end_row, end_column = end

        board[start_row][start_column] = "S"
        board[end_row][end_column] = "E"

        # ----------------------------------------------------
        # Column numbers
        # ----------------------------------------------------

        output: List[str] = []

        header = (
            "     "
            + " ".join(
                f"{column:>2}"
                for column in range(self.columns)
            )
        )

        output.append(header)

        output.append(
            "   +"
            + "---" * self.columns
            + "+"
        )

        # ----------------------------------------------------
        # Grid
        # ----------------------------------------------------

        for row_number, row in enumerate(board):

            rendered_row = " ".join(
                f"{cell:>2}"
                for cell in row
            )

            output.append(
                f"{row_number:>2} |"
                + rendered_row
                + " |"
            )

        output.append(
            "   +"
            + "---" * self.columns
            + "+"
        )

        return "\n".join(output)


# ============================================================
# OPTIONAL SELF TESTS
# ============================================================

def run_self_tests() -> None:
    """
    Small internal tests to catch accidental algorithm changes.
    """

    # --------------------------------------------------------
    # Test 1: direct horizontal route
    # --------------------------------------------------------

    solver = SlidingMazeSolver(
        rows=4,
        columns=4,
    )

    result = solver.solve(
        (0, 0),
        (0, 3),
    )

    assert result.found
    assert result.moves == 1

    # --------------------------------------------------------
    # Test 2: one turn
    # --------------------------------------------------------

    result = solver.solve(
        (0, 0),
        (3, 3),
    )

    assert result.found
    assert result.moves == 2

    # --------------------------------------------------------
    # Test 3: start == end
    # --------------------------------------------------------

    result = solver.solve(
        (2, 2),
        (2, 2),
    )

    assert result.found
    assert result.moves == 0

    # --------------------------------------------------------
    # Test 4: enclosed destination
    # --------------------------------------------------------

    enclosed_solver = SlidingMazeSolver(
        rows=3,
        columns=3,
        blocked={
            (0, 1),
            (1, 0),
            (1, 2),
            (2, 1),
        },
    )

    result = enclosed_solver.solve(
        (0, 0),
        (1, 1),
    )

    assert not result.found

    print("Self-tests: PASSED")


# ============================================================
# MAIN DEMONSTRATION
# ============================================================

def main() -> None:

    # --------------------------------------------------------
    # YOUR MAZE SETTINGS
    # --------------------------------------------------------

    ROWS = 8
    COLUMNS = 8

    START: Point = (
        0,
        0,
    )

    END: Point = (
        7,
        7,
    )

    TAKEN: Set[Point] = {
        (1, 0),
        (1, 1),
        (1, 2),
        (1, 3),
    }

    # --------------------------------------------------------
    # CREATE SOLVER
    # --------------------------------------------------------

    solver = SlidingMazeSolver(
        rows=ROWS,
        columns=COLUMNS,
        blocked=TAKEN,
    )

    # --------------------------------------------------------
    # RUN SHORTEST-PATH SEARCH
    # --------------------------------------------------------

    result = solver.solve(
        START,
        END,
    )

    # --------------------------------------------------------
    # ORIGINAL MAZE
    # --------------------------------------------------------

    print()
    print("=" * 64)
    print(" SLIDING MAZE SHORTEST-PATH SOLVER")
    print("=" * 64)

    print()
    print("Original maze:")
    print()

    print(
        solver.render(
            START,
            END,
        )
    )

    # --------------------------------------------------------
    # RESULT
    # --------------------------------------------------------

    print()
    print("=" * 64)

    if not result.found:

        print("NO ROUTE FOUND")

        print()
        print(
            "The destination cannot be reached "
            "from the starting position."
        )

    else:

        print("SHORTEST ROUTE FOUND")

        print()
        print(
            f"Minimum moves : {result.moves}"
        )

        print(
            f"Path          : "
            + " -> ".join(
                map(str, result.path)
            )
        )

        # ----------------------------------------------------
        # ROUTE BOARD
        # ----------------------------------------------------

        print()
        print("Visual route:")
        print()

        print(
            solver.render(
                START,
                END,
                result.path,
            )
        )

        # ----------------------------------------------------
        # MOVE INSTRUCTIONS
        # ----------------------------------------------------

        print()
        print("Move-by-move instructions:")
        print()

        print(
            solver.path_instructions(
                result.path
            )
        )

    # --------------------------------------------------------
    # ALGORITHM STATISTICS
    # --------------------------------------------------------

    print()
    print("=" * 64)
    print("SEARCH STATISTICS")
    print("=" * 64)

    print(
        f"Expanded nodes    : "
        f"{result.stats.expanded_nodes}"
    )

    print(
        f"Discovered nodes  : "
        f"{result.stats.discovered_nodes}"
    )

    print(
        f"Maximum queue size: "
        f"{result.stats.maximum_queue_size}"
    )

    print()

    print(
        "Legend: "
        "S=start, "
        "E=end, "
        "X=obstacle, "
        "●=slide endpoint, "
        "·=travelled cell"
    )

    print()


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    # Uncomment this if you want the internal tests
    # to run before the demonstration.
    #
    # run_self_tests()

    main()
