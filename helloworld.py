#!/usr/bin/env python3
"""
Advanced Hello World
====================

A deliberately over-engineered evolution of:

    print("Hello World!")

Features:
- Command-line arguments
- Custom names/messages
- ANSI terminal colours
- Animated typing
- Repetition
- Timestamp support
- JSON output
- Logging
- Execution timing
- Environment/system information
- Cross-platform behaviour
- Graceful Ctrl+C handling
- No third-party dependencies
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import platform
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Final


APP_NAME: Final[str] = "Advanced Hello World"
VERSION: Final[str] = "3.0.0"


class ANSI:
    RESET = "\033[0m"
    BOLD = "\033[1m"

    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"


COLOURS: dict[str, str] = {
    "red": ANSI.RED,
    "green": ANSI.GREEN,
    "yellow": ANSI.YELLOW,
    "blue": ANSI.BLUE,
    "magenta": ANSI.MAGENTA,
    "cyan": ANSI.CYAN,
    "none": "",
}


@dataclass(slots=True)
class HelloResult:
    message: str
    target: str
    timestamp: str
    hostname: str
    operating_system: str
    python_version: str
    process_id: int
    execution_ms: float


def supports_colour() -> bool:
    """Return True when ANSI colour output is likely supported."""
    if not sys.stdout.isatty():
        return False

    if os.getenv("NO_COLOR") is not None:
        return False

    if os.name != "nt":
        return True

    return (
        os.getenv("ANSICON") is not None
        or os.getenv("WT_SESSION") is not None
        or os.getenv("TERM_PROGRAM") == "vscode"
        or "TERM" in os.environ
    )


def colour_text(text: str, colour: str, enabled: bool) -> str:
    """Apply ANSI colour codes when enabled."""
    if not enabled or colour == "none":
        return text

    return f"{COLOURS[colour]}{ANSI.BOLD}{text}{ANSI.RESET}"


def typewriter_print(
    text: str,
    delay: float = 0.03,
) -> None:
    """Print text one character at a time."""
    for character in text:
        print(character, end="", flush=True)
        time.sleep(delay)

    print()


def generate_message(
    target: str,
    prefix: str = "Hello",
    punctuation: str = "!",
) -> str:
    """Construct the greeting."""
    target = target.strip()

    if not target:
        target = "World"

    return f"{prefix}, {target}{punctuation}"


def get_timestamp() -> str:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc).astimezone().isoformat(
        timespec="seconds"
    )


def create_result(
    message: str,
    target: str,
    execution_ms: float,
) -> HelloResult:
    """Collect metadata about the execution."""
    return HelloResult(
        message=message,
        target=target,
        timestamp=get_timestamp(),
        hostname=platform.node() or "unknown",
        operating_system=(
            f"{platform.system()} "
            f"{platform.release()} "
            f"({platform.machine()})"
        ),
        python_version=platform.python_version(),
        process_id=os.getpid(),
        execution_ms=round(execution_ms, 4),
    )


def configure_logging(verbose: bool) -> logging.Logger:
    """Create application logger."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.WARNING,
        format=(
            "%(asctime)s | %(levelname)-8s | "
            "%(name)s | %(message)s"
        ),
        datefmt="%H:%M:%S",
    )

    return logging.getLogger(APP_NAME)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hello",
        description=(
            "A highly upgraded version of Python's classic "
            "'Hello World' program."
        ),
    )

    parser.add_argument(
        "target",
        nargs="?",
        default="World",
        help="Who or what should be greeted.",
    )

    parser.add_argument(
        "-p",
        "--prefix",
        default="Hello",
        help="Greeting prefix. Default: Hello",
    )

    parser.add_argument(
        "--punctuation",
        default="!",
        help="Ending punctuation. Default: !",
    )

    parser.add_argument(
        "-n",
        "--repeat",
        type=int,
        default=1,
        help="Number of greetings to generate.",
    )

    parser.add_argument(
        "--colour",
        choices=tuple(COLOURS),
        default="cyan",
        help="Terminal output colour.",
    )

    parser.add_argument(
        "--no-colour",
        action="store_true",
        help="Disable ANSI colours.",
    )

    parser.add_argument(
        "--animate",
        action="store_true",
        help="Display the greeting using a typewriter animation.",
    )

    parser.add_argument(
        "--speed",
        type=float,
        default=0.03,
        metavar="SECONDS",
        help="Animation delay between characters.",
    )

    parser.add_argument(
        "--timestamp",
        action="store_true",
        help="Show the current timestamp.",
    )

    parser.add_argument(
        "--system-info",
        action="store_true",
        help="Show execution/system information.",
    )

    parser.add_argument(
        "--json",
        action="store_true",
        help="Return structured JSON instead of normal output.",
    )

    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable debug logging.",
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"{APP_NAME} {VERSION}",
    )

    return parser


