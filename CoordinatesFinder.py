#!/usr/bin/env python3
"""
Advanced Mouse Position Inspector

Install:
    python -m pip install pyautogui

Examples:
    python mouse_tracker.py
    python mouse_tracker.py --interval 0.05
    python mouse_tracker.py --log mouse_positions.csv
    python mouse_tracker.py --no-colour
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from datetime import datetime
from pathlib import Path

import pyautogui


def positive_float(value: str) -> float:
    """Validate a positive float argument."""
    try:
        number = float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("Must be a number.") from error

    if number <= 0:
        raise argparse.ArgumentTypeError("Must be greater than zero.")

    return number


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Display live mouse coordinates, screen percentages, and RGB colour."
    )

    parser.add_argument(
        "--interval",
        type=positive_float,
        default=0.1,
        help="Refresh interval in seconds. Default: 0.1",
    )

    parser.add_argument(
        "--log",
        type=Path,
        metavar="FILE.csv",
        help="Save coordinate changes to a CSV file.",
    )

    parser.add_argument(
        "--no-colour",
        action="store_true",
        help="Do not read the RGB pixel colour under the mouse cursor.",
    )

    parser.add_argument(
        "--once",
        action="store_true",
        help="Print one coordinate reading and exit.",
    )

    return parser.parse_args()


def create_csv_logger(path: Path):
    """Create a CSV file and return its writer and file handle."""
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)

    file_handle = path.open("w", newline="", encoding="utf-8")
    writer = csv.writer(file_handle)

    writer.writerow(
        [
            "timestamp",
            "x",
            "y",
            "screen_width",
            "screen_height",
            "x_percent",
            "y_percent",
            "red",
            "green",
            "blue",
        ]
    )

    return file_handle, writer


def get_mouse_data(screen_width: int, screen_height: int, read_colour: bool) -> dict:
    """Collect current cursor position and optional RGB data."""
    x, y = pyautogui.position()

    red = green = blue = None

    if read_colour:
        try:
            red, green, blue = pyautogui.pixel(x, y)
        except Exception:
            # Some systems can block screenshot/pixel access.
            red = green = blue = None

    return {
        "timestamp": datetime.now().isoformat(timespec="milliseconds"),
        "x": x,
        "y": y,
        "screen_width": screen_width,
        "screen_height": screen_height,
        "x_percent": (x / max(screen_width - 1, 1)) * 100,
        "y_percent": (y / max(screen_height - 1, 1)) * 100,
        "red": red,
        "green": green,
        "blue": blue,
    }


def format_status(data: dict) -> str:
    """Create one terminal-friendly status line."""
    colour = "RGB: unavailable"

    if data["red"] is not None:
        colour = f"RGB: ({data['red']:3}, {data['green']:3}, {data['blue']:3})"

    return (
        f"X: {data['x']:5} | "
        f"Y: {data['y']:5} | "
        f"Screen: {data['screen_width']}x{data['screen_height']} | "
        f"Position: {data['x_percent']:6.2f}% x {data['y_percent']:6.2f}% | "
        f"{colour}"
    )


def main() -> int:
    args = parse_args()

    # Safety feature: moving mouse to upper-left can interrupt PyAutoGUI actions.
    pyautogui.FAILSAFE = True

    screen_width, screen_height = pyautogui.size()

    print("Advanced Mouse Position Inspector")
    print(f"Screen size: {screen_width} x {screen_height}")
    print("Press Ctrl-C to quit.")

    if args.log:
        print(f"Logging coordinate changes to: {args.log}")

    csv_file = None
    csv_writer = None

    if args.log:
        csv_file, csv_writer = create_csv_logger(args.log)

    last_line_length = 0
    last_position = None

    try:
        while True:
            data = get_mouse_data(
                screen_width=screen_width,
                screen_height=screen_height,
                read_colour=not args.no_colour,
            )

            status = format_status(data)

            # Overwrite the previous terminal line cleanly.
            sys.stdout.write("\r" + status.ljust(last_line_length))
            sys.stdout.flush()
            last_line_length = len(status)

            current_position = (data["x"], data["y"])

            # Only log when the cursor actually moves.
            if csv_writer and current_position != last_position:
                csv_writer.writerow(
                    [
                        data["timestamp"],
                        data["x"],
                        data["y"],
                        data["screen_width"],
                        data["screen_height"],
                        f"{data['x_percent']:.2f}",
                        f"{data['y_percent']:.2f}",
                        data["red"],
                        data["green"],
                        data["blue"],
                    ]
                )
                csv_file.flush()

            last_position = current_position

            if args.once:
                break

            time.sleep(args.interval)

    except KeyboardInterrupt:
        print("\n\nStopped safely.")

    except pyautogui.FailSafeException:
        print("\n\nPyAutoGUI fail-safe triggered.")

    finally:
        if csv_file:
            csv_file.close()
            print("Log file saved.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
