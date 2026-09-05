from pathlib import Path
import py_compile, textwrap

script = r'''#!/usr/bin/env python3
"""
Advanced Sierpinski Triangle Generator
======================================

A modern, dependency-free Python 3 implementation of the Sierpinski triangle.

Features
--------
- Recursive fractal generation with clean type hints and dataclasses.
- Fast Turtle rendering using batched screen updates.
- Filled, outline, or combined rendering.
- Multiple colour palettes.
- Native SVG export without third-party packages.
- EPS export from the Turtle canvas.
- Interactive keyboard controls:
    Up / Down : increase / decrease recursion depth
    C         : cycle colour palette
    M         : cycle render mode
    S         : save SVG
    E         : save EPS
    R         : redraw
    Q / Esc   : quit
- Command-line validation and useful fractal statistics.

Examples
--------
    python sierpinski_advanced.py 6
    python sierpinski_advanced.py 8 --mode filled --palette neon
    python sierpinski_advanced.py 7 --svg sierpinski.svg
    python sierpinski_advanced.py 6 --background "#10131a" --palette ocean

No pip packages are required: only Python's standard library is used.
"""

from __future__ import annotations

import argparse
import colorsys
import html
import math
import sys
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterable, Iterator, Sequence

try:
    import turtle
except ImportError as exc:
    raise SystemExit("This Python installation does not include tkinter/turtle support.") from exc


PROGRAM_NAME = "Advanced Sierpinski Triangle"
VERSION = "2.0.0"
MAX_RECOMMENDED_DEPTH = 10

Point = tuple[float, float]
Triangle = tuple[Point, Point, Point]

PALETTES: dict[str, tuple[str, ...]] = {
    "classic": ("#e53935", "#fb8c00", "#fdd835", "#43a047", "#1e88e5", "#8e24aa"),
    "ocean": ("#00e5ff", "#00b8d4", "#0091ea", "#2962ff", "#304ffe", "#6200ea"),
    "forest": ("#dce775", "#9ccc65", "#66bb6a", "#43a047", "#00897b", "#00695c"),
    "fire": ("#fff176", "#ffca28", "#ff9800", "#f4511e", "#e53935", "#b71c1c"),
    "neon": ("#39ff14", "#00ffff", "#ff00ff", "#ffff00", "#ff3131", "#7df9ff"),
    "mono": ("#f5f5f5", "#d6d6d6", "#bdbdbd", "#9e9e9e", "#757575", "#424242"),
}

RENDER_MODES = ("outline", "filled", "both")


@dataclass(frozen=True, slots=True)
class Config:
    depth: int = 6
    size: float = 700.0
    mode: str = "both"
    palette: str = "classic"
    background: str = "#0b0d12"
    line_width: float = 1.2
    margin: float = 0.90
    show_stats: bool = True
    svg_path: Path | None = None
    eps_path: Path | None = None


def midpoint(a: Point, b: Point) -> Point:
    """Return the midpoint between two 2D points."""
    return ((a[0] + b[0]) * 0.5, (a[1] + b[1]) * 0.5)


def equilateral_triangle(size: float) -> Triangle:
    """
    Return an equilateral triangle centered around the origin.

    'size' is the side length.
    """
    height = size * math.sqrt(3.0) / 2.0
    return (
        (-size / 2.0, -height / 3.0),
        (0.0, 2.0 * height / 3.0),
        (size / 2.0, -height / 3.0),
    )


def subdivide(tri: Triangle) -> tuple[Triangle, Triangle, Triangle]:
    """Split one triangle into its three occupied Sierpinski children."""
    a, b, c = tri
    ab = midpoint(a, b)
    bc = midpoint(b, c)
    ca = midpoint(c, a)
    return (
        (a, ab, ca),
        (ab, b, bc),
        (ca, bc, c),
    )


def leaf_triangles(tri: Triangle, depth: int) -> Iterator[Triangle]:
    """
    Yield only triangles at the requested recursion depth.

    This avoids retaining the full fractal tree in memory.
    """
    if depth <= 0:
        yield tri
        return

    for child in subdivide(tri):
        yield from leaf_triangles(child, depth - 1)


def triangle_centroid(tri: Triangle) -> Point:
    a, b, c = tri
    return (
        (a[0] + b[0] + c[0]) / 3.0,
        (a[1] + b[1] + c[1]) / 3.0,
    )


def hex_to_rgb01(value: str) -> tuple[float, float, float]:
    value = value.lstrip("#")
    if len(value) != 6:
        raise ValueError(f"Expected #RRGGBB colour, got {value!r}")
    return tuple(int(value[i:i + 2], 16) / 255.0 for i in (0, 2, 4))  # type: ignore[return-value]


def rgb01_to_hex(rgb: Sequence[float]) -> str:
    r, g, b = (max(0, min(255, round(component * 255))) for component in rgb)
    return f"#{r:02x}{g:02x}{b:02x}"


def interpolate_colour(colours: Sequence[str], t: float) -> str:
    """Interpolate smoothly through a palette."""
    if not colours:
        return "#ffffff"
    if len(colours) == 1:
        return colours[0]

    t = max(0.0, min(1.0, t))
    position = t * (len(colours) - 1)
    index = min(int(position), len(colours) - 2)
    local_t = position - index

    c1 = hex_to_rgb01(colours[index])
    c2 = hex_to_rgb01(colours[index + 1])

    # Blend in HSV space for more visually interesting gradients.
    h1, s1, v1 = colorsys.rgb_to_hsv(*c1)
    h2, s2, v2 = colorsys.rgb_to_hsv(*c2)

    # Take the shortest path around the hue circle.
    dh = h2 - h1
    if dh > 0.5:
        dh -= 1.0
    elif dh < -0.5:
        dh += 1.0

    h = (h1 + dh * local_t) % 1.0
    s = s1 + (s2 - s1) * local_t
    v = v1 + (v2 - v1) * local_t

    return rgb01_to_hex(colorsys.hsv_to_rgb(h, s, v))


def colour_for_triangle(tri: Triangle, root: Triangle, palette_name: str) -> str:
    """
    Colour a leaf according to its vertical position, producing a smooth
    spatial gradient instead of a flat per-depth colour.
    """
    colours = PALETTES[palette_name]
    _, y = triangle_centroid(tri)
    ys = [p[1] for p in root]
    ymin, ymax = min(ys), max(ys)
    t = 0.5 if math.isclose(ymin, ymax) else (y - ymin) / (ymax - ymin)
    return interpolate_colour(colours, t)


def fractal_stats(depth: int, side_length: float) -> dict[str, float | int]:
    """
    Return mathematical properties of the depth-limited Sierpinski triangle.

    At recursion depth d:
      leaf triangles = 3^d
      scale per leaf  = 1 / 2^d
      theoretical Hausdorff dimension = log(3) / log(2)
    """
    leaves = 3 ** depth
    scale = 1.0 / (2 ** depth)
    original_area = (math.sqrt(3.0) / 4.0) * side_length * side_length
    remaining_area = original_area * ((3.0 / 4.0) ** depth)

    return {
        "depth": depth,
        "leaf_triangles": leaves,
        "leaf_side_length": side_length * scale,
        "area_fraction": (3.0 / 4.0) ** depth,
        "remaining_area": remaining_area,
        "hausdorff_dimension": math.log(3.0) / math.log(2.0),
    }


class TurtleRenderer:
    """Fast interactive Turtle renderer for the Sierpinski triangle."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.root = equilateral_triangle(config.size * config.margin)
        self.palette_names = list(PALETTES)
        self.mode_names = list(RENDER_MODES)

        self.screen = turtle.Screen()
        self.screen.title(f"{PROGRAM_NAME} v{VERSION}")
        window = int(max(640, min(1100, config.size + 180)))
        self.screen.setup(width=window, height=window)
        self.screen.bgcolor(config.background)
        self.screen.tracer(0, 0)

        self.pen = turtle.Turtle(visible=False)
        self.pen.speed(0)
        self.pen.penup()
        self.pen.width(config.line_width)

        self.status_pen = turtle.Turtle(visible=False)
        self.status_pen.speed(0)
        self.status_pen.penup()
        self.status_pen.color("#cfd8dc")

        self._bind_keys()

    def _bind_keys(self) -> None:
        self.screen.listen()
        self.screen.onkey(self.increase_depth, "Up")
        self.screen.onkey(self.decrease_depth, "Down")
        self.screen.onkey(self.cycle_palette, "c")
        self.screen.onkey(self.cycle_palette, "C")
        self.screen.onkey(self.cycle_mode, "m")
        self.screen.onkey(self.cycle_mode, "M")
        self.screen.onkey(self.redraw, "r")
        self.screen.onkey(self.redraw, "R")
        self.screen.onkey(self.save_svg, "s")
        self.screen.onkey(self.save_svg, "S")
        self.screen.onkey(self.save_eps, "e")
        self.screen.onkey(self.save_eps, "E")
        self.screen.onkey(self.screen.bye, "q")
        self.screen.onkey(self.screen.bye, "Q")
        self.screen.onkey(self.screen.bye, "Escape")

    def increase_depth(self) -> None:
        if self.config.depth < 12:
            self.config = replace(self.config, depth=self.config.depth + 1)
            self.redraw()

    def decrease_depth(self) -> None:
        if self.config.depth > 0:
            self.config = replace(self.config, depth=self.config.depth - 1)
            self.redraw()

    def cycle_palette(self) -> None:
        index = self.palette_names.index(self.config.palette)
        palette = self.palette_names[(index + 1) % len(self.palette_names)]
        self.config = replace(self.config, palette=palette)
        self.redraw()

    def cycle_mode(self) -> None:
        index = self.mode_names.index(self.config.mode)
        mode = self.mode_names[(index + 1) % len(self.mode_names)]
        self.config = replace(self.config, mode=mode)
        self.redraw()

    def _draw_triangle(self, tri: Triangle, colour: str) -> None:
        a, b, c = tri
        self.pen.penup()
        self.pen.goto(*a)
        self.pen.pendown()

        if self.config.mode in {"filled", "both"}:
            self.pen.fillcolor(colour)
            self.pen.pencolor(colour if self.config.mode == "filled" else "#ffffff")
            self.pen.begin_fill()
            self.pen.goto(*b)
            self.pen.goto(*c)
            self.pen.goto(*a)
            self.pen.end_fill()
        else:
            self.pen.pencolor(colour)
            self.pen.goto(*b)
            self.pen.goto(*c)
            self.pen.goto(*a)

        self.pen.penup()

    def _draw_status(self, elapsed: float) -> None:
        self.status_pen.clear()
        if not self.config.show_stats:
            return

        stats = fractal_stats(self.config.depth, self.config.size * self.config.margin)
        window_height = self.screen.window_height()
        x = -self.screen.window_width() / 2 + 18
        y = -window_height / 2 + 18

        text = (
            f"Depth {self.config.depth}  |  "
            f"{stats['leaf_triangles']:,} leaf triangles  |  "
            f"mode: {self.config.mode}  |  palette: {self.config.palette}  |  "
            f"render: {elapsed * 1000:.1f} ms\n"
            "↑/↓ depth   C palette   M mode   S SVG   E EPS   R redraw   Q quit"
        )
        self.status_pen.goto(x, y)
        self.status_pen.write(text, align="left", font=("Arial", 10, "normal"))

    def redraw(self) -> None:
        started = time.perf_counter()
        self.pen.clear()
        self.status_pen.clear()
        self.screen.bgcolor(self.config.background)
        self.pen.width(self.config.line_width)

        for tri in leaf_triangles(self.root, self.config.depth):
            colour = colour_for_triangle(tri, self.root, self.config.palette)
            self._draw_triangle(tri, colour)

        elapsed = time.perf_counter() - started
        self._draw_status(elapsed)
        self.screen.update()

    def save_svg(self) -> None:
        path = self.config.svg_path or Path(f"sierpinski_depth_{self.config.depth}.svg")
        export_svg(
            path=path,
            root=self.root,
            depth=self.config.depth,
            palette=self.config.palette,
            background=self.config.background,
            mode=self.config.mode,
            line_width=self.config.line_width,
        )
        print(f"SVG saved to: {path.resolve()}")

    def save_eps(self) -> None:
        path = self.config.eps_path or Path(f"sierpinski_depth_{self.config.depth}.eps")
        self.screen.getcanvas().postscript(file=str(path), colormode="color")
        print(f"EPS saved to: {path.resolve()}")

    def run(self) -> None:
        self.redraw()

        if self.config.svg_path is not None:
            self.save_svg()
        if self.config.eps_path is not None:
            self.save_eps()

        turtle.done()


def export_svg(
    path: Path,
    root: Triangle,
    depth: int,
    palette: str,
    background: str,
    mode: str,
    line_width: float,
) -> None:
    """Export the current fractal as a standalone vector SVG."""
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)

    all_x = [p[0] for p in root]
    all_y = [p[1] for p in root]
    min_x, max_x = min(all_x), max(all_x)
    min_y, max_y = min(all_y), max(all_y)

    pad = max(max_x - min_x, max_y - min_y) * 0.04
    width = (max_x - min_x) + pad * 2
    height = (max_y - min_y) + pad * 2

    def svg_xy(point: Point) -> tuple[float, float]:
        # SVG's Y axis points downward; Turtle's points upward.
        x, y = point
        return x - min_x + pad, max_y - y + pad

    polygons: list[str] = []

    for tri in leaf_triangles(root, depth):
        colour = colour_for_triangle(tri, root, palette)
        coords = " ".join(
            f"{x:.3f},{y:.3f}" for x, y in (svg_xy(point) for point in tri)
        )

        if mode == "filled":
            fill = colour
            stroke = colour
        elif mode == "both":
            fill = colour
            stroke = "#ffffff"
        else:
            fill = "none"
            stroke = colour

        polygons.append(
            f'<polygon points="{coords}" fill="{fill}" '
            f'stroke="{stroke}" stroke-width="{line_width:.3f}" '
            'stroke-linejoin="round"/>'
        )

    escaped_bg = html.escape(background, quote=True)
    document = "\n".join(
        [
            '<?xml version="1.0" encoding="UTF-8"?>',
            (
                f'<svg xmlns="http://www.w3.org/2000/svg" '
                f'viewBox="0 0 {width:.3f} {height:.3f}" '
                f'width="{width:.0f}" height="{height:.0f}">'
            ),
            f'<rect width="100%" height="100%" fill="{escaped_bg}"/>',
            *polygons,
            "</svg>",
        ]
    )

    path.write_text(document, encoding="utf-8")


def colour_argument(value: str) -> str:
    """
    Accept #RRGGBB colours for deterministic SVG + Turtle compatibility.
    """
    value = value.strip()
    if not (len(value) == 7 and value.startswith("#")):
        raise argparse.ArgumentTypeError("colour must use #RRGGBB format")
    try:
        int(value[1:], 16)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("colour must use hexadecimal #RRGGBB format") from exc
    return value.lower()


def positive_float(value: str) -> float:
    number = float(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("value must be greater than zero")
    return number


def depth_argument(value: str) -> int:
    try:
        depth = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("depth must be an integer") from exc

    if depth < 0:
        raise argparse.ArgumentTypeError("depth must be 0 or greater")
    if depth > 12:
        raise argparse.ArgumentTypeError(
            "depth above 12 is intentionally blocked because Turtle rendering becomes extremely heavy"
        )
    return depth


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sierpinski_advanced.py",
        description="Render an interactive, colourised Sierpinski triangle.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument(
        "depth",
        nargs="?",
        default=6,
        type=depth_argument,
        help="fractal recursion depth",
    )
    parser.add_argument(
        "--size",
        type=positive_float,
        default=700.0,
        help="outer triangle side length in Turtle coordinate units",
    )
    parser.add_argument(
        "--mode",
        choices=RENDER_MODES,
        default="both",
        help="triangle drawing style",
    )
    parser.add_argument(
        "--palette",
        choices=tuple(PALETTES),
        default="classic",
        help="colour palette",
    )
    parser.add_argument(
        "--background",
        type=colour_argument,
        default="#0b0d12",
        help="background colour in #RRGGBB format",
    )
    parser.add_argument(
        "--line-width",
        type=positive_float,
        default=1.2,
        help="triangle outline width",
    )
    parser.add_argument(
        "--no-stats",
        action="store_true",
        help="hide the on-screen statistics and keyboard help",
    )
    parser.add_argument(
        "--svg",
        type=Path,
        metavar="FILE",
        help="also export a standalone SVG file",
    )
    parser.add_argument(
        "--eps",
        type=Path,
        metavar="FILE",
        help="also export the Turtle canvas as EPS",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {VERSION}",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.depth > MAX_RECOMMENDED_DEPTH:
        print(
            f"Warning: depth {args.depth} creates {3 ** args.depth:,} leaf triangles; "
            "Turtle rendering may be slow.",
            file=sys.stderr,
        )

    config = Config(
        depth=args.depth,
        size=args.size,
        mode=args.mode,
        palette=args.palette,
        background=args.background,
        line_width=args.line_width,
        show_stats=not args.no_stats,
        svg_path=args.svg,
        eps_path=args.eps,
    )

    stats = fractal_stats(config.depth, config.size * config.margin)
    print(f"{PROGRAM_NAME} v{VERSION}")
    print(f"Depth: {config.depth}")
    print(f"Leaf triangles: {stats['leaf_triangles']:,}")
    print(f"Leaf side length: {stats['leaf_side_length']:.6f}")
    print(f"Remaining area fraction: {stats['area_fraction']:.8f}")
    print(f"Hausdorff dimension: {stats['hausdorff_dimension']:.12f}")

    try:
        TurtleRenderer(config).run()
    except turtle.Terminator:
        pass
    except Exception as exc:
        # A common cause is running in a headless environment with no Tk display.
        print(f"Unable to start Turtle graphics: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''

path = Path("/mnt/data/sierpinski_advanced.py")
path.write_text(script, encoding="utf-8")
py_compile.compile(str(path), doraise=True)

print(f"Created: {path}")
print("Syntax check: PASS")
print(f"Lines: {len(script.splitlines())}")
print(f"Characters: {len(script):,}")
