"""
Wikipedia Explorer
Modern Python 3 command-line Wikipedia search tool.

Created from an older Python 2 script and improved with:
- Safe input validation
- Search and random article modes
- Disambiguation handling
- Summary or full article display
- Optional article saving
- Configurable Wikipedia language
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import wikipedia as wiki
from wikipedia.exceptions import DisambiguationError, PageError


MAX_SEARCH_RESULTS = 10
SAVE_DIRECTORY = Path("wikipedia_articles")


def line(char: str = "-", length: int = 70) -> None:
    print(char * length)


def get_integer(prompt: str, minimum: int, maximum: int) -> int:
    """Ask for an integer until the user enters a valid value."""
    while True:
        try:
            value = int(input(prompt).strip())

            if minimum <= value <= maximum:
                return value

            print(f"Please enter a number between {minimum} and {maximum}.")
        except ValueError:
            print("Invalid input. Please enter a whole number.")


def get_yes_no(prompt: str) -> bool:
    """Return True for yes and False for no."""
    while True:
        answer = input(f"{prompt} (y/n): ").strip().lower()

        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no"):
            return False

        print("Please enter y or n.")


def safe_filename(title: str) -> str:
    """Create a Windows-safe filename from an article title."""
    filename = re.sub(r'[<>:"/\\|?*]', "_", title)
    filename = re.sub(r"\s+", "_", filename.strip())
    return filename[:100] + ".txt"


def print_article_list(items: list[str]) -> None:
    """Print numbered search or random article results."""
    line()
    for index, title in enumerate(items, start=1):
        print(f"{index}. {title}")
    line()


def resolve_page(title: str) -> Optional[wiki.WikipediaPage]:
    """
    Fetch a Wikipedia page.
    If the title is ambiguous, allow the user to select a matching article.
    """
    current_title = title

    for _ in range(5):
        try:
            return wiki.page(current_title, auto_suggest=False)

        except DisambiguationError as error:
            print(f'\n"{current_title}" has several possible meanings.')

            options = error.options[:MAX_SEARCH_RESULTS]
            print_article_list(options)

            selection = get_integer(
                "Choose the correct article number: ",
                1,
                len(options),
            )
            current_title = options[selection - 1]

        except PageError:
            print(f'\nNo Wikipedia page was found for "{current_title}".')
            return None

        except Exception as error:
            print(f"\nCould not retrieve the article: {error}")
            return None

    print("\nToo many disambiguation attempts.")
    return None


def build_article_text(page: wiki.WikipediaPage, full_article: bool) -> str:
    """Create formatted plain text for displaying or saving."""
    line_text = "=" * 70

    article = (
        f"{line_text}\n"
        f"{page.title}\n"
        f"{line_text}\n\n"
        f"Page ID: {page.pageid}\n"
        f"URL: {page.url}\n\n"
    )

    if full_article:
        article += page.content.strip()
    else:
        article += page.summary.strip()

    return article


def save_article(page: wiki.WikipediaPage, full_article: bool) -> None:
    """Save an article summary or full content into a text file."""
    SAVE_DIRECTORY.mkdir(exist_ok=True)

    file_path = SAVE_DIRECTORY / safe_filename(page.title)
    article_text = build_article_text(page, full_article)

    try:
        file_path.write_text(article_text, encoding="utf-8")
        print(f"\nSaved article to:\n{file_path.resolve()}")
    except OSError as error:
        print(f"\nCould not save the file: {error}")


def display_page(page: wiki.WikipediaPage) -> None:
    """Ask whether to show a summary or full page, then display it."""
    print("\n1. Summary")
    print("2. Full article")

    choice = get_integer("Choose page type: ", 1, 2)
    full_article = choice == 2

    print()
    print(build_article_text(page, full_article))
    print()

    if get_yes_no("Save this article as a text file"):
        save_article(page, full_article)


def search_wikipedia() -> None:
    """Search Wikipedia and open a selected result."""
    query = input("\nWikipedia search: ").strip()

    if not query:
        print("Search cannot be empty.")
        return

    try:
        results = wiki.search(query, results=MAX_SEARCH_RESULTS)
    except Exception as error:
        print(f"Search failed: {error}")
        return

    if not results:
        print("No matching Wikipedia articles found.")
        return

    print_article_list(results)

    selection = get_integer(
        "Choose an article number: ",
        1,
        len(results),
    )

    page = resolve_page(results[selection - 1])

    if page:
        display_page(page)


def random_wikipedia() -> None:
    """Get random Wikipedia pages and open a selected one."""
    number = get_integer(
        f"\nHow many random pages? (1-{MAX_SEARCH_RESULTS}): ",
        1,
        MAX_SEARCH_RESULTS,
    )

    try:
        random_titles = wiki.random(pages=number)

        if isinstance(random_titles, str):
            random_titles = [random_titles]

    except Exception as error:
        print(f"Could not retrieve random pages: {error}")
        return

    if not random_titles:
        print("No random pages were returned.")
        return

    print_article_list(random_titles)

    selection = get_integer(
        "Choose an article number: ",
        1,
        len(random_titles),
    )

    page = resolve_page(random_titles[selection - 1])

    if page:
        display_page(page)


def change_language() -> None:
    """Set the Wikipedia language code."""
    print("\nExamples: en, fr, de, es, it, ja, zh")

    language = input("Enter Wikipedia language code: ").strip().lower()

    if not language:
        print("Language code cannot be empty.")
        return

    try:
        wiki.set_lang(language)
        print(f'Wikipedia language changed to "{language}".')
    except Exception as error:
        print(f"Could not change language: {error}")


def main() -> None:
    """Run the interactive Wikipedia Explorer."""
    wiki.set_lang("en")

    while True:
        line("=")
        print("            WIKIPEDIA EXPLORER")
        line("=")
        print("1. Search Wikipedia")
        print("2. Open random Wikipedia articles")
        print("3. Change language")
        print("4. Exit")

        choice = get_integer("\nChoose an option: ", 1, 4)

        if choice == 1:
            search_wikipedia()

        elif choice == 2:
            random_wikipedia()

        elif choice == 3:
            change_language()

        else:
            print("\nThanks for using Wikipedia Explorer.")
            break


if __name__ == "__main__":
    main()