def validate_arguments(args: argparse.Namespace) -> None:
    if args.repeat < 1:
        raise ValueError("--repeat must be at least 1.")

    if args.repeat > 1000:
        raise ValueError("--repeat cannot exceed 1000.")

    if args.speed < 0:
        raise ValueError("--speed cannot be negative.")

    if args.speed > 10:
        raise ValueError("--speed cannot exceed 10 seconds.")


def print_system_info(result: HelloResult) -> None:
    print()
    print("─" * 60)
    print(f"Application : {APP_NAME}")
    print(f"Version     : {VERSION}")
    print(f"Host        : {result.hostname}")
    print(f"OS          : {result.operating_system}")
    print(f"Python      : {result.python_version}")
    print(f"Process ID  : {result.process_id}")
    print(f"Execution   : {result.execution_ms:.4f} ms")
    print("─" * 60)


def run(args: argparse.Namespace) -> int:
    logger = configure_logging(args.verbose)

    validate_arguments(args)

    logger.debug("Arguments: %s", vars(args))

    start_ns = time.perf_counter_ns()

    message = generate_message(
        target=args.target,
        prefix=args.prefix,
        punctuation=args.punctuation,
    )

    logger.debug("Generated message: %r", message)

    elapsed_ms = (time.perf_counter_ns() - start_ns) / 1_000_000

    result = create_result(
        message=message,
        target=args.target,
        execution_ms=elapsed_ms,
    )

    if args.json:
        output = asdict(result)
        output["repeat"] = args.repeat
        output["application"] = APP_NAME
        output["version"] = VERSION

        print(
            json.dumps(
                output,
                indent=4,
                ensure_ascii=False,
            )
        )

        return 0

    colour_enabled = (
        supports_colour()
        and not args.no_colour
    )

    formatted_message = colour_text(
        message,
        args.colour,
        colour_enabled,
    )

    for index in range(args.repeat):
        if args.repeat > 1:
            prefix = f"[{index + 1:03}/{args.repeat:03}] "
        else:
            prefix = ""

        output = prefix + formatted_message

        if args.timestamp:
            output = f"[{result.timestamp}] {output}"

        if args.animate:
            typewriter_print(
                output,
                delay=args.speed,
            )
        else:
            print(output)

    if args.system_info:
        print_system_info(result)

    logger.debug("Program completed successfully.")

    return 0


def main() -> int:
    parser = build_parser()

    try:
        args = parser.parse_args()
        return run(args)

    except KeyboardInterrupt:
        print(
            "\nInterrupted by user.",
            file=sys.stderr,
        )
        return 130

    except ValueError as exc:
        print(
            f"Configuration error: {exc}",
            file=sys.stderr,
        )
        return 2

    except BrokenPipeError:
        return 0

    except Exception as exc:
        logging.exception("Unexpected application failure.")

        print(
            f"Fatal error: {exc}",
            file=sys.stderr,
        )

        return 1


if __name__ == "__main__":
    raise SystemExit(main())
