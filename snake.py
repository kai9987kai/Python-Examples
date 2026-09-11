"""
ADVANCED TERMINAL SNAKE
=======================

An expanded and modernised version of the classic curses Snake game.

FEATURES
--------
- Proper curses.wrapper() cleanup
- Dynamic terminal-sized board
- Four difficulty modes
- Arrow keys + WASD controls
- Pause / resume
- Restart without closing the program
- Persistent high score
- Progressive speed system
- Level system
- Obstacles
- Golden bonus food
- Wraparound / solid-wall modes
- Runtime wrap toggle
- Colour support
- Prevents instant 180-degree turns
- Safe random food/obstacle placement
- Game-over and victory screens
- Terminal-size validation
- Cross-platform high-score file
- Object-oriented architecture

CONTROLS
--------
Arrow Keys / WASD : Move
SPACE / P          : Pause
T                  : Toggle wraparound
R                  : Restart
M                  : Return to menu
Q / ESC            : Quit

WINDOWS
-------
Python's curses module is normally included on Linux/macOS.

On Windows install:

    py -m pip install windows-curses

Then run:

    py advanced_snake.py
"""

from __future__ import annotations

import curses
import json
import random
import time

from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Deque, Optional


# ============================================================
# CONFIGURATION
# ============================================================

GAME_TITLE = "ADVANCED SNAKE"

MIN_TERMINAL_WIDTH = 45
MIN_TERMINAL_HEIGHT = 18

MAX_BOARD_WIDTH = 80
MAX_BOARD_HEIGHT = 26

HIGH_SCORE_FILE = Path.home() / ".advanced_snake_highscore.json"

NORMAL_FOOD = "*"
BONUS_FOOD = "$"

HEAD_CHARACTER = "@"
BODY_CHARACTER = "O"
TAIL_CHARACTER = "o"

OBSTACLE_CHARACTER = "X"

BONUS_FOOD_CHANCE = 0.16
BONUS_FOOD_LIFETIME = 6.0

NORMAL_FOOD_POINTS = 1
BONUS_FOOD_POINTS = 3


# ============================================================
# DIRECTIONS
# ============================================================

UP = (-1, 0)
DOWN = (1, 0)
LEFT = (0, -1)
RIGHT = (0, 1)

OPPOSITE = {
    UP: DOWN,
    DOWN: UP,
    LEFT: RIGHT,
    RIGHT: LEFT,
}


# ============================================================
# DIFFICULTY CONFIGURATION
# ============================================================

@dataclass(frozen=True)
class Difficulty:
    name: str
    base_delay: int
    minimum_delay: int
    acceleration: float
    obstacles: bool
    obstacle_interval: int
    wraparound: bool


DIFFICULTIES = {
    1: Difficulty(
        name="EASY",
        base_delay=165,
        minimum_delay=90,
        acceleration=1.3,
        obstacles=False,
        obstacle_interval=999,
        wraparound=True,
    ),
    2: Difficulty(
        name="NORMAL",
        base_delay=130,
        minimum_delay=60,
        acceleration=1.8,
        obstacles=True,
        obstacle_interval=6,
        wraparound=True,
    ),
    3: Difficulty(
        name="HARD",
        base_delay=100,
        minimum_delay=42,
        acceleration=2.2,
        obstacles=True,
        obstacle_interval=5,
        wraparound=False,
    ),
    4: Difficulty(
        name="INSANE",
        base_delay=75,
        minimum_delay=28,
        acceleration=2.7,
        obstacles=True,
        obstacle_interval=3,
        wraparound=False,
    ),
}


# ============================================================
# FOOD
# ============================================================

@dataclass
class Food:
    position: tuple[int, int]
    bonus: bool = False
    created_at: float = 0.0

    @property
    def glyph(self) -> str:
        return BONUS_FOOD if self.bonus else NORMAL_FOOD

    @property
    def points(self) -> int:
        return BONUS_FOOD_POINTS if self.bonus else NORMAL_FOOD_POINTS


