#!/usr/bin/env python3
"""
Modern Search & Browser Launcher
================================

Inspired by:
    Author: Ankit Agarwal (ankit167)
    Original usage: python google.py <keyword>

Modernized features:
    - Python 3.10+
    - CLI argument parsing
    - Clipboard fallback
    - Configurable number of results
    - Search region selection
    - Safe Search control
    - Time filtering
    - Search backend selection
    - Google-specific backend option
    - Google browser-only mode
    - site: and -site: filtering
    - Result deduplication
    - URL validation
    - Tracking-parameter removal
    - Separate browser tabs
    - Configurable tab-opening delay
    - JSON export
    - Copy first result
    - Preview-only mode
    - Error handling
    - Dependency detection
    - No fragile BeautifulSoup CSS selectors
    - HTTPS only

Examples
--------

Basic:
    python google.py artificial intelligence

Quoted query:
    python google.py "WebGPU ONNX Runtime"

Open 10 results:
    python google.py "Blender geometry nodes" --limit 10

Ask DDGS specifically for its Google backend:
    python google.py "Python 3.14" --backend google

Only results from GitHub:
    python google.py "WebGPU renderer" --site github.com

Exclude Reddit:
    python google.py "Blender tutorial" --exclude-site reddit.com

Results from the last week:
    python google.py "WebGPU news" --timelimit w

Print results but don't open them:
    python google.py "local AI" --no-open

Export results:
    python google.py "local AI WebGPU" --no-open --json results.json

Copy first URL:
    python google.py "Bournemouth University" --copy-first

Open the normal Google Search page without programmatically retrieving results:
    python google.py "Bournemouth University" --google-page

Clipboard mode:
    Copy text, then run:
    python google.py

Dependencies
------------
Automatic result retrieval:
    python -m pip install -U ddgs

Optional improved clipboard support:
    python -m pip install -U pyperclip
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import webbrowser

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Sequence
from urllib.parse import (
    parse_qsl,
    urlencode,
    urlsplit,
    urlunsplit,
)


# ============================================================
# Configuration
# ============================================================

VERSION = "3.0.0"

DEFAULT_LIMIT = 5
DEFAULT_REGION = "uk-en"
DEFAULT_SAFE_SEARCH = "moderate"
DEFAULT_BACKEND = "auto"
DEFAULT_TAB_DELAY = 0.20

MAX_RESULTS = 50


# Common advertising/analytics parameters that can normally
# be removed without changing the destination resource.
TRACKING_PARAMETERS = {
    "gclid",
    "dclid",
    "fbclid",
    "msclkid",
    "mc_cid",
    "mc_eid",
    "igshid",
    "ref_src",
}


# ============================================================
# Data model
# ============================================================

@dataclass(
    frozen=True,
    slots=True,
)
class SearchResult:
    """
    Represents one sanitized search result.
    """

    rank: int
    title: str
    url: str
    snippet: str = ""


# ============================================================
# Argument validation
# ============================================================

def positive_int(value: str) -> int:
    """
    Validate a positive integer result count.
    """

    try:
        number = int(value)

    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "must be an integer"
        ) from exc

    if number < 1:
        raise argparse.ArgumentTypeError(
            "must be at least 1"
        )

    if number > MAX_RESULTS:
        raise argparse.ArgumentTypeError(
            f"must not exceed {MAX_RESULTS}"
        )

    return number


def non_negative_float(value: str) -> float:
    """
    Validate a non-negative floating point number.
    """

    try:
        number = float(value)

    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "must be a number"
        ) from exc

    if number < 0:
        raise argparse.ArgumentTypeError(
            "must be zero or greater"
        )

    return number


# ============================================================
# CLI
# ============================================================

def build_parser() -> argparse.ArgumentParser:
    """
    Construct the command-line parser.
    """

    parser = argparse.ArgumentParser(
        prog="google.py",
        description=(
            "Search the web, display the highest-ranked results, "
            "and optionally open them in separate browser tabs. "
            "If no query is supplied, clipboard text is used."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument(
        "query",
        nargs="*",
        help=(
            "Search query. If omitted, text is read "
            "from the clipboard."
        ),
    )

    parser.add_argument(
        "-n",
        "--limit",
        type=positive_int,
        default=DEFAULT_LIMIT,
        help=(
            "Maximum number of unique results "
            "to return and open."
        ),
    )

    parser.add_argument(
        "--region",
        default=DEFAULT_REGION,
        help=(
            "Search region/language code, for example "
            "uk-en, us-en, de-de or fr-fr."
        ),
    )

    parser.add_argument(
        "--safe",
        choices=(
            "on",
            "moderate",
            "off",
        ),
        default=DEFAULT_SAFE_SEARCH,
        help="Safe-search filtering level.",
    )

    parser.add_argument(
        "--timelimit",
        choices=(
            "d",
            "w",
            "m",
            "y",
        ),
        help=(
            "Restrict results to the last "
            "day, week, month or year."
        ),
    )

    parser.add_argument(
        "--backend",
        default=DEFAULT_BACKEND,
        help=(
            "DDGS search backend. "
            "'auto' is generally most resilient. "
            "Use 'google' to request Google's backend "
            "specifically where available."
        ),
    )

    parser.add_argument(
        "--site",
        action="append",
        default=[],
        metavar="DOMAIN",
        help=(
            "Restrict results to a domain. "
            "May be supplied multiple times."
        ),
    )

    parser.add_argument(
        "--exclude-site",
        action="append",
        default=[],
        metavar="DOMAIN",
        help=(
            "Exclude results from a domain. "
            "May be supplied multiple times."
        ),
    )

    parser.add_argument(
        "--delay",
        type=non_negative_float,
        default=DEFAULT_TAB_DELAY,
        help=(
            "Delay in seconds between opening "
            "browser tabs."
        ),
    )

    parser.add_argument(
        "--no-open",
        action="store_true",
        help=(
            "Display results without opening "
            "browser tabs."
        ),
    )

    parser.add_argument(
        "--copy-first",
        action="store_true",
        help=(
            "Copy the first result URL "
            "to the clipboard."
        ),
    )

    parser.add_argument(
        "--json",
        type=Path,
        metavar="FILE",
        help=(
            "Export structured result data "
            "to a UTF-8 JSON file."
        ),
    )

    parser.add_argument(
        "--google-page",
        action="store_true",
        help=(
            "Skip programmatic search retrieval and "
            "simply open the encoded Google Search page."
        ),
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {VERSION}",
    )

    return parser


# ============================================================
# Clipboard
# ============================================================

def get_clipboard_text() -> str:
    """
    Retrieve text from the clipboard.

    First tries pyperclip because it provides a clean
    cross-platform abstraction.

    Falls back to tkinter when pyperclip isn't installed.
    """

    try:
        import pyperclip

        value = pyperclip.paste()

        if isinstance(value, str):
            value = value.strip()

            if value:
                return value

    except Exception:
        pass

    try:
        import tkinter as tk

        root = tk.Tk()

        root.withdraw()

        try:
            value = root.clipboard_get()

        finally:
            root.destroy()

        if isinstance(value, str):
            value = value.strip()

            if value:
                return value

    except Exception:
        pass

    return ""


def set_clipboard_text(text: str) -> bool:
    """
    Write text to the system clipboard.
    """

    try:
        import pyperclip

        pyperclip.copy(text)

        return True

    except Exception:
        pass

    try:
        import tkinter as tk

        root = tk.Tk()

        root.withdraw()

        root.clipboard_clear()

        root.clipboard_append(text)

        # Required to ensure clipboard data survives
        # after the Tk window is destroyed.
        root.update()

        root.destroy()

        return True

    except Exception:
        return False


# ============================================================
# Query processing
# ============================================================

def normalize_domain(value: str) -> str:
    """
    Convert a URL/domain into a search-operator-safe domain.
    """

    value = value.strip().lower()

    prefixes = (
        "https://",
        "http://",
    )

    for prefix in prefixes:

        if value.startswith(prefix):
            value = value[len(prefix):]

    return value.strip(" /")


def compose_query(
    base_query: str,
    sites: Sequence[str],
    excluded_sites: Sequence[str],
) -> str:
    """
    Add site restrictions to the query.
    """

    components: list[str] = [
        base_query.strip(),
    ]

    for site in sites:

        normalized = normalize_domain(site)

        if normalized:
            components.append(
                f"site:{normalized}"
            )

    for site in excluded_sites:

        normalized = normalize_domain(site)

        if normalized:
            components.append(
                f"-site:{normalized}"
            )

    return " ".join(
        component
        for component in components
        if component
    )


# ============================================================
# URL processing
# ============================================================

def clean_url(url: str) -> str | None:
    """
    Validate a URL and remove common tracking parameters.

    Only HTTP and HTTPS URLs are accepted.
    """

    url = url.strip()

    if not url:
        return None

    try:
        parts = urlsplit(url)

    except ValueError:
        return None

    if parts.scheme not in {
        "http",
        "https",
    }:
        return None

    if not parts.netloc:
        return None

    cleaned_query: list[tuple[str, str]] = []

    for key, value in parse_qsl(
        parts.query,
        keep_blank_values=True,
    ):

        normalized_key = key.lower()

        if normalized_key.startswith("utm_"):
            continue

        if normalized_key in TRACKING_PARAMETERS:
            continue

        cleaned_query.append(
            (
                key,
                value,
            )
        )

    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            parts.path or "/",
            urlencode(
                cleaned_query,
                doseq=True,
            ),
            "",
        )
    )


def dedupe_key(url: str) -> str:
    """
    Produce a normalized URL key for duplicate detection.
    """

    parts = urlsplit(url)

    host = parts.netloc.lower()

    if host.startswith("www."):
        host = host[4:]

    path = parts.path.rstrip("/")

    if not path:
        path = "/"

    return urlunsplit(
        (
            parts.scheme.lower(),
            host,
            path,
            parts.query,
            "",
        )
    )


# ============================================================
# Search engine
# ============================================================

def fetch_results(
    query: str,
    *,
    limit: int,
    region: str,
    safe: str,
    timelimit: str | None,
    backend: str,
) -> list[SearchResult]:
    """
    Retrieve and normalize search results using DDGS.
    """

    try:
        from ddgs import DDGS

    except ImportError as exc:

        raise RuntimeError(
            "Automatic result retrieval requires the "
            "'ddgs' package.\n"
            "\n"
            "Install it with:\n"
            "    python -m pip install -U ddgs"
        ) from exc

    # Fetch additional candidates because some may be
    # invalid or duplicates after normalization.
    candidate_count = min(
        max(
            limit * 3,
            limit,
        ),
        MAX_RESULTS,
    )

    try:
        search_engine = DDGS(
            timeout=10,
        )

        raw_results = search_engine.text(
            query,
            region=region,
            safesearch=safe,
            timelimit=timelimit,
            max_results=candidate_count,
            backend=backend,
        )

    except Exception as exc:

        raise RuntimeError(
            f"Search request failed: {exc}"
        ) from exc

    results: list[SearchResult] = []

    seen: set[str] = set()

    for raw in raw_results or []:

        if not isinstance(raw, dict):
            continue

        raw_url = str(
            raw.get("href")
            or raw.get("url")
            or ""
        ).strip()

        url = clean_url(
            raw_url
        )

        if not url:
            continue

        key = dedupe_key(
            url
        )

        if key in seen:
            continue

        seen.add(
            key
        )

        title = str(
            raw.get("title")
            or url
        ).strip()

        snippet = str(
            raw.get("body")
            or raw.get("description")
            or ""
        ).strip()

        result = SearchResult(
            rank=len(results) + 1,
            title=title,
            url=url,
            snippet=snippet,
        )

        results.append(
            result
        )

        if len(results) >= limit:
            break

    return results


# ============================================================
# Google browser mode
# ============================================================

def google_search_url(
    query: str,
) -> str:
    """
    Generate a properly encoded Google Search URL.
    """

    parameters = {
        "q": query,
    }

    return (
        "https://www.google.com/search?"
        + urlencode(parameters)
    )


# ============================================================
# Terminal output
# ============================================================

def compact_text(
    text: str,
    maximum_length: int = 220,
) -> str:
    """
    Collapse whitespace and truncate long snippets.
    """

    text = " ".join(
        text.split()
    )

    if len(text) <= maximum_length:
        return text

    return (
        text[:maximum_length - 3]
        .rstrip()
        + "..."
    )


def print_results(
    query: str,
    results: Iterable[SearchResult],
) -> None:
    """
    Display results in the terminal.
    """

    results = list(
        results
    )

    print()
    print("=" * 72)

    print(
        f"QUERY: {query}"
    )

    print(
        f"RESULTS: {len(results)}"
    )

    print("=" * 72)
    print()

    for result in results:

        print(
            f"[{result.rank}] {result.title}"
        )

        print(
            f"    {result.url}"
        )

        if result.snippet:

            print(
                "    "
                + compact_text(
                    result.snippet
                )
            )

        print()


# ============================================================
# Browser
# ============================================================

def open_tabs(
    results: Sequence[SearchResult],
    delay: float,
) -> int:
    """
    Open each result in a new browser tab.
    """

    opened = 0

    for result in results:

        try:
            success = webbrowser.open_new_tab(
                result.url
            )

            if success:
                opened += 1

        except webbrowser.Error as exc:

            print(
                (
                    "Warning: could not open "
                    f"{result.url}: {exc}"
                ),
                file=sys.stderr,
            )

        if delay:
            time.sleep(
                delay
            )

    return opened


# ============================================================
# JSON export
# ============================================================

def write_json(
    path: Path,
    query: str,
    results: Sequence[SearchResult],
) -> None:
    """
    Export search results as structured JSON.
    """

    payload = {
        "query": query,
        "result_count": len(results),
        "results": [
            asdict(result)
            for result in results
        ],
    }

    output_path = (
        path
        .expanduser()
        .resolve()
    )

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path.write_text(
        json.dumps(
            payload,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print(
        f"Saved JSON: {output_path}"
    )


# ============================================================
# Main application
# ============================================================

def main(
    argv: Sequence[str] | None = None,
) -> int:
    """
    Program entry point.
    """

    parser = build_parser()

    args = parser.parse_args(
        argv
    )

    # --------------------------------------------------------
    # Resolve query
    # --------------------------------------------------------

    if args.query:

        query = " ".join(
            args.query
        ).strip()

    else:

        query = get_clipboard_text()

        if query:

            print(
                f'Using clipboard query: "{query}"'
            )

    if not query:

        parser.error(
            "no search query was supplied and "
            "the clipboard is empty or unavailable"
        )

    # --------------------------------------------------------
    # Add optional site operators
    # --------------------------------------------------------

    query = compose_query(
        query,
        args.site,
        args.exclude_site,
    )

    # --------------------------------------------------------
    # Browser-only Google mode
    # --------------------------------------------------------

    if args.google_page:

        url = google_search_url(
            query
        )

        print()
        print(
            "Opening Google Search:"
        )
        print(
            url
        )

        try:

            success = webbrowser.open_new_tab(
                url
            )

        except webbrowser.Error as exc:

            print(
                f"Browser error: {exc}",
                file=sys.stderr,
            )

            return 3

        if success:
            return 0

        print(
            "The browser reported that the page "
            "could not be opened.",
            file=sys.stderr,
        )

        return 3

    # --------------------------------------------------------
    # Search
    # --------------------------------------------------------

    try:

        results = fetch_results(
            query,
            limit=args.limit,
            region=args.region,
            safe=args.safe,
            timelimit=args.timelimit,
            backend=args.backend,
        )

    except RuntimeError as exc:

        print(
            f"Error: {exc}",
            file=sys.stderr,
        )

        print(
            (
                "\nFallback:\n"
                "    python google.py "
                "--google-page "
                f"\"{query}\""
            ),
            file=sys.stderr,
        )

        return 2

    # --------------------------------------------------------
    # Validate returned results
    # --------------------------------------------------------

    if not results:

        print(
            "No usable search results were returned.",
            file=sys.stderr,
        )

        return 1

    # --------------------------------------------------------
    # Terminal output
    # --------------------------------------------------------

    print_results(
        query,
        results,
    )

    # --------------------------------------------------------
    # JSON export
    # --------------------------------------------------------

    if args.json:

        try:

            write_json(
                args.json,
                query,
                results,
            )

        except OSError as exc:

            print(
                (
                    "Warning: JSON export failed: "
                    f"{exc}"
                ),
                file=sys.stderr,
            )

    # --------------------------------------------------------
    # Clipboard output
    # --------------------------------------------------------

    if args.copy_first:

        first_url = results[0].url

        if set_clipboard_text(
            first_url
        ):

            print(
                "Copied first result URL "
                "to clipboard."
            )

        else:

            print(
                "Warning: clipboard copy failed.",
                file=sys.stderr,
            )

    # --------------------------------------------------------
    # Preview-only mode
    # --------------------------------------------------------

    if args.no_open:

        return 0

    # --------------------------------------------------------
    # Open browser tabs
    # --------------------------------------------------------

    opened = open_tabs(
        results,
        args.delay,
    )

    print(
        f"Opened {opened}/{len(results)} "
        "result(s) in browser tabs."
    )

    if opened == 0:
        return 3

    return 0


# ============================================================
# Entry point
# ============================================================

if __name__ == "__main__":
    raise SystemExit(
        main()
    )
