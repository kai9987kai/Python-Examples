"""
Cricbuzz Match Extractor
Fetches match cards from the Cricbuzz homepage and prints clean results.

Install:
    pip install requests beautifulsoup4
"""

from dataclasses import dataclass
from typing import List
import requests
from bs4 import BeautifulSoup


URL = "https://www.cricbuzz.com/"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/124 Safari/537.36"
    )
}
TIMEOUT_SECONDS = 15


@dataclass
class Match:
    title: str
    details: str


def fetch_page(url: str) -> str:
    """Download a webpage safely and return its HTML."""
    try:
        response = requests.get(url, headers=HEADERS, timeout=TIMEOUT_SECONDS)
        response.raise_for_status()
        return response.text
    except requests.RequestException as error:
        raise RuntimeError(f"Could not retrieve Cricbuzz: {error}") from error


def extract_matches(html: str) -> List[Match]:
    """Extract match titles and visible score/details from match cards."""
    page = BeautifulSoup(html, "html.parser")

    # Original Cricbuzz score-card selector, with fallbacks for layout changes.
    cards = page.select(
        "div.cb-col.cb-col-25.cb-mtch-blk, "
        "div.cb-mtch-lst, "
        "div.cb-col.cb-col-100.cb-mtch-lst"
    )

    matches: List[Match] = []
    seen = set()

    for card in cards:
        link = card.select_one("a[title]")

        if not link:
            continue

        title = link.get("title", "").strip()
        details = " ".join(card.stripped_strings)

        if not title or (title, details) in seen:
            continue

        seen.add((title, details))
        matches.append(Match(title=title, details=details))

    return matches


def print_matches(matches: List[Match]) -> None:
    """Print extracted matches in a readable format."""
    if not matches:
        print("No match cards found. Cricbuzz may have changed its page layout.")
        return

    print(f"\nFound {len(matches)} match card(s)\n")
    print("=" * 70)

    for number, match in enumerate(matches, start=1):
        print(f"{number}. {match.title}")
        print(f"   {match.details}")
        print("-" * 70)


def main() -> None:
    html = fetch_page(URL)
    matches = extract_matches(html)
    print_matches(matches)


if __name__ == "__main__":
    main()
