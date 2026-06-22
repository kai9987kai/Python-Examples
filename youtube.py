#!/usr/bin/env python3
"""
play_song.py

Open a YouTube search in the default web browser.

Usage:
    python play_song.py "Daft Punk One More Time"
    python play_song.py
    python play_song.py --print-url "lofi hip hop"
"""

from __future__ import annotations

import argparse
import sys
import webbrowser
from urllib.parse import quote_plus


YOUTUBE_SEARCH_URL = "https://www.youtube.com/results?search_query={query}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Search YouTube and open the results in your browser."
    )

    parser.add_argument(
        "query",
        nargs="*",
        help="Song, artist, video, or search phrase."
    )

    parser.add_argument(
        "--print-url",
        action="store_true",
        help="Print the generated YouTube URL."
    )

    parser.add_argument(
        "--no-open",
        action="store_true",
        help="Do not open a browser; useful for testing."
    )

    return parser.parse_args()


def get_query(arguments: argparse.Namespace) -> str:
    query = " ".join(arguments.query).strip()

    if not query:
        try:
            query = input("Enter the song or video to search for: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nSearch cancelled.")
            sys.exit(1)

    if not query:
        print("Please enter a song, artist, or video name.")
        sys.exit(1)

    return query


def main() -> int:
    args = parse_args()
    query = get_query(args)

    encoded_query = quote_plus(query)
    url = YOUTUBE_SEARCH_URL.format(query=encoded_query)

    if args.print_url:
        print(url)

    if args.no_open:
        return 0

    opened = webbrowser.open_new_tab(url)

    if not opened:
        print("Could not open a browser automatically.")
        print(f"Copy this URL into your browser:\n{url}")
        return 1

    print(f'Opened YouTube results for: "{query}"')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