# ============================================================
# PERSISTENT HIGH SCORE
# ============================================================

class HighScoreManager:

    def __init__(self, path: Path):
        self.path = path
        self.high_score = self.load()

    def load(self) -> int:
        try:
            if not self.path.exists():
                return 0

            with self.path.open("r", encoding="utf-8") as file:
                data = json.load(file)

            return max(0, int(data.get("high_score", 0)))

        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return 0

    def update(self, score: int) -> bool:
        if score <= self.high_score:
            return False

        self.high_score = score
        self.save()

        return True

    def save(self) -> None:
        try:
            temporary_path = self.path.with_suffix(".tmp")

            with temporary_path.open("w", encoding="utf-8") as file:
                json.dump(
                    {
                        "high_score": self.high_score,
                        "updated": time.time(),
                    },
                    file,
                    indent=4,
                )

            temporary_path.replace(self.path)

        except OSError:
            # High-score saving should never crash the game.
            pass


# ============================================================
# SNAKE GAME ENGINE
# ============================================================

class SnakeGame:

    def __init__(
        self,
        stdscr,
        difficulty: Difficulty,
        high_scores: HighScoreManager,
    ):
        self.stdscr = stdscr
        self.difficulty = difficulty
        self.high_scores = high_scores

        terminal_height, terminal_width = stdscr.getmaxyx()

        self.height = min(
            MAX_BOARD_HEIGHT,
            terminal_height - 2,
        )

        self.width = min(
            MAX_BOARD_WIDTH,
            terminal_width - 2,
        )

        self.start_y = max(
            0,
            (terminal_height - self.height) // 2,
        )

        self.start_x = max(
            0,
            (terminal_width - self.width) // 2,
        )

        self.window = curses.newwin(
            self.height,
            self.width,
            self.start_y,
            self.start_x,
        )

        self.window.keypad(True)
        self.window.nodelay(False)

        self.score = 0
        self.food_eaten = 0

        self.direction = RIGHT
        self.next_direction = RIGHT

        self.wraparound = difficulty.wraparound

        self.game_over = False
        self.won = False

        self.obstacles: set[tuple[int, int]] = set()

        self.next_obstacle_score = difficulty.obstacle_interval

        self.snake: Deque[tuple[int, int]] = deque()

        self.food: Optional[Food] = None

        self.create_initial_snake()
        self.spawn_food()

    # ========================================================
    # INITIAL STATE
    # ========================================================

    def create_initial_snake(self) -> None:

        center_y = self.height // 2
        center_x = self.width // 2

        self.snake.clear()

        self.snake.append((center_y, center_x))
        self.snake.append((center_y, center_x - 1))
        self.snake.append((center_y, center_x - 2))
        self.snake.append((center_y, center_x - 3))

    # ========================================================
    # BOARD UTILITIES
    # ========================================================

    def is_inside_play_area(
        self,
        y: int,
        x: int,
    ) -> bool:

        return (
            1 <= y <= self.height - 2
            and
            1 <= x <= self.width - 2
        )

    def get_empty_cells(self) -> list[tuple[int, int]]:

        occupied = set(self.snake)
        occupied.update(self.obstacles)

        if self.food:
            occupied.add(self.food.position)

        empty_cells = []

        for y in range(1, self.height - 1):

            for x in range(1, self.width - 1):

                position = (y, x)

                if position not in occupied:
                    empty_cells.append(position)

        return empty_cells

    def random_empty_position(
        self,
    ) -> Optional[tuple[int, int]]:

        empty_cells = self.get_empty_cells()

        if not empty_cells:
            return None

        return random.choice(empty_cells)

    # ========================================================
    # FOOD
    # ========================================================

    def spawn_food(self) -> None:

        position = self.random_empty_position()

        if position is None:
            self.won = True
            self.game_over = True
            return

        bonus = random.random() < BONUS_FOOD_CHANCE

        self.food = Food(
            position=position,
            bonus=bonus,
            created_at=time.monotonic(),
        )

    def update_bonus_food(self) -> None:

        if self.food is None:
            return

        if not self.food.bonus:
            return

        age = time.monotonic() - self.food.created_at

        if age >= BONUS_FOOD_LIFETIME:
            self.food = None
            self.spawn_food()

    # ========================================================
    # OBSTACLES
    # ========================================================

    def add_obstacle(self) -> None:

        if not self.difficulty.obstacles:
            return

        head_y, head_x = self.snake[0]

        possible_positions = []

        for y in range(1, self.height - 1):

            for x in range(1, self.width - 1):

                position = (y, x)

                if position in self.snake:
                    continue

                if position in self.obstacles:
                    continue

                if self.food and position == self.food.position:
                    continue

                # Avoid spawning an obstacle immediately beside
                # the snake head.
                distance = (
                    abs(y - head_y)
                    +
                    abs(x - head_x)
                )

                if distance < 5:
                    continue

                possible_positions.append(position)

        if possible_positions:
            self.obstacles.add(
                random.choice(possible_positions)
            )

    def update_obstacles(self) -> None:

        if not self.difficulty.obstacles:
            return

        while self.score >= self.next_obstacle_score:

            self.add_obstacle()

            self.next_obstacle_score += (
                self.difficulty.obstacle_interval
            )

    # ========================================================
    # SPEED
    # ========================================================

    @property
    def level(self) -> int:

        return 1 + self.score // 5

    @property
    def delay(self) -> int:

        calculated_delay = (
            self.difficulty.base_delay
            -
            int(
                self.score
                *
                self.difficulty.acceleration
            )
        )

        return max(
            self.difficulty.minimum_delay,
            calculated_delay,
        )

    # ========================================================
    # INPUT
    # ========================================================

    def handle_input(
        self,
        key: int,
    ) -> Optional[str]:

        key_mapping = {

            curses.KEY_UP: UP,
            curses.KEY_DOWN: DOWN,
            curses.KEY_LEFT: LEFT,
            curses.KEY_RIGHT: RIGHT,

            ord("w"): UP,
            ord("W"): UP,

            ord("s"): DOWN,
            ord("S"): DOWN,

            ord("a"): LEFT,
            ord("A"): LEFT,

            ord("d"): RIGHT,
            ord("D"): RIGHT,
        }

        if key in key_mapping:

            requested_direction = key_mapping[key]

            # Prevent instant 180-degree turns.
            if requested_direction != OPPOSITE[self.direction]:
                self.next_direction = requested_direction

            return None

        if key in (
            ord(" "),
            ord("p"),
            ord("P"),
        ):
            self.pause()
            return None

        if key in (
            ord("t"),
            ord("T"),
        ):
            self.wraparound = not self.wraparound
            return None

        if key in (
            ord("r"),
            ord("R"),
        ):
            return "restart"

        if key in (
            ord("m"),
            ord("M"),
        ):
            return "menu"

        if key in (
            ord("q"),
            ord("Q"),
            27,
        ):
            return "quit"

        return None

    # ========================================================
    # MOVEMENT
    # ========================================================

    def calculate_next_head(
        self,
    ) -> Optional[tuple[int, int]]:

        self.direction = self.next_direction

        head_y, head_x = self.snake[0]

        dy, dx = self.direction

        new_y = head_y + dy
        new_x = head_x + dx

        if self.wraparound:

            if new_y <= 0:
                new_y = self.height - 2

            elif new_y >= self.height - 1:
                new_y = 1

            if new_x <= 0:
                new_x = self.width - 2

            elif new_x >= self.width - 1:
                new_x = 1

        else:

            if not self.is_inside_play_area(
                new_y,
                new_x,
            ):
                return None

        return new_y, new_x

    def update(self) -> None:

        self.update_bonus_food()

        next_head = self.calculate_next_head()

        # Wall collision.
        if next_head is None:
            self.game_over = True
            return

        eating = (
            self.food is not None
            and
            next_head == self.food.position
        )

        # When the snake isn't growing, moving onto the current
        # tail position is technically legal because that tail
        # segment disappears during this frame.
        body_collision_check = list(self.snake)

        if not eating:
            body_collision_check = body_collision_check[:-1]

        if next_head in body_collision_check:
            self.game_over = True
            return

        if next_head in self.obstacles:
            self.game_over = True
            return

        self.snake.appendleft(next_head)

        if eating:

            points = self.food.points

            self.score += points
            self.food_eaten += 1

            self.food = None

            self.high_scores.update(self.score)

            self.update_obstacles()
            self.spawn_food()

        else:
            self.snake.pop()

    # ========================================================
    # COLOUR HELPERS
    # ========================================================

    @staticmethod
    def attr(pair_number: int) -> int:

        if curses.has_colors():
            return curses.color_pair(pair_number)

        return 0

    # ========================================================
    # DRAWING
    # ========================================================

    def draw(self) -> None:

        self.window.erase()
        self.window.box()

        self.draw_status()
        self.draw_obstacles()
        self.draw_food()
        self.draw_snake()

        self.window.refresh()

    def draw_status(self) -> None:

        wrap_text = (
            "WRAP"
            if self.wraparound
            else "WALL"
        )

        status = (
            f" {GAME_TITLE} | "
            f"Score:{self.score} "
            f"High:{self.high_scores.high_score} "
            f"Level:{self.level} "
            f"{self.difficulty.name} "
            f"{wrap_text} "
        )

        try:

            self.window.addnstr(
                0,
                2,
                status,
                max(1, self.width - 4),
                curses.A_BOLD,
            )

        except curses.error:
            pass

    def draw_snake(self) -> None:

        snake_list = list(self.snake)

        for index, (y, x) in enumerate(snake_list):

            if index == 0:

                character = HEAD_CHARACTER

                attribute = (
                    self.attr(1)
                    |
                    curses.A_BOLD
                )

            elif index == len(snake_list) - 1:

                character = TAIL_CHARACTER
                attribute = self.attr(2)

            else:

                character = BODY_CHARACTER
                attribute = self.attr(2)

            try:
                self.window.addch(
                    y,
                    x,
                    character,
                    attribute,
                )

            except curses.error:
                pass

    def draw_food(self) -> None:

        if self.food is None:
            return

        y, x = self.food.position

        if self.food.bonus:

            attribute = (
                self.attr(4)
                |
                curses.A_BOLD
                |
                curses.A_BLINK
            )

        else:

            attribute = (
                self.attr(3)
                |
                curses.A_BOLD
            )

        try:

            self.window.addch(
                y,
                x,
                self.food.glyph,
                attribute,
            )

        except curses.error:
            pass

    def draw_obstacles(self) -> None:

        attribute = (
            self.attr(5)
            |
            curses.A_BOLD
        )

        for y, x in self.obstacles:

            try:

                self.window.addch(
                    y,
                    x,
                    OBSTACLE_CHARACTER,
                    attribute,
                )

            except curses.error:
                pass

    # ========================================================
    # PAUSE
    # ========================================================

    def pause(self) -> None:

        self.window.nodelay(False)
        self.window.timeout(-1)

        message = " PAUSED - SPACE/P TO RESUME "

        y = self.height // 2
        x = max(
            1,
            (self.width - len(message)) // 2,
        )

        try:

            self.window.addnstr(
                y,
                x,
                message,
                self.width - 2,
                curses.A_REVERSE
                |
                curses.A_BOLD,
            )

        except curses.error:
            pass

        self.window.refresh()

        while True:

            key = self.window.getch()

            if key in (
                ord(" "),
                ord("p"),
                ord("P"),
            ):
                break

            if key in (
                ord("q"),
                ord("Q"),
                27,
            ):
                self.game_over = True
                break

    # ========================================================
    # END SCREEN
    # ========================================================

    def show_end_screen(self) -> str:

        self.high_scores.update(self.score)

        self.window.timeout(-1)

        if self.won:
            title = "YOU COMPLETED THE BOARD!"
        else:
            title = "GAME OVER"

        lines = [
            "",
            title,
            "",
            f"Final score : {self.score}",
            f"High score  : {self.high_scores.high_score}",
            f"Food eaten  : {self.food_eaten}",
            f"Snake length: {len(self.snake)}",
            f"Level       : {self.level}",
            "",
            "[R] Restart",
            "[M] Main Menu",
            "[Q] Quit",
        ]

        self.window.erase()
        self.window.box()

        center_y = (
            self.height // 2
            -
            len(lines) // 2
        )

        for index, text in enumerate(lines):

            y = center_y + index

            x = max(
                1,
                (self.width - len(text)) // 2,
            )

            if text in (
                "GAME OVER",
                "YOU COMPLETED THE BOARD!",
            ):

                attribute = (
                    self.attr(3)
                    |
                    curses.A_BOLD
                )

            else:

                attribute = 0

            try:

                self.window.addnstr(
                    y,
                    x,
                    text,
                    self.width - 2,
                    attribute,
                )

            except curses.error:
                pass

        self.window.refresh()

        while True:

            key = self.window.getch()

            if key in (
                ord("r"),
                ord("R"),
            ):
                return "restart"

            if key in (
                ord("m"),
                ord("M"),
            ):
                return "menu"

            if key in (
                ord("q"),
                ord("Q"),
                27,
            ):
                return "quit"

    # ========================================================
    # MAIN GAME LOOP
    # ========================================================

    def run(self) -> str:

        while not self.game_over:

            self.draw()

            self.window.timeout(
                self.delay
            )

            key = self.window.getch()

            action = self.handle_input(key)

            if action is not None:
                return action

            self.update()

        return self.show_end_screen()


