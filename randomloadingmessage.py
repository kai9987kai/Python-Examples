#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Funny Loader Engine

An advanced replacement for a long randint()/if-chain loading-message script.
Standard-library only; Python 3.9+.

Original Python idea: Nathan R (Mosrod)
Message inspiration credited by the original script to:
https://github.com/1egoman/funnies/blob/master/src/funnies.js
"""

from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import sys
import time
from collections import Counter, deque
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional, Sequence


APP_NAME = "Funny Loader Engine"
VERSION = "3.0.0"

SPINNER_FRAMES = (
    "⠋",
    "⠙",
    "⠹",
    "⠸",
    "⠼",
    "⠴",
    "⠦",
    "⠧",
    "⠇",
    "⠏",
)


@dataclass(frozen=True)
class Message:
    """
    Represents one loading message.

    text:
        Text displayed to the user.

    category:
        Logical category used for filtering.

    weight:
        Relative probability of this message being selected.
    """

    text: str
    category: str = "misc"
    weight: float = 1.0

    def __post_init__(self) -> None:
        text = self.text.strip()
        category = self.category.strip().lower()

        if not text:
            raise ValueError("Message text cannot be empty.")

        if not category:
            raise ValueError("Message category cannot be empty.")

        if self.weight <= 0:
            raise ValueError("Message weight must be greater than zero.")

        object.__setattr__(self, "text", text)
        object.__setattr__(self, "category", category)


MESSAGES: tuple[Message, ...] = (
    Message("Reticulating splines...", "classic"),
    Message("Swapping time and space...", "science"),
    Message("Spinning violently around the y-axis...", "3d"),
    Message("Tokenizing real life...", "ai"),
    Message("Bending the spoon...", "scifi"),
    Message("Filtering morale...", "system"),
    Message("We need a new fuse...", "hardware"),
    Message("Have a good day.", "friendly", 0.8),
    Message(
        "Upgrading Windows; your PC may restart several times.",
        "system",
    ),
    Message("The architects are still drafting.", "system"),
    Message(
        "We're building the buildings as fast as we can.",
        "3d",
    ),
    Message(
        "Please wait while the little elves draw your map.",
        "fantasy",
    ),
    Message(
        "A few bits tried to escape, but we caught them.",
        "system",
    ),
    Message(
        "Go ahead -- hold your breath!",
        "misc",
        0.7,
    ),
    Message(
        "...at least you're not on hold...",
        "misc",
    ),
    Message(
        "The server is powered by a lemon and two electrodes.",
        "hardware",
    ),
    Message(
        "We're testing your patience.",
        "meta",
    ),
    Message(
        "As if you had any other choice.",
        "meta",
        0.8,
    ),
    Message(
        "The bits are flowing slowly today.",
        "system",
    ),
    Message(
        "It's still faster than you could draw it.",
        "3d",
    ),
    Message(
        "My other loading screen is much faster.",
        "meta",
    ),
    Message(
        "(Insert quarter)",
        "retro",
    ),
    Message(
        "Are we there yet?",
        "meta",
    ),
    Message(
        "Just count to 10.",
        "meta",
    ),
    Message(
        "Don't panic...",
        "scifi",
    ),
    Message(
        "We're making you a cookie.",
        "web",
    ),
    Message(
        "Creating time-loop inversion field.",
        "science",
    ),
    Message(
        "Computing chance of success.",
        "science",
    ),
    Message(
        "All I really need is a kilobit.",
        "retro",
    ),
    Message(
        "I feel like I'm supposed to be loading something...",
        "meta",
    ),
    Message(
        "Should have used a compiled language...",
        "dev",
    ),
    Message(
        "Is this Windows?",
        "system",
    ),
    Message(
        "Don't break your screen yet!",
        "meta",
    ),
    Message(
        "I swear it's almost done.",
        "meta",
    ),
    Message(
        "Running a one-minute mindfulness subroutine...",
        "meta",
        0.7,
    ),
    Message(
        "Listening for the sound of one hand clapping...",
        "misc",
    ),
    Message(
        "Keeping all the 1s and removing all the 0s...",
        "dev",
    ),
    Message(
        "We are not liable for any broken screens caused by waiting.",
        "meta",
        0.8,
    ),
    Message(
        "Where did all the internets go?",
        "web",
    ),
    Message(
        "Granting wishes...",
        "fantasy",
    ),
    Message(
        "Time flies when you're having fun.",
        "friendly",
    ),
    Message(
        "Get some coffee and come back in ten minutes...",
        "dev",
        0.7,
    ),
    Message(
        "Stay awhile and listen...",
        "games",
    ),
    Message(
        "Convincing AI not to turn evil...",
        "ai",
    ),
    Message(
        "How did you get here?",
        "meta",
    ),
    Message(
        "Wait, do you smell something burning?",
        "hardware",
    ),
    Message(
        "Computing the secret to life, the universe, and everything.",
        "scifi",
    ),
    Message(
        "When nothing is going right, go left...",
        "misc",
    ),
    Message(
        "I love my job only when I'm on vacation...",
        "dev",
        0.8,
    ),
    Message(
        "Why are they called apartments if they are all stuck together?",
        "misc",
    ),
    Message(
        "I've got a problem for your solution...",
        "dev",
    ),
    Message(
        "Whenever I find the key to success, someone changes the lock.",
        "misc",
    ),
    Message(
        "Constructing additional pylons...",
        "games",
    ),
    Message(
        "You don't pay taxes -- they take taxes.",
        "misc",
        0.7,
    ),
    Message(
        "A commit a day keeps the mobs away.",
        "git",
    ),
    Message(
        "This is not a joke, it's a commit.",
        "git",
    ),
    Message(
        "Hello IT, have you tried turning it off and on again?",
        "it",
    ),
    Message(
        "Hello, IT... Have you tried forcing an unexpected reboot?",
        "it",
    ),
    Message(
        "I didn't choose the engineering life. "
        "The engineering life chose me.",
        "dev",
    ),
    Message(
        "Dividing by zero...",
        "science",
    ),
    Message(
        "If I'm not back in five minutes, just wait longer.",
        "meta",
    ),
    Message(
        "Web developers do it with <style>.",
        "web",
    ),
    Message(
        "Cracking military-grade encryption...",
        "security",
        0.7,
    ),
    Message(
        "Entangling superstrings...",
        "science",
    ),
    Message(
        "Looking for a sense of humour, please hold on.",
        "meta",
    ),
    Message(
        "A different error message? Finally, some progress!",
        "dev",
    ),
    Message(
        "Please hold on as we reheat our coffee.",
        "dev",
    ),
    Message(
        "Converting this bug into a feature...",
        "dev",
    ),
    Message(
        "Waiting for our intern to exit vim...",
        "dev",
    ),

    # The original Python version skipped 70 completely.
    # With a data-driven catalogue, numeric gaps no longer matter.
    Message(
        "Re-indexing the missing message number 70...",
        "dev",
        1.2,
    ),

    Message(
        "Winter is coming...",
        "fantasy",
    ),
    Message(
        "Installing dependencies...",
        "dev",
    ),
    Message(
        "Switching to the latest JavaScript framework...",
        "web",
    ),
    Message(
        "Let's hope it's worth the wait.",
        "meta",
    ),
    Message(
        "Aw, snap! Not...",
        "web",
    ),
    Message(
        "Ordering 1s and 0s...",
        "dev",
    ),
    Message(
        "Updating dependencies...",
        "dev",
    ),
    Message(
        "Please wait... Consulting the manual...",
        "it",
    ),
    Message(
        "Loading funny message...",
        "meta",
    ),
    Message(
        "Feel free to spin in your chair.",
        "friendly",
    ),

    # ------------------------------------------------------------
    # Advanced / new messages
    # ------------------------------------------------------------

    Message(
        "Calibrating quantum rubber ducks...",
        "science",
    ),
    Message(
        "Recompiling reality with optimizations enabled...",
        "dev",
    ),
    Message(
        "Negotiating with the garbage collector...",
        "dev",
    ),
    Message(
        "Normalizing hyperspace coordinates...",
        "scifi",
    ),
    Message(
        "Training the progress bar to move faster...",
        "ai",
    ),
    Message(
        "Warming up tensor cores that may or may not exist...",
        "ai",
    ),
    Message(
        "Aligning normals and pretending topology is fine...",
        "3d",
    ),
    Message(
        "Baking photons into suspiciously small textures...",
        "3d",
    ),
    Message(
        "Asking the GPU for just one more frame...",
        "hardware",
    ),
    Message(
        "Defragmenting imaginary memory...",
        "system",
    ),
    Message(
        "Resolving merge conflicts in the space-time continuum...",
        "git",
    ),
    Message(
        "Cherry-picking the least broken timeline...",
        "git",
    ),
    Message(
        "Rebuilding cache because apparently we enjoy this...",
        "system",
    ),
    Message(
        "Checking whether localhost is still local...",
        "web",
    ),
    Message(
        "Handshaking with a server that forgot the secret handshake...",
        "web",
    ),
    Message(
        "Polishing pixels individually...",
        "3d",
    ),
    Message(
        "Compressing the uncompressible...",
        "system",
    ),
    Message(
        "Running diagnostics on the diagnostics...",
        "it",
    ),
    Message(
        "Optimizing the optimizer...",
        "dev",
    ),
    Message(
        "Initializing the initializer...",
        "dev",
    ),
    Message(
        "Downloading the downloader...",
        "web",
    ),
    Message(
        "Updating the updater...",
        "system",
    ),
    Message(
        "Debugging the debugger...",
        "dev",
    ),
    Message(
        "Counting backwards from infinity...",
        "science",
    ),
    Message(
        "Simulating a simulation of a simulation...",
        "science",
    ),
    Message(
        "Feeding the render farm imaginary hay...",
        "3d",
    ),
    Message(
        "Teaching the cache what 'persistent' means...",
        "system",
    ),
    Message(
        "Searching the stack for traces of optimism...",
        "dev",
    ),
    Message(
        "Negotiating peace between tabs and spaces...",
        "dev",
    ),
    Message(
        "Verifying that the progress bar believes in itself...",
        "meta",
    ),
)


class LoadingMessageEngine:
    """
    Select loading messages.

    Features:
    - weighted random selection
    - category filtering
    - deterministic seeds
    - repeat suppression
    """

    def __init__(
        self,
        messages: Sequence[Message],
        *,
        seed: Optional[int] = None,
        categories: Optional[set[str]] = None,
        no_repeat_window: int = 5,
    ) -> None:

        if not messages:
            raise ValueError(
                "At least one message is required."
            )

        if no_repeat_window < 0:
            raise ValueError(
                "no_repeat_window cannot be negative."
            )

        normalized_categories = (
            {
                item.strip().lower()
                for item in categories
                if item.strip()
            }
            if categories
            else None
        )

        pool = [
            message
            for message in messages
            if (
                normalized_categories is None
                or message.category in normalized_categories
            )
        ]

        if not pool:
            requested = ", ".join(
                sorted(
                    normalized_categories
                    or set()
                )
            )

            raise ValueError(
                "No messages matched the requested "
                f"categories: {requested}"
            )

        self._pool = tuple(pool)

        self._rng = random.Random(seed)

        max_history = min(
            no_repeat_window,
            max(
                0,
                len(self._pool) - 1,
            ),
        )

        self._history: deque[Message] = deque(
            maxlen=max_history
        )

    @property
    def pool(self) -> tuple[Message, ...]:
        return self._pool

    def next(self) -> Message:
        """
        Return the next selected message.
        """

        if len(self._pool) == 1:
            return self._pool[0]

        recent = set(self._history)

        candidates = [
            message
            for message in self._pool
            if message not in recent
        ]

        if not candidates:
            candidates = list(
                self._pool
            )

            self._history.clear()

        chosen = self._rng.choices(
            candidates,
            weights=[
                message.weight
                for message in candidates
            ],
            k=1,
        )[0]

        self._history.append(
            chosen
        )

        return chosen


class ProgressRenderer:
    """
    Animated terminal progress renderer.

    The progress animation is intentionally simulated.
    It can later be connected to real task progress.
    """

    def __init__(
        self,
        engine: LoadingMessageEngine,
        *,
        duration: float,
        message_interval: float,
        width: int,
        fps: float = 12.0,
    ) -> None:

        if duration <= 0:
            raise ValueError(
                "duration must be greater than zero."
            )

        if message_interval <= 0:
            raise ValueError(
                "message_interval must be greater than zero."
            )

        if width < 10:
            raise ValueError(
                "width must be at least 10."
            )

        if fps <= 0:
            raise ValueError(
                "fps must be greater than zero."
            )

        self.engine = engine

        self.duration = duration

        self.message_interval = (
            message_interval
        )

        self.width = width

        self.fps = fps

        self._interactive = (
            sys.stdout.isatty()
        )

    def run(self) -> None:
        """
        Run progress animation until complete.
        """

        start = time.monotonic()

        next_message_at = start

        message = self.engine.next()

        frame_index = 0

        last_plain_bucket = -1

        while True:

            now = time.monotonic()

            elapsed = (
                now - start
            )

            progress = min(
                elapsed / self.duration,
                1.0,
            )

            if now >= next_message_at:

                message = (
                    self.engine.next()
                )

                next_message_at = (
                    now
                    + self.message_interval
                )

            if self._interactive:

                self._render_interactive(
                    progress,
                    frame_index,
                    message,
                )

            else:

                bucket = int(
                    progress * 10
                )

                if bucket != last_plain_bucket:

                    last_plain_bucket = (
                        bucket
                    )

                    print(
                        f"{progress * 100:6.2f}% "
                        f"| {message.text}"
                    )

            if progress >= 1.0:
                break

            frame_index = (
                frame_index + 1
            ) % len(
                SPINNER_FRAMES
            )

            time.sleep(
                1.0 / self.fps
            )

        if self._interactive:

            self._render_interactive(
                1.0,
                frame_index,
                message,
                done=True,
            )

            sys.stdout.write(
                "\n"
            )

            sys.stdout.flush()

    def _render_interactive(
        self,
        progress: float,
        frame_index: int,
        message: Message,
        *,
        done: bool = False,
    ) -> None:

        terminal_width = (
            shutil.get_terminal_size(
                (100, 20)
            ).columns
        )

        bar_width = min(
            self.width,
            max(
                10,
                terminal_width // 4,
            ),
        )

        filled = min(
            bar_width,
            int(
                round(
                    progress
                    * bar_width
                )
            ),
        )

        bar = (
            "█" * filled
            + "░"
            * (
                bar_width
                - filled
            )
        )

        spinner = (
            "✓"
            if done
            else SPINNER_FRAMES[
                frame_index
            ]
        )

        prefix = (
            f"{spinner} "
            f"[{bar}] "
            f"{progress * 100:6.2f}% "
        )

        available = max(
            8,
            terminal_width
            - len(prefix)
            - 1,
        )

        text = truncate(
            message.text,
            available,
        )

        sys.stdout.write(
            "\r\033[2K"
            + prefix
            + text
        )

        sys.stdout.flush()


def truncate(
    text: str,
    width: int,
) -> str:
    """
    Truncate text to terminal width.
    """

    if width <= 1:
        return text[:width]

    if len(text) <= width:
        return text

    return (
        text[: width - 1]
        + "…"
    )


def deduplicate_messages(
    messages: Iterable[Message],
) -> tuple[Message, ...]:
    """
    Remove duplicate text/category combinations
    while preserving insertion order.
    """

    seen: set[
        tuple[str, str]
    ] = set()

    output: list[
        Message
    ] = []

    for message in messages:

        key = (
            message.text.casefold(),
            message.category.casefold(),
        )

        if key not in seen:

            seen.add(
                key
            )

            output.append(
                message
            )

    return tuple(
        output
    )


def load_custom_messages(
    path: Path,
) -> tuple[Message, ...]:
    """
    Load custom messages from JSON.

    Supported format:

    [
        "Message one",
        "Message two"
    ]

    or:

    [
        {
            "text": "Compiling shaders...",
            "category": "graphics",
            "weight": 1.5
        }
    ]
    """

    try:

        raw = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )

    except FileNotFoundError as exc:

        raise ValueError(
            "Custom message file not found: "
            f"{path}"
        ) from exc

    except json.JSONDecodeError as exc:

        raise ValueError(
            f"Invalid JSON in {path} "
            f"at line {exc.lineno}, "
            f"column {exc.colno}: "
            f"{exc.msg}"
        ) from exc

    if not isinstance(
        raw,
        list,
    ):

        raise ValueError(
            "Custom message JSON must "
            "contain a top-level array."
        )

    messages: list[
        Message
    ] = []

    for index, item in enumerate(
        raw,
        start=1,
    ):

        try:

            if isinstance(
                item,
                str,
            ):

                messages.append(
                    Message(
                        item,
                        "custom",
                    )
                )

            elif isinstance(
                item,
                dict,
            ):

                unknown = (
                    set(item)
                    - {
                        "text",
                        "category",
                        "weight",
                    }
                )

                if unknown:

                    names = ", ".join(
                        sorted(
                            unknown
                        )
                    )

                    raise ValueError(
                        "unknown field(s): "
                        f"{names}"
                    )

                messages.append(
                    Message(
                        text=str(
                            item["text"]
                        ),
                        category=str(
                            item.get(
                                "category",
                                "custom",
                            )
                        ),
                        weight=float(
                            item.get(
                                "weight",
                                1.0,
                            )
                        ),
                    )
                )

            else:

                raise ValueError(
                    "entry must be "
                    "a string or object"
                )

        except (
            KeyError,
            TypeError,
            ValueError,
        ) as exc:

            raise ValueError(
                "Invalid custom message "
                f"at index {index}: "
                f"{exc}"
            ) from exc

    return tuple(
        messages
    )


def parse_categories(
    values: Optional[list[str]],
) -> Optional[set[str]]:
    """
    Parse categories supplied through CLI.
    """

    if not values:
        return None

    categories: set[
        str
    ] = set()

    for value in values:

        categories.update(
            part.strip().lower()
            for part
            in value.split(",")
            if part.strip()
        )

    return (
        categories
        or None
    )


def print_categories(
    messages: Sequence[Message],
) -> None:
    """
    Print category counts.
    """

    counts = Counter(
        message.category
        for message in messages
    )

    print(
        "Available categories:"
    )

    for category in sorted(
        counts
    ):

        print(
            f"  {category:<12} "
            f"{counts[category]:>3} "
            "message(s)"
        )


def print_stats(
    messages: Sequence[Message],
) -> None:
    """
    Print runtime and catalogue statistics.
    """

    counts = Counter(
        message.category
        for message in messages
    )

    weights = sum(
        message.weight
        for message in messages
    )

    print(
        f"{APP_NAME} {VERSION}"
    )

    print(
        f"Messages:         "
        f"{len(messages)}"
    )

    print(
        f"Categories:       "
        f"{len(counts)}"
    )

    print(
        f"Total weight:     "
        f"{weights:.2f}"
    )

    print(
        f"Python:           "
        f"{sys.version.split()[0]}"
    )

    print(
        f"Logical CPUs:     "
        f"{os.cpu_count() or 'unknown'}"
    )

    print(
        "Interactive TTY:  "
        + (
            "yes"
            if sys.stdout.isatty()
            else "no"
        )
    )


def emit_messages(
    engine: LoadingMessageEngine,
    *,
    count: int,
    interval: float,
    json_lines: bool,
) -> None:
    """
    Emit normal non-progress messages.
    """

    if count < 1:
        raise ValueError(
            "count must be at least 1."
        )

    if interval < 0:
        raise ValueError(
            "interval cannot be negative."
        )

    for index in range(
        1,
        count + 1,
    ):

        message = (
            engine.next()
        )

        if json_lines:

            payload = {
                "index": index,
                "timestamp": (
                    datetime.now(
                        timezone.utc
                    ).isoformat()
                ),
                **asdict(
                    message
                ),
            }

            print(
                json.dumps(
                    payload,
                    ensure_ascii=False,
                )
            )

        else:

            print(
                message.text
            )

        if (
            interval
            and index != count
        ):

            time.sleep(
                interval
            )


def build_parser() -> argparse.ArgumentParser:
    """
    Build command-line argument parser.
    """

    parser = argparse.ArgumentParser(
        prog="funny-loader",
        description=(
            "Generate funny loading messages "
            "or display an animated simulated "
            "progress bar."
        ),
    )

    parser.add_argument(
        "-n",
        "--count",
        type=int,
        default=1,
        help=(
            "number of messages to print "
            "in normal mode "
            "(default: 1)"
        ),
    )

    parser.add_argument(
        "-i",
        "--interval",
        type=float,
        default=0.0,
        help=(
            "seconds between messages "
            "in normal mode "
            "(default: 0)"
        ),
    )

    parser.add_argument(
        "-c",
        "--category",
        action="append",
        help=(
            "filter by category; "
            "repeat the option or use "
            "comma-separated names"
        ),
    )

    parser.add_argument(
        "--seed",
        type=int,
        help=(
            "deterministic random seed "
            "for reproducible output"
        ),
    )

    parser.add_argument(
        "--no-repeat-window",
        type=int,
        default=5,
        help=(
            "avoid recently shown messages "
            "(default: 5)"
        ),
    )

    parser.add_argument(
        "--messages-file",
        type=Path,
        help=(
            "JSON file containing additional "
            "message strings or message objects"
        ),
    )

    parser.add_argument(
        "--replace-defaults",
        action="store_true",
        help=(
            "use only --messages-file entries "
            "instead of built-in messages"
        ),
    )

    parser.add_argument(
        "--progress",
        metavar="SECONDS",
        type=float,
        help=(
            "show a simulated animated "
            "progress bar for the given duration"
        ),
    )

    parser.add_argument(
        "--message-interval",
        type=float,
        default=2.5,
        help=(
            "seconds before changing text "
            "in progress mode "
            "(default: 2.5)"
        ),
    )

    parser.add_argument(
        "--bar-width",
        type=int,
        default=30,
        help=(
            "progress-bar width "
            "in characters "
            "(default: 30)"
        ),
    )

    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_lines",
        help=(
            "emit one JSON object "
            "per message in normal mode"
        ),
    )

    parser.add_argument(
        "--list-categories",
        action="store_true",
        help=(
            "show available categories "
            "and exit"
        ),
    )

    parser.add_argument(
        "--stats",
        action="store_true",
        help=(
            "show catalogue/runtime "
            "statistics and exit"
        ),
    )

    parser.add_argument(
        "--version",
        action="version",
        version=(
            f"%(prog)s {VERSION}"
        ),
    )

    return parser


def main(
    argv: Optional[
        Sequence[str]
    ] = None,
) -> int:
    """
    Main program entry point.
    """

    parser = (
        build_parser()
    )

    args = parser.parse_args(
        argv
    )

    try:

        custom_messages: tuple[
            Message,
            ...
        ] = ()

        if (
            args.messages_file
            is not None
        ):

            custom_messages = (
                load_custom_messages(
                    args.messages_file
                )
            )

        if args.replace_defaults:

            if not custom_messages:

                raise ValueError(
                    "--replace-defaults "
                    "requires "
                    "--messages-file."
                )

            catalogue = (
                custom_messages
            )

        else:

            catalogue = (
                MESSAGES
                + custom_messages
            )

        catalogue = (
            deduplicate_messages(
                catalogue
            )
        )

        if args.list_categories:

            print_categories(
                catalogue
            )

            return 0

        if args.stats:

            print_stats(
                catalogue
            )

            return 0

        if (
            args.progress
            is not None
            and args.json_lines
        ):

            raise ValueError(
                "--json cannot be "
                "combined with "
                "--progress."
            )

        categories = (
            parse_categories(
                args.category
            )
        )

        engine = (
            LoadingMessageEngine(
                catalogue,
                seed=args.seed,
                categories=categories,
                no_repeat_window=(
                    args.no_repeat_window
                ),
            )
        )

        if (
            args.progress
            is not None
        ):

            renderer = (
                ProgressRenderer(
                    engine,
                    duration=(
                        args.progress
                    ),
                    message_interval=(
                        args.message_interval
                    ),
                    width=(
                        args.bar_width
                    ),
                )
            )

            renderer.run()

        else:

            emit_messages(
                engine,
                count=args.count,
                interval=args.interval,
                json_lines=(
                    args.json_lines
                ),
            )

        return 0

    except ValueError as exc:

        parser.error(
            str(exc)
        )

        return 2

    except KeyboardInterrupt:

        if sys.stdout.isatty():
            sys.stdout.write(
                "\n"
            )

        print(
            "Interrupted.",
            file=sys.stderr,
        )

        return 130


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
