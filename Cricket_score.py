#!/usr/bin/env python3
"""
Cricbuzz live-score desktop notifier.

Install:
    pip install requests beautifulsoup4 lxml win10toast

Run once:
    python cricket_notifier.py --once

Keep watching every 60 seconds:
    python cricket_notifier.py --interval 60

Only show matches containing a team name:
    python cricket_notifier.py --team England
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

import requests
from bs4 import BeautifulSoup
from win10toast import ToastNotifier


URL = "https://www.cricbuzz.com/cricket-match/live-scores"
STATE_FILE = Path("cricket_notifier_state.json")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/120 Safari/537.36"
    ),
    "Accept-Language": "en-GB,en;q=0.9",
}


@dataclass(frozen=True)
class Match:
    match_id: str
    title: str
    details: str
    url: str

    @property
    def fingerprint(self) -> str:
        """Changes whenever the displayed score/status changes."""
        return hashlib.sha256(
            f"{self.title}|{self.details}".encode("utf-8")
        ).hexdigest()


def clean_text(value: str) -> str:
    return " ".join(value.split())


def load_previous_state() -> dict[str, str]:
    if not STATE_FILE.exists():
        return {}

    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logging.warning("Could not read previous state; starting fresh.")
        return {}


def save_state(matches: Iterable[Match]) -> None:
    state = {match.match_id: match.fingerprint for match in matches}

    try:
        STATE_FILE.write_text(
            json.dumps(state, indent=2),
            encoding="utf-8",
        )
    except OSError as error:
        logging.warning("Could not save state: %s", error)


def fetch_html(session: requests.Session) -> str:
    response = session.get(URL, headers=HEADERS, timeout=20)
    response.raise_for_status()
    return response.text


def extract_matches(html: str) -> list[Match]:
    soup = BeautifulSoup(html, "lxml")
    matches: list[Match] = []

    # Cricbuzz groups individual fixtures inside these match-list containers.
    for card in soup.select("div.cb-mtch-lst"):
        score_link = card.select_one('a[href*="/live-cricket-score/"]')

        if score_link is None:
            continue

        relative_url = score_link.get("href", "")
        match_url = f"https://www.cricbuzz.com{relative_url}"

        # Pull the full card text so score, result, and innings state stay together.
        card_text = clean_text(card.get_text(" ", strip=True))

        # Remove repetitive navigation labels that do not describe the match.
        for label in ("Live Score |", "Scorecard |", "Full Commentary |", "News"):
            card_text = card_text.replace(label, "")

        card_text = clean_text(card_text)

        # A readable title is normally the first useful link text in the match card.
        title = clean_text(score_link.get_text(" ", strip=True))
        if not title or title.lower() == "live score":
            title = "Cricket match update"

        match_id = hashlib.md5(match_url.encode("utf-8")).hexdigest()

        matches.append(
            Match(
                match_id=match_id,
                title=title,
                details=card_text[:240],
                url=match_url,
            )
        )

    return matches


def notify(toaster: ToastNotifier, match: Match) -> None:
    message = match.details or "A cricket score update is available."

    print(f"\n{match.title}\n{message}\n{match.url}")

    toaster.show_toast(
        title=match.title[:64],
        msg=message[:250],
        duration=10,
        threaded=True,
    )


def run_check(
    session: requests.Session,
    toaster: ToastNotifier,
    team_filter: str | None,
    notify_first_run: bool,
    previous_state: dict[str, str],
) -> list[Match]:
    html = fetch_html(session)
    matches = extract_matches(html)

    if team_filter:
        team_filter = team_filter.casefold()
        matches = [
            match
            for match in matches
            if team_filter in f"{match.title} {match.details}".casefold()
        ]

    if not matches:
        print("No matching live/recent fixtures found.")
        return []

    for match in matches:
        has_changed = previous_state.get(match.match_id) != match.fingerprint
        is_new = match.match_id not in previous_state

        if has_changed and (notify_first_run or not is_new):
            notify(toaster, match)

    return matches


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Show Cricbuzz score updates as Windows notifications."
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=60,
        help="Seconds between checks; default: 60.",
    )
    parser.add_argument(
        "--team",
        help="Only notify about matches containing this team name.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Check once and exit.",
    )
    parser.add_argument(
        "--notify-first",
        action="store_true",
        help="Also notify for all matches found on the first check.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.interval < 30:
        raise SystemExit("--interval must be at least 30 seconds.")

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    toaster = ToastNotifier()
    previous_state = load_previous_state()

    with requests.Session() as session:
        while True:
            try:
                matches = run_check(
                    session=session,
                    toaster=toaster,
                    team_filter=args.team,
                    notify_first_run=args.notify_first,
                    previous_state=previous_state,
                )

                if matches:
                    save_state(matches)
                    previous_state = {
                        match.match_id: match.fingerprint
                        for match in matches
                    }

            except requests.RequestException as error:
                logging.error("Could not reach Cricbuzz: %s", error)
            except Exception as error:
                logging.exception("Unexpected error: %s", error)

            if args.once:
                break

            time.sleep(args.interval)


if __name__ == "__main__":
    main()