# ============================================================
# CURSES INITIALISATION
# ============================================================

def initialise_curses(stdscr) -> None:

    curses.noecho()
    curses.cbreak()

    try:
        curses.curs_set(0)
    except curses.error:
        pass

    stdscr.keypad(True)

    if curses.has_colors():

        curses.start_color()

        try:
            curses.use_default_colors()
        except curses.error:
            pass

        # Head
        curses.init_pair(
            1,
            curses.COLOR_CYAN,
            -1,
        )

        # Body
        curses.init_pair(
            2,
            curses.COLOR_GREEN,
            -1,
        )

        # Food
        curses.init_pair(
            3,
            curses.COLOR_RED,
            -1,
        )

        # Bonus food
        curses.init_pair(
            4,
            curses.COLOR_YELLOW,
            -1,
        )

        # Obstacles
        curses.init_pair(
            5,
            curses.COLOR_MAGENTA,
            -1,
        )


# ============================================================
# TERMINAL SIZE CHECK
# ============================================================

def terminal_large_enough(
    stdscr,
) -> bool:

    height, width = stdscr.getmaxyx()

    return (
        width >= MIN_TERMINAL_WIDTH
        and
        height >= MIN_TERMINAL_HEIGHT
    )


def show_terminal_error(stdscr) -> None:

    while True:

        stdscr.erase()

        height, width = stdscr.getmaxyx()

        lines = [
            "Terminal is too small.",
            "",
            f"Current : {width} x {height}",
            (
                "Minimum : "
                f"{MIN_TERMINAL_WIDTH} x "
                f"{MIN_TERMINAL_HEIGHT}"
            ),
            "",
            "Enlarge the terminal window.",
            "",
            "Press Q or ESC to quit.",
        ]

        start_y = max(
            0,
            height // 2
            -
            len(lines) // 2,
        )

        for index, text in enumerate(lines):

            y = start_y + index

            x = max(
                0,
                (width - len(text)) // 2,
            )

            try:

                stdscr.addnstr(
                    y,
                    x,
                    text,
                    max(1, width - 1),
                )

            except curses.error:
                pass

        stdscr.refresh()

        stdscr.timeout(300)

        key = stdscr.getch()

        if key in (
            ord("q"),
            ord("Q"),
            27,
        ):
            return

        if terminal_large_enough(stdscr):
            return


