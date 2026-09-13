#!/usr/bin/env python3
"""
Advanced Conway's Game of Life
==============================

A modern, vectorized, interactive implementation of Conway's Game of Life.

Highlights
----------
- NumPy-vectorized evolution (no per-cell Python loop)
- Correct wrap/toroidal and fixed/dead boundary modes
- Generic Life-like rules in B/S notation (default: B3/S23)
- Deterministic random seeds
- Built-in classic patterns
- Cell-age visualization
- Interactive pause/step/edit/reset controls
- Population, births, deaths, density, generation and speed statistics
- Repeat-state / oscillator detection
- Headless simulation mode
- Benchmark mode
- PNG and NumPy snapshot export
- Backward-compatible positional canvas size

Examples
--------
    python game_of_life_advanced.py 120
    python game_of_life_advanced.py 200 --density 0.22 --seed 42
    python game_of_life_advanced.py 160 --pattern acorn
    python game_of_life_advanced.py 120 --boundary fixed
    python game_of_life_advanced.py 150 --rule B36/S23
    python game_of_life_advanced.py 500 --headless --max-generations 1000
    python game_of_life_advanced.py 600 --benchmark --benchmark-steps 500

Controls
--------
    Space       Pause/resume
    N / Right   Advance one generation
    R           Re-randomize
    C           Clear board
    G           Place a glider at centre
    P           Cycle through built-in patterns
    S           Save PNG snapshot
    A           Toggle cell-age visualization
    I           Toggle statistics overlay
    + / =       Increase simulation speed
    - / _       Decrease simulation speed
    Q / Esc     Quit
    Left click  Toggle a cell (best while paused)

Requirements
------------
    Python 3.10+
    numpy
    matplotlib
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
import time
from collections import OrderedDict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np


# ---------------------------------------------------------------------------
# Rules and patterns
# ---------------------------------------------------------------------------

RULE_RE = re.compile(r"^\s*B([0-8]*)\s*/\s*S([0-8]*)\s*$", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class LifeRule:
    """A Life-like cellular automaton rule in B/S notation."""

    birth: frozenset[int]
    survive: frozenset[int]
    notation: str

    @classmethod
    def parse(cls, text: str) -> "LifeRule":
        match = RULE_RE.match(text)
        if not match:
            raise ValueError(
                f"Invalid rule {text!r}. Expected B/S notation such as B3/S23."
            )

        birth = frozenset(int(x) for x in match.group(1))
        survive = frozenset(int(x) for x in match.group(2))
        notation = (
            "B" + "".join(str(x) for x in sorted(birth))
            + "/S" + "".join(str(x) for x in sorted(survive))
        )
        return cls(birth=birth, survive=survive, notation=notation)


def _pattern(rows: Sequence[str]) -> np.ndarray:
    """Create a uint8 pattern from strings using '.' and 'O'."""
    if not rows:
        raise ValueError("Pattern cannot be empty.")
    width = len(rows[0])
    if width == 0 or any(len(row) != width for row in rows):
        raise ValueError("Pattern rows must have equal non-zero width.")
    return np.array(
        [[1 if ch.upper() in {"O", "1", "X", "#"} else 0 for ch in row] for row in rows],
        dtype=np.uint8,
    )


PATTERNS: dict[str, np.ndarray] = {
    "glider": _pattern(
        [
            ".O.",
            "..O",
            "OOO",
        ]
    ),
    "blinker": _pattern(
        [
            "OOO",
        ]
    ),
    "beacon": _pattern(
        [
            "OO..",
            "OO..",
            "..OO",
            "..OO",
        ]
    ),
    "rpentomino": _pattern(
        [
            ".OO",
            "OO.",
            ".O.",
        ]
    ),
    "acorn": _pattern(
        [
            ".O.....",
            "...O...",
            "OO..OOO",
        ]
    ),
    "diehard": _pattern(
        [
            "......O.",
            "OO......",
            ".O...OOO",
        ]
    ),
    "lwss": _pattern(
        [
            ".OO.O",
            "OOOO.",
            "OOO..",
            ".OO..",
        ]
    ),
    "pulsar": _pattern(
        [
            "..OOO...OOO..",
            ".............",
            "O....O.O....O",
            "O....O.O....O",
            "O....O.O....O",
            "..OOO...OOO..",
            ".............",
            "..OOO...OOO..",
            "O....O.O....O",
            "O....O.O....O",
            "O....O.O....O",
            ".............",
            "..OOO...OOO..",
        ]
    ),
    "gosper": _pattern(
        [
            "........................O...........",
            "......................O.O...........",
            "............OO......OO............OO",
            "...........O...O....OO............OO",
            "OO........O.....O...OO..............",
            "OO........O...O.OO....O.O...........",
            "..........O.....O.......O...........",
            "...........O...O....................",
            "............OO......................",
        ]
    ),
}

PATTERN_NAMES = tuple(PATTERNS)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class StepStats:
    generation: int
    population: int
    births: int
    deaths: int
    density: float
    repeated_from: int | None = None
    period: int | None = None


class LifeEngine:
    """
    Vectorized Life-like cellular automaton engine.

    Board representation:
        uint8 ndarray, shape (height, width), values 0 or 1.

    Boundary modes:
        wrap  - toroidal world; opposite edges connect.
        fixed - outside the board is permanently dead.
    """

    def __init__(
        self,
        width: int,
        height: int | None = None,
        *,
        rule: str | LifeRule = "B3/S23",
        boundary: str = "wrap",
        seed: int | None = None,
        history_limit: int = 4096,
    ) -> None:
        if width < 3:
            raise ValueError("width must be at least 3")
        if height is None:
            height = width
        if height < 3:
            raise ValueError("height must be at least 3")
        if boundary not in {"wrap", "fixed"}:
            raise ValueError("boundary must be 'wrap' or 'fixed'")
        if history_limit < 0:
            raise ValueError("history_limit must be >= 0")

        self.width = int(width)
        self.height = int(height)
        self.rule = LifeRule.parse(rule) if isinstance(rule, str) else rule
        self.boundary = boundary
        self.rng = np.random.default_rng(seed)
        self.seed_value = seed
        self.history_limit = int(history_limit)

        self.board = np.zeros((self.height, self.width), dtype=np.uint8)
        self.age = np.zeros((self.height, self.width), dtype=np.uint32)

        self.generation = 0
        self.births = 0
        self.deaths = 0
        self._history: OrderedDict[bytes, int] = OrderedDict()
        self._last_repeat: tuple[int, int] | None = None
        self._remember_state()

    @property
    def population(self) -> int:
        return int(np.count_nonzero(self.board))

    @property
    def density(self) -> float:
        return self.population / self.board.size

    def clear(self) -> None:
        self.board.fill(0)
        self.age.fill(0)
        self._reset_generation_tracking()

    def randomize(self, density: float = 0.25) -> None:
        if not 0.0 <= density <= 1.0:
            raise ValueError("density must be between 0 and 1")
        self.board[:] = (self.rng.random(self.board.shape) < density).astype(np.uint8)
        self.age[:] = self.board
        self._reset_generation_tracking()

    def load_pattern(
        self,
        name: str,
        *,
        row: int | None = None,
        col: int | None = None,
        clear_first: bool = True,
    ) -> None:
        key = name.lower().replace("-", "").replace("_", "")
        aliases = {
            "r": "rpentomino",
            "rpentomino": "rpentomino",
            "lightweightspaceship": "lwss",
            "spaceship": "lwss",
            "gun": "gosper",
            "gosperglidergun": "gosper",
        }
        key = aliases.get(key, key)
        if key not in PATTERNS:
            raise ValueError(
                f"Unknown pattern {name!r}. Available: {', '.join(PATTERN_NAMES)}"
            )

        pat = PATTERNS[key]
        ph, pw = pat.shape
        if ph > self.height or pw > self.width:
            raise ValueError(
                f"Pattern {key!r} ({pw}x{ph}) does not fit board "
                f"({self.width}x{self.height})."
            )

        if row is None:
            row = (self.height - ph) // 2
        if col is None:
            col = (self.width - pw) // 2

        if not (0 <= row <= self.height - ph and 0 <= col <= self.width - pw):
            raise ValueError("Pattern placement lies outside the board.")

        if clear_first:
            self.board.fill(0)
            self.age.fill(0)

        view = self.board[row : row + ph, col : col + pw]
        view |= pat
        self.age[row : row + ph, col : col + pw] = np.maximum(
            self.age[row : row + ph, col : col + pw], pat
        )
        self._reset_generation_tracking()

    def toggle(self, row: int, col: int) -> None:
        if 0 <= row < self.height and 0 <= col < self.width:
            self.board[row, col] ^= 1
            self.age[row, col] = self.board[row, col]
            self._reset_generation_tracking()

    def neighbour_count(self) -> np.ndarray:
        """Return live-neighbour counts for every cell."""
        b = self.board

        if self.boundary == "wrap":
            # Eight toroidal shifts. uint8 is sufficient because max count is 8.
            n = (
                np.roll(b, 1, axis=0)
                + np.roll(b, -1, axis=0)
                + np.roll(b, 1, axis=1)
                + np.roll(b, -1, axis=1)
                + np.roll(np.roll(b, 1, axis=0), 1, axis=1)
                + np.roll(np.roll(b, 1, axis=0), -1, axis=1)
                + np.roll(np.roll(b, -1, axis=0), 1, axis=1)
                + np.roll(np.roll(b, -1, axis=0), -1, axis=1)
            )
            return n.astype(np.uint8, copy=False)

        # Fixed/dead boundary: pad once, then sum eight shifted views.
        p = np.pad(b, 1, mode="constant", constant_values=0)
        return (
            p[:-2, :-2]
            + p[:-2, 1:-1]
            + p[:-2, 2:]
            + p[1:-1, :-2]
            + p[1:-1, 2:]
            + p[2:, :-2]
            + p[2:, 1:-1]
            + p[2:, 2:]
        ).astype(np.uint8, copy=False)

    def step(self, steps: int = 1) -> StepStats:
        if steps < 1:
            raise ValueError("steps must be >= 1")

        stats: StepStats | None = None
        for _ in range(steps):
            neighbours = self.neighbour_count()
            alive = self.board.astype(bool, copy=False)

            birth_mask = (~alive) & np.isin(neighbours, tuple(self.rule.birth))
            survive_mask = alive & np.isin(neighbours, tuple(self.rule.survive))
            next_alive = birth_mask | survive_mask

            deaths_mask = alive & ~survive_mask
            births = int(np.count_nonzero(birth_mask))
            deaths = int(np.count_nonzero(deaths_mask))

            # Age is 1 on a newly born cell and increments while it survives.
            next_age = np.zeros_like(self.age)
            next_age[next_alive] = self.age[next_alive] + 1
            next_age[birth_mask] = 1

            self.board[:] = next_alive
            self.age[:] = next_age
            self.generation += 1
            self.births = births
            self.deaths = deaths

            repeated_from, period = self._remember_state()
            population = int(np.count_nonzero(self.board))
            stats = StepStats(
                generation=self.generation,
                population=population,
                births=births,
                deaths=deaths,
                density=population / self.board.size,
                repeated_from=repeated_from,
                period=period,
            )

        assert stats is not None
        return stats

    def snapshot_hash(self) -> bytes:
        """Compact deterministic state fingerprint for repeat detection."""
        h = hashlib.blake2b(digest_size=16)
        h.update(self.board.tobytes(order="C"))
        h.update(self.rule.notation.encode("ascii"))
        h.update(self.boundary.encode("ascii"))
        return h.digest()

    def _remember_state(self) -> tuple[int | None, int | None]:
        if self.history_limit == 0:
            return None, None

        digest = self.snapshot_hash()
        previous = self._history.get(digest)
        period = None if previous is None else self.generation - previous

        # Move/insert current state as the newest record.
        self._history[digest] = self.generation
        self._history.move_to_end(digest)

        while len(self._history) > self.history_limit:
            self._history.popitem(last=False)

        if previous is not None:
            self._last_repeat = (previous, period)
        return previous, period

    def _reset_generation_tracking(self) -> None:
        self.generation = 0
        self.births = 0
        self.deaths = 0
        self._history.clear()
        self._last_repeat = None
        self._remember_state()

    def save_npy(self, path: Path) -> Path:
        path = path.with_suffix(".npy")
        np.save(path, self.board)
        return path


# ---------------------------------------------------------------------------
# Interactive visualization
# ---------------------------------------------------------------------------

class LifeApp:
    """Matplotlib interactive front end."""

    def __init__(
        self,
        engine: LifeEngine,
        *,
        fps: float = 30.0,
        density: float = 0.25,
        start_paused: bool = False,
        show_grid: bool = False,
        show_age: bool = True,
        show_info: bool = True,
        max_generations: int | None = None,
        output_prefix: str = "life_snapshot",
    ) -> None:
        if fps <= 0:
            raise ValueError("fps must be > 0")

        self.engine = engine
        self.fps = float(fps)
        self.density = float(density)
        self.running = not start_paused
        self.show_grid = show_grid
        self.show_age = show_age
        self.show_info = show_info
        self.max_generations = max_generations
        self.output_prefix = output_prefix

        self._pattern_index = 0
        self._last_tick = time.perf_counter()
        self._step_times: deque[float] = deque(maxlen=120)
        self._animation = None

        self._setup_plot()

    def _setup_plot(self) -> None:
        import matplotlib.pyplot as plt
        from matplotlib.animation import FuncAnimation
        from matplotlib.colors import LinearSegmentedColormap

        self.plt = plt
        self.FuncAnimation = FuncAnimation

        self.fig, self.ax = plt.subplots(figsize=(9, 9))
        self.fig.canvas.manager.set_window_title("Advanced Conway's Game of Life")

        self.binary_cmap = LinearSegmentedColormap.from_list(
            "life_binary", ["#f7f7f7", "#101010"], N=2
        )
        self.age_cmap = plt.get_cmap("viridis")

        data = self._display_data()
        self.image = self.ax.imshow(
            data,
            interpolation="nearest",
            cmap=self.age_cmap if self.show_age else self.binary_cmap,
            vmin=0,
            vmax=self._display_vmax(),
            origin="upper",
            animated=True,
        )

        self.ax.set_xlim(-0.5, self.engine.width - 0.5)
        self.ax.set_ylim(self.engine.height - 0.5, -0.5)
        self.ax.set_aspect("equal")
        self.ax.set_xticks([])
        self.ax.set_yticks([])

        if self.show_grid and max(self.engine.width, self.engine.height) <= 120:
            self._apply_grid()

        self.info_text = self.ax.text(
            0.01,
            0.99,
            "",
            transform=self.ax.transAxes,
            va="top",
            ha="left",
            fontsize=9,
            family="monospace",
            bbox={"boxstyle": "round,pad=0.35", "alpha": 0.72},
            animated=True,
        )

        self.help_text = self.fig.text(
            0.5,
            0.015,
            "Space pause | N step | R random | C clear | P pattern | "
            "A age | I info | S save | +/- speed | Q quit",
            ha="center",
            va="bottom",
            fontsize=8,
        )

        self.fig.canvas.mpl_connect("key_press_event", self._on_key)
        self.fig.canvas.mpl_connect("button_press_event", self._on_click)

        self._update_title()
        self._update_info(None)

    def _apply_grid(self) -> None:
        self.ax.set_xticks(np.arange(-0.5, self.engine.width, 1), minor=True)
        self.ax.set_yticks(np.arange(-0.5, self.engine.height, 1), minor=True)
        self.ax.grid(which="minor", linewidth=0.15, alpha=0.3)
        self.ax.tick_params(which="minor", bottom=False, left=False)

    def _display_data(self) -> np.ndarray:
        return self.engine.age if self.show_age else self.engine.board

    def _display_vmax(self) -> float:
        if not self.show_age:
            return 1.0
        max_age = int(self.engine.age.max(initial=1))
        # Adaptive scale prevents a single ancient cell from crushing contrast.
        return float(max(8, min(max_age, 128)))

    def _update_title(self) -> None:
        state = "RUNNING" if self.running else "PAUSED"
        self.ax.set_title(
            f"Game of Life — {self.engine.rule.notation} — "
            f"{self.engine.boundary} boundary — {state}"
        )

    def _steps_per_second(self) -> float:
        if not self._step_times:
            return 0.0
        total = sum(self._step_times)
        return 0.0 if total <= 0 else len(self._step_times) / total

    def _update_info(self, stats: StepStats | None) -> None:
        if not self.show_info:
            self.info_text.set_text("")
            return

        pop = self.engine.population
        density = pop / self.engine.board.size
        repeat = ""
        if stats and stats.period is not None:
            repeat = (
                f"\nrepeat: gen {stats.repeated_from} "
                f"(period {stats.period})"
            )

        self.info_text.set_text(
            f"generation: {self.engine.generation:,}\n"
            f"population: {pop:,}\n"
            f"density:    {density:7.3%}\n"
            f"births:     {self.engine.births:,}\n"
            f"deaths:     {self.engine.deaths:,}\n"
            f"speed:      {self._steps_per_second():,.1f} gen/s\n"
            f"fps target: {self.fps:g}"
            f"{repeat}"
        )

    def _advance(self) -> StepStats:
        t0 = time.perf_counter()
        stats = self.engine.step()
        self._step_times.append(time.perf_counter() - t0)
        return stats

    def _render(self, stats: StepStats | None = None):
        self.image.set_data(self._display_data())
        self.image.set_cmap(self.age_cmap if self.show_age else self.binary_cmap)
        self.image.set_clim(0, self._display_vmax())
        self._update_info(stats)
        return self.image, self.info_text

    def _frame(self, _frame_index: int):
        stats = None
        if self.running:
            stats = self._advance()
            if (
                self.max_generations is not None
                and self.engine.generation >= self.max_generations
            ):
                self.running = False
                self._update_title()

        return self._render(stats)

    def _set_fps(self, new_fps: float) -> None:
        self.fps = float(np.clip(new_fps, 1.0, 240.0))
        if self._animation is not None:
            self._animation.event_source.interval = 1000.0 / self.fps
        self._update_info(None)

    def _on_key(self, event) -> None:
        key = (event.key or "").lower()

        if key in {" ", "space"}:
            self.running = not self.running
            self._update_title()

        elif key in {"n", "right"}:
            self.running = False
            self._update_title()
            stats = self._advance()
            self._render(stats)

        elif key == "r":
            self.engine.randomize(self.density)
            self._render(None)

        elif key == "c":
            self.engine.clear()
            self.running = False
            self._update_title()
            self._render(None)

        elif key == "g":
            self.engine.load_pattern("glider")
            self.running = False
            self._update_title()
            self._render(None)

        elif key == "p":
            name = PATTERN_NAMES[self._pattern_index % len(PATTERN_NAMES)]
            self._pattern_index += 1
            try:
                self.engine.load_pattern(name)
            except ValueError:
                # Skip patterns too large for the current board.
                return
            self.running = False
            self._update_title()
            self._render(None)
            self.ax.set_title(
                f"{name} — {self.engine.rule.notation} — "
                f"{self.engine.boundary} boundary — PAUSED"
            )

        elif key == "a":
            self.show_age = not self.show_age
            self._render(None)

        elif key == "i":
            self.show_info = not self.show_info
            self._render(None)

        elif key in {"+", "="}:
            self._set_fps(self.fps * 1.25)

        elif key in {"-", "_"}:
            self._set_fps(self.fps / 1.25)

        elif key == "s":
            path = self.save_png()
            self.ax.set_title(f"Saved {path.name}")

        elif key in {"q", "escape"}:
            self.plt.close(self.fig)

        self.fig.canvas.draw_idle()

    def _on_click(self, event) -> None:
        if event.inaxes is not self.ax or event.xdata is None or event.ydata is None:
            return
        col = int(np.floor(event.xdata + 0.5))
        row = int(np.floor(event.ydata + 0.5))
        self.engine.toggle(row, col)
        self.running = False
        self._update_title()
        self._render(None)
        self.fig.canvas.draw_idle()

    def save_png(self) -> Path:
        stamp = time.strftime("%Y%m%d_%H%M%S")
        path = Path(f"{self.output_prefix}_{stamp}_g{self.engine.generation}.png")
        self.fig.savefig(path, dpi=180, bbox_inches="tight")
        return path

    def run(self) -> None:
        # Keep a strong reference: Matplotlib animations stop if garbage-collected.
        self._animation = self.FuncAnimation(
            self.fig,
            self._frame,
            interval=1000.0 / self.fps,
            blit=True,
            cache_frame_data=False,
        )
        self.plt.show()


# ---------------------------------------------------------------------------
# CLI / headless / benchmark
# ---------------------------------------------------------------------------

def benchmark(engine: LifeEngine, steps: int) -> dict[str, float]:
    if steps < 1:
        raise ValueError("benchmark steps must be >= 1")

    # Warm-up to pay one-off allocation/cache costs before timing.
    warmup = min(10, max(1, steps // 20))
    engine.step(warmup)

    start = time.perf_counter()
    engine.step(steps)
    elapsed = time.perf_counter() - start

    cells = engine.board.size
    generations_per_second = steps / elapsed if elapsed else float("inf")
    cell_updates_per_second = (
        (steps * cells) / elapsed if elapsed else float("inf")
    )

    return {
        "steps": float(steps),
        "elapsed": elapsed,
        "generations_per_second": generations_per_second,
        "cell_updates_per_second": cell_updates_per_second,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Advanced vectorized Conway's Game of Life / Life-like cellular automaton."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    # Positional size preserves the original script's usage style.
    parser.add_argument(
        "size",
        nargs="?",
        type=int,
        default=120,
        help="square canvas size; overridden by --width/--height",
    )
    parser.add_argument("--width", type=int, help="board width")
    parser.add_argument("--height", type=int, help="board height")
    parser.add_argument(
        "--density",
        type=float,
        default=0.25,
        help="initial live-cell probability for random seeding",
    )
    parser.add_argument("--seed", type=int, help="deterministic RNG seed")
    parser.add_argument(
        "--rule",
        default="B3/S23",
        help="Life-like rule in B/S notation, e.g. B3/S23 or B36/S23",
    )
    parser.add_argument(
        "--boundary",
        choices=("wrap", "fixed"),
        default="wrap",
        help="edge behaviour",
    )
    parser.add_argument(
        "--pattern",
        choices=("random", "empty", *PATTERN_NAMES),
        default="random",
        help="initial board",
    )
    parser.add_argument(
        "--fps",
        type=float,
        default=30.0,
        help="target GUI generations/frames per second",
    )
    parser.add_argument(
        "--paused",
        action="store_true",
        help="open GUI paused",
    )
    parser.add_argument(
        "--grid",
        action="store_true",
        help="draw cell grid when board is <=120 cells per side",
    )
    parser.add_argument(
        "--binary",
        action="store_true",
        help="disable cell-age visualization",
    )
    parser.add_argument(
        "--no-info",
        action="store_true",
        help="hide statistics overlay",
    )
    parser.add_argument(
        "--history",
        type=int,
        default=4096,
        help="number of state fingerprints retained for repeat detection",
    )
    parser.add_argument(
        "--max-generations",
        type=int,
        help="generation limit; GUI pauses at limit, headless stops",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="run without opening Matplotlib",
    )
    parser.add_argument(
        "--benchmark",
        action="store_true",
        help="benchmark the vectorized engine without GUI",
    )
    parser.add_argument(
        "--benchmark-steps",
        type=int,
        default=250,
        help="timed generations in benchmark mode",
    )
    parser.add_argument(
        "--save-npy",
        type=Path,
        help="save final board as a .npy array",
    )
    parser.add_argument(
        "--output-prefix",
        default="life_snapshot",
        help="prefix used for GUI PNG snapshots",
    )

    return parser


def initialise_engine(args: argparse.Namespace) -> LifeEngine:
    width = args.width if args.width is not None else args.size
    height = args.height if args.height is not None else args.size

    if width < 3 or height < 3:
        raise ValueError("board width and height must both be at least 3")
    if not 0.0 <= args.density <= 1.0:
        raise ValueError("--density must be between 0 and 1")
    if args.fps <= 0:
        raise ValueError("--fps must be > 0")
    if args.history < 0:
        raise ValueError("--history must be >= 0")
    if args.max_generations is not None and args.max_generations < 0:
        raise ValueError("--max-generations must be >= 0")

    engine = LifeEngine(
        width=width,
        height=height,
        rule=args.rule,
        boundary=args.boundary,
        seed=args.seed,
        history_limit=args.history,
    )

    if args.pattern == "random":
        engine.randomize(args.density)
    elif args.pattern == "empty":
        engine.clear()
    else:
        engine.load_pattern(args.pattern)

    return engine


def run_headless(engine: LifeEngine, max_generations: int) -> StepStats:
    if max_generations < 0:
        raise ValueError("max_generations must be >= 0")

    last = StepStats(
        generation=engine.generation,
        population=engine.population,
        births=0,
        deaths=0,
        density=engine.density,
    )

    for _ in range(max_generations):
        last = engine.step()
        if last.population == 0:
            break

    return last


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        engine = initialise_engine(args)
    except ValueError as exc:
        parser.error(str(exc))

    if args.benchmark:
        results = benchmark(engine, args.benchmark_steps)
        print(
            f"Board: {engine.width}x{engine.height} "
            f"({engine.board.size:,} cells)"
        )
        print(f"Rule: {engine.rule.notation}")
        print(f"Boundary: {engine.boundary}")
        print(f"Timed generations: {int(results['steps']):,}")
        print(f"Elapsed: {results['elapsed']:.6f} s")
        print(
            "Throughput: "
            f"{results['generations_per_second']:,.2f} generations/s"
        )
        print(
            "Cell updates: "
            f"{results['cell_updates_per_second'] / 1_000_000:,.2f} million/s"
        )

    elif args.headless:
        generations = (
            args.max_generations if args.max_generations is not None else 1000
        )
        start = time.perf_counter()
        stats = run_headless(engine, generations)
        elapsed = time.perf_counter() - start

        print(f"Generation: {stats.generation:,}")
        print(f"Population: {stats.population:,}")
        print(f"Births (last step): {stats.births:,}")
        print(f"Deaths (last step): {stats.deaths:,}")
        print(f"Density: {stats.density:.6%}")
        if stats.period is not None:
            print(
                f"Repeat detected: generation {stats.repeated_from} "
                f"-> {stats.generation} (period {stats.period})"
            )
        print(f"Elapsed: {elapsed:.6f} s")

    else:
        app = LifeApp(
            engine,
            fps=args.fps,
            density=args.density,
            start_paused=args.paused,
            show_grid=args.grid,
            show_age=not args.binary,
            show_info=not args.no_info,
            max_generations=args.max_generations,
            output_prefix=args.output_prefix,
        )
        app.run()

    if args.save_npy:
        path = engine.save_npy(args.save_npy)
        print(f"Saved board: {path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
