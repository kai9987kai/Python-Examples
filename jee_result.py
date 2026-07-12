#!/usr/bin/env python3
"""
Authorised examination-result checker.

Checks one registration number and one known date of birth.
It does not enumerate or guess personal information.
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import Final

import requests
from bs4 import BeautifulSoup


DEFAULT_URL: Final = "https://results.cbse.nic.in/"
DATE_FORMAT: Final = "%d/%m/%Y"


@dataclass(frozen=True)
class Candidate:
    registration_number: str
    date_of_birth: str


class ResultLookupError(RuntimeError):
    """Raised when the result portal cannot be queried reliably."""


def validate_candidate(registration_number: str, date_of_birth: str) -> Candidate:
    registration_number = registration_number.strip()

    if not registration_number.isdigit():
        raise ValueError("The registration number must contain digits only.")

    if not 4 <= len(registration_number) <= 20:
        raise ValueError("The registration number has an unexpected length.")

    try:
        parsed_date = datetime.strptime(date_of_birth.strip(), DATE_FORMAT)
    except ValueError as exc:
        raise ValueError(
            f"Date of birth must use DD/MM/YYYY format, for example 10/03/1997."
        ) from exc

    return Candidate(
        registration_number=registration_number,
        date_of_birth=parsed_date.strftime(DATE_FORMAT),
    )


def create_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/150.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml",
        }
    )
    return session


def extract_hidden_fields(html: str) -> dict[str, str]:
    """Collect CSRF tokens and other hidden form fields."""
    soup = BeautifulSoup(html, "html.parser")
    form = soup.find("form")

    if form is None:
        raise ResultLookupError("No result lookup form was found.")

    fields: dict[str, str] = {}

    for element in form.select('input[type="hidden"][name]'):
        fields[element["name"]] = element.get("value", "")

    return fields


def result_appears_valid(html: str) -> bool:
    """
    Detect a successful response using page text rather than table counts.

    The exact phrases may need adjusting for the authorised portal.
    """
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True).casefold()

    failure_phrases = (
        "invalid roll number",
        "invalid registration number",
        "invalid date of birth",
        "record not found",
        "no result found",
    )

    success_phrases = (
        "candidate name",
        "result status",
        "marks obtained",
        "roll number",
    )

    if any(phrase in text for phrase in failure_phrases):
        return False

    return any(phrase in text for phrase in success_phrases)


def check_result(
    session: requests.Session,
    page_url: str,
    candidate: Candidate,
) -> bool:
    try:
        initial_response = session.get(page_url, timeout=(5, 20))
        initial_response.raise_for_status()

        payload = extract_hidden_fields(initial_response.text)
        payload.update(
            {
                # Confirm these field names using the authorised portal's form.
                "regno": candidate.registration_number,
                "dob": candidate.date_of_birth,
            }
        )

        response = session.post(
            page_url,
            data=payload,
            timeout=(5, 20),
        )
        response.raise_for_status()

    except requests.Timeout as exc:
        raise ResultLookupError("The result portal timed out.") from exc
    except requests.RequestException as exc:
        raise ResultLookupError(f"Portal request failed: {exc}") from exc

    return result_appears_valid(response.text)


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check one authorised examination result."
    )
    parser.add_argument(
        "--registration-number",
        required=True,
        help="Candidate registration or roll number.",
    )
    parser.add_argument(
        "--dob",
        required=True,
        help="Known date of birth in DD/MM/YYYY format.",
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_URL,
        help="Official result-page URL.",
    )
    return parser.parse_args()


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    args = parse_arguments()

    try:
        candidate = validate_candidate(args.registration_number, args.dob)
        session = create_session()

        found = check_result(session, args.url, candidate)

        if found:
            logging.info("A matching result response was detected.")
            return 0

        logging.warning("No matching result was detected.")
        return 1

    except (ValueError, ResultLookupError) as exc:
        logging.error("%s", exc)
        return 2


if __name__ == "__main__":
    sys.exit(main())