# ============================================================
# MAIN MENU
# ============================================================

def show_main_menu(
    stdscr,
    high_score: int,
) -> Optional[Difficulty]:

    stdscr.timeout(-1)

    while True:

        stdscr.erase()

        height, width = stdscr.getmaxyx()

        title = r"""
   _____ _   _          _  ________
  / ____| \ | |   /\   | |/ /  ____|
 | (___ |  \| |  /  \  | ' /| |__
  \___ \| . ` | / /\ \ |  < |  __|
  ____) | |\  |/ ____ \| . \| |____
 |_____/|_| \_/_/    \_\_|\_\______|
"""

        title_lines = title.strip("\n").splitlines()

        menu_lines = [
            "",
            "ADVANCED TERMINAL EDITION",
            "",
            f"High Score: {high_score}",
            "",
            "[1] EASY",
            "    Slower speed, wraparound, no obstacles",
            "",
            "[2] NORMAL",
            "    Progressive speed, wraparound, obstacles",
            "",
            "[3] HARD",
            "    Faster, solid walls, more obstacles",
            "",
            "[4] INSANE",
            "    Extreme speed and obstacle density",
            "",
            "Arrow Keys / WASD = Move",
            "SPACE / P          = Pause",
            "T                  = Toggle wraparound",
            "R                  = Restart",
            "M                  = Menu",
            "Q / ESC            = Quit",
            "",
            "* = normal food",
            "$ = bonus food (+3 points)",
            "X = obstacle",
            "",
            "Select difficulty: 1-4",
        ]

        total_height = (
            len(title_lines)
            +
            len(menu_lines)
        )

        start_y = max(
            0,
            (height - total_height) // 2,
        )

        current_y = start_y

        for line in title_lines:

            x = max(
                0,
                (width - len(line)) // 2,
            )

            try:

                stdscr.addnstr(
                    current_y,
                    x,
                    line,
                    max(1, width - 1),
                    curses.A_BOLD,
                )

            except curses.error:
                pass

            current_y += 1

        for line in menu_lines:

            x = max(
                0,
                (width - len(line)) // 2,
            )

            attribute = 0

            if line.startswith("["):
                attribute = curses.A_BOLD

            try:

                stdscr.addnstr(
                    current_y,
                    x,
                    line,
                    max(1, width - 1),
                    attribute,
                )

            except curses.error:
                pass

            current_y += 1

        stdscr.refresh()

        key = stdscr.getch()

        if key in (
            ord("1"),
            ord("2"),
            ord("3"),
            ord("4"),
        ):

            number = int(chr(key))

            return DIFFICULTIES[number]

        if key in (
            ord("q"),
            ord("Q"),
            27,
        ):
            return None


# ============================================================
# APPLICATION
# ============================================================

def main(stdscr) -> None:

    initialise_curses(stdscr)

    high_scores = HighScoreManager(
        HIGH_SCORE_FILE
    )

    if not terminal_large_enough(stdscr):

        show_terminal_error(stdscr)

        if not terminal_large_enough(stdscr):
            return

    while True:

        difficulty = show_main_menu(
            stdscr,
            high_scores.high_score,
        )

        if difficulty is None:
            break

        while True:

            game = SnakeGame(
                stdscr,
                difficulty,
                high_scores,
            )

            result = game.run()

            if result == "restart":
                continue

            if result == "menu":
                break

            if result == "quit":
                return


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    try:

        curses.wrapper(main)

    except KeyboardInterrupt:

        print("\nSnake terminated by user.")

    except curses.error as error:

        print(
            "\nCurses encountered a terminal error:"
        )

        print(error)

        print(
            "\nTry enlarging your terminal window."
        )
