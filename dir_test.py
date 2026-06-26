#!/usr/bin/env python3
"""
Script Name: dir_test.py
Description: Check whether a directory exists and optionally create it.
"""

from pathlib import Path


def get_directory_path() -> Path:
    """Ask the user for a directory path and return an expanded Path object."""
    while True:
        user_input = input("Enter the directory path to check: ").strip()

        if not user_input:
            print("Please enter a directory path.")
            continue

        return Path(user_input).expanduser()


def check_or_create_directory(directory: Path) -> None:
    """Check whether a directory exists; create it if needed."""
    try:
        if directory.exists():
            if directory.is_dir():
                print(f"\nDirectory already exists:\n  {directory.resolve()}")
            else:
                print(
                    f"\nA file already exists at this location, so a directory "
                    f"cannot be created:\n  {directory.resolve()}"
                )
            return

        print(f"\nDirectory does not exist:\n  {directory}")

        answer = input("Create it? [y/N]: ").strip().lower()
        if answer not in {"y", "yes"}:
            print("No changes made.")
            return

        directory.mkdir(parents=True, exist_ok=True)
        print(f"\nDirectory created successfully:\n  {directory.resolve()}")

    except PermissionError:
        print("\nPermission denied. Try a location you are allowed to modify.")
    except OSError as error:
        print(f"\nCould not create or inspect the directory: {error}")


def main() -> None:
    print("Directory Checker")
    print("-" * 30)

    directory = get_directory_path()
    check_or_create_directory(directory)


if __name__ == "__main__":
    main()
