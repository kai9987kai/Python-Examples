from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class InputConfig:
    """
    Configuration for validated integer input.

    Attributes:
        minimum:
            Lowest accepted integer.

        maximum:
            Highest accepted integer.

        prompt:
            Text displayed when requesting input.

        default:
            Optional value returned when the user presses Enter
            without typing anything.

        allow_quit:
            Whether commands such as "q", "quit", and "exit"
            are accepted.

        menu:
            Optional mapping of integer values to menu descriptions.
    """

    minimum: int
    maximum: int
    prompt: str = "Enter your choice"
    default: int | None = None
    allow_quit: bool = True
    menu: Mapping[int, str] | None = None

    def __post_init__(self) -> None:
        if self.minimum > self.maximum:
            raise ValueError(
                f"minimum ({self.minimum}) cannot be greater "
                f"than maximum ({self.maximum})."
            )

        if self.default is not None:
            if not self.minimum <= self.default <= self.maximum:
                raise ValueError(
                    f"default ({self.default}) must be between "
                    f"{self.minimum} and {self.maximum}."
                )


def display_menu(menu: Mapping[int, str]) -> None:
    """
    Display a numbered menu.

    Example:
        1. Start
        2. Settings
        3. Exit
    """

    print()

    for number, description in sorted(menu.items()):
        print(f"  {number}. {description}")

    print()


def get_user_input(config: InputConfig) -> int | None:
    """
    Read and validate an integer from the command line.

    Returns:
        int:
            A valid integer between minimum and maximum,
            inclusive.

        None:
            Returned if quitting is enabled and the user enters
            q, quit, or exit.
    """

    if config.menu:
        display_menu(config.menu)

    quit_commands = {"q", "quit", "exit"}

    while True:
        # Build a useful prompt automatically.
        prompt_parts = [
            f"{config.prompt} "
            f"[{config.minimum}-{config.maximum}]"
        ]

        if config.default is not None:
            prompt_parts.append(
                f"(default: {config.default})"
            )

        if config.allow_quit:
            prompt_parts.append("(q to quit)")

        full_prompt = " ".join(prompt_parts) + ": "

        try:
            raw_input = input(full_prompt).strip()

        except (EOFError, KeyboardInterrupt):
            # Handle Ctrl+D / Ctrl+Z and Ctrl+C gracefully.
            print("\nInput cancelled.")

            if config.allow_quit:
                return None

            continue

        # ------------------------------------------------------
        # Empty input / default handling
        # ------------------------------------------------------

        if not raw_input:
            if config.default is not None:
                return config.default

            print(
                "Invalid input: you must enter a number."
            )
            continue

        # ------------------------------------------------------
        # Quit handling
        # ------------------------------------------------------

        if config.allow_quit:
            if raw_input.casefold() in quit_commands:
                return None

        # ------------------------------------------------------
        # Integer conversion
        # ------------------------------------------------------

        try:
            value = int(raw_input)

        except ValueError:
            print(
                f"Invalid input: {raw_input!r} is not an integer."
            )
            continue

        # ------------------------------------------------------
        # Range validation
        # ------------------------------------------------------

        if value < config.minimum:
            print(
                f"Value too small. "
                f"Enter {config.minimum} or greater."
            )
            continue

        if value > config.maximum:
            print(
                f"Value too large. "
                f"Enter {config.maximum} or less."
            )
            continue

        # ------------------------------------------------------
        # Menu validation
        # ------------------------------------------------------

        if config.menu is not None and value not in config.menu:
            valid_options = ", ".join(
                str(option)
                for option in sorted(config.menu)
            )

            print(
                "That number is not a valid menu option. "
                f"Valid choices: {valid_options}"
            )
            continue

        # All validation succeeded.
        return value


def main() -> None:
    menu = {
        1: "Start program",
        2: "Load project",
        3: "Settings",
        4: "View information",
        5: "Advanced options",
        6: "Exit",
    }

    config = InputConfig(
        minimum=1,
        maximum=6,
        prompt="Enter your choice",
        menu=menu,
        allow_quit=True,
    )

    choice = get_user_input(config)

    if choice is None:
        print("Program cancelled.")
        return

    match choice:
        case 1:
            print("Starting program...")

        case 2:
            print("Loading project...")

        case 3:
            print("Opening settings...")

        case 4:
            print("Displaying information...")

        case 5:
            print("Opening advanced options...")

        case 6:
            print("Exiting program...")

        case _:
            # Should never occur because validation has already
            # guaranteed a valid menu selection.
            raise RuntimeError(
                f"Unexpected validated choice: {choice}"
            )


if __name__ == "__main__":
    main()
