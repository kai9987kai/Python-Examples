"""
Magic 8 Ball Game
Python 3.5+
Requirement:
    pip install colorama
"""

from __future__ import print_function

import random
import sys
import time

from colorama import Fore, Style, init


# Automatically reset terminal colours after each print.
init(autoreset=True)


RESPONSES = {
    "positive": [
        "It is certain.",
        "It is decidedly so.",
        "Without a doubt.",
        "Yes, definitely.",
        "You may rely on it.",
        "As I see it, yes.",
        "Most likely.",
        "Outlook good.",
        "Yes.",
        "Signs point to yes."
    ],
    "neutral": [
        "Ask again later.",
        "Better not tell you now.",
        "Cannot predict now.",
        "Concentrate and ask again.",
        "The future is unclear."
    ],
    "negative": [
        "Don't count on it.",
        "My reply is no.",
        "My sources say no.",
        "Outlook not so good.",
        "Very doubtful."
    ]
}

CATEGORY_COLOURS = {
    "positive": Fore.GREEN,
    "neutral": Fore.YELLOW,
    "negative": Fore.RED
}


def thinking_animation():
    """Display a short thinking animation."""
    print(Fore.CYAN + "\nConsulting the Magic 8 Ball", end="")
    for _ in range(3):
        time.sleep(0.45)
        print(".", end="")
    print("\n")


def get_answer():
    """Return a random answer and its category."""
    category = random.choice(list(RESPONSES.keys()))
    answer = random.choice(RESPONSES[category])
    return category, answer


def ask_question():
    """Collect and validate a question from the player."""
    while True:
        question = input(Fore.WHITE + "Ask the Magic 8 Ball a question: ").strip()

        if question.lower() in ("quit", "exit", "q"):
            return None

        if question:
            return question

        print(Fore.YELLOW + "Please type a question, or enter 'quit' to leave.\n")


def play_again():
    """Ask whether the player wants another prediction."""
    while True:
        choice = input(
            Fore.WHITE + "\nAsk another question? (y/n): "
        ).strip().lower()

        if choice in ("y", "yes"):
            return True

        if choice in ("n", "no", "quit", "exit"):
            return False

        print(Fore.YELLOW + "Please enter y or n.")


def game():
    """Run the main Magic 8 Ball game loop."""
    questions_asked = 0

    print(Fore.MAGENTA + Style.BRIGHT + "\n=== MAGIC 8 BALL ===")
    print(Fore.CYAN + "Ask a question and discover your possible future.")
    print(Fore.CYAN + "Type 'quit' at any time to exit.\n")

    while True:
        question = ask_question()

        if question is None:
            break

        thinking_animation()

        category, answer = get_answer()
        colour = CATEGORY_COLOURS[category]

        print(
            colour + Style.BRIGHT +
            "Magic 8 Ball says: " + answer
        )

        questions_asked += 1

        if not play_again():
            break

    print(
        Fore.MAGENTA +
        "\nAuf Wiedersehen! You asked {0} question(s).".format(questions_asked)
    )


if __name__ == "__main__":
    try:
        game()
    except KeyboardInterrupt:
        print(Fore.YELLOW + "\n\nMagic 8 Ball closed. Goodbye!")
        sys.exit(0)
