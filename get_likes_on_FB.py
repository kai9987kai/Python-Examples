#!/usr/bin/env python3
"""
Modern Facebook / Meta Graph API Post Exporter
================================================

Features
--------
- Python 3
- Meta Graph API v26.0
- Secure Bearer authentication
- Access token stored in environment variable
- Optional appsecret_proof
- Cursor-based pagination
- Automatic retries and exponential backoff
- Likes, reactions, comments and share counts
- Post message and permalink
- TSV output
- Can retrieve more than the old 100-post limit

Install dependency
------------------

    python -m pip install requests

PowerShell example
------------------

    $env:FB_ACCESS_TOKEN = "YOUR_ACCESS_TOKEN"

    python facebook_posts.py me

Export 500 posts:

    python facebook_posts.py me --max-posts 500

Save to a file:

    python facebook_posts.py me --max-posts 500 --output facebook_posts.tsv

If your Meta application has "Require App Secret" enabled:

    $env:FB_APP_SECRET = "YOUR_APP_SECRET"

Then run the program normally.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import hmac
import os
import sys
import time

from datetime import datetime
from pathlib import Path
from typing import Any

import requests


# ============================================================
# CONFIGURATION
# ============================================================

API_VERSION = "v26.0"

GRAPH_ROOT = "https://graph.facebook.com"

DEFAULT_PAGE_SIZE = 100

DEFAULT_TIMEOUT = 30.0

DEFAULT_RETRIES = 4


# Explicitly request every Graph API field that we need.
#
# limit(0) means we do not download the actual list of
# users/comments/reactions; we only ask Facebook for summary
# information such as total_count.

FIELDS = ",".join(
    [
        "id",
        "created_time",
        "message",
        "permalink_url",
        "shares",
        "likes.limit(0).summary(true)",
        "reactions.limit(0).summary(true)",
        "comments.limit(0).summary(true)",
    ]
)


# TSV column order

COLUMNS = [
    "id",
    "time",
    "date",
    "year",
    "shares",
    "likes",
    "reactions",
    "comments",
    "post_id",
    "permalink_url",
    "message",
]


# ============================================================
# CUSTOM GRAPH API ERROR
# ============================================================

class GraphAPIError(RuntimeError):
    """
    Exception representing an error returned by Meta Graph API.
    """

    def __init__(
        self,
        message: str,
        code: int | None = None,
    ) -> None:

        super().__init__(message)

        self.code = code


# ============================================================
# COMMAND-LINE ARGUMENTS
# ============================================================

def arguments() -> argparse.Namespace:
    """
    Parse command-line arguments.
    """

    parser = argparse.ArgumentParser(
        description=(
            "Export Facebook posts and engagement information "
            "using Meta Graph API."
        )
    )

    parser.add_argument(
        "user_id",
        nargs="?",
        default="me",
        help=(
            'Facebook Graph user/Page ID. '
            'Defaults to "me".'
        ),
    )

    parser.add_argument(
        "--max-posts",
        type=int,
        default=100,
        help=(
            "Maximum number of posts to retrieve. "
            "Use 0 for every accessible post."
        ),
    )

    parser.add_argument(
        "--page-size",
        type=int,
        default=DEFAULT_PAGE_SIZE,
        help=(
            "Posts requested from Facebook per API request. "
            "Range: 1-100."
        ),
    )

    parser.add_argument(
        "--output",
        type=Path,
        help=(
            "Output TSV filename. "
            "If omitted, results are printed to stdout."
        ),
    )

    parser.add_argument(
        "--api-version",
        default=API_VERSION,
        help=(
            f"Meta Graph API version. "
            f"Default: {API_VERSION}"
        ),
    )

    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help=(
            "HTTP timeout in seconds. "
            f"Default: {DEFAULT_TIMEOUT}"
        ),
    )

    args = parser.parse_args()

    if args.max_posts < 0:
        parser.error(
            "--max-posts must be 0 or greater."
        )

    if not 1 <= args.page_size <= 100:
        parser.error(
            "--page-size must be between 1 and 100."
        )

    if args.timeout <= 0:
        parser.error(
            "--timeout must be greater than zero."
        )

    return args


# ============================================================
# APP SECRET PROOF
# ============================================================

def appsecret_proof(
    token: str,
    app_secret: str,
) -> str:
    """
    Generate Meta appsecret_proof.

    appsecret_proof =
        HMAC-SHA256(
            key=APP_SECRET,
            message=ACCESS_TOKEN
        )

    This is useful when "Require App Secret" is enabled
    in the Meta application.
    """

    return hmac.new(
        app_secret.encode("utf-8"),
        token.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


# ============================================================
# GRAPH API REQUEST
# ============================================================

def api_get(
    session: requests.Session,
    url: str,
    params: dict[str, Any],
    timeout: float,
    retries: int = DEFAULT_RETRIES,
) -> dict[str, Any]:
    """
    Perform a resilient Meta Graph API GET request.

    Temporary failures automatically retry.

    Retried status codes:

        429  Too Many Requests
        500  Internal Server Error
        502  Bad Gateway
        503  Service Unavailable
        504  Gateway Timeout
    """

    transient_statuses = {
        429,
        500,
        502,
        503,
        504,
    }

    for attempt in range(retries + 1):

        try:

            response = session.get(
                url,
                params=params,
                timeout=timeout,
            )

        except requests.RequestException as exc:

            if attempt == retries:
                raise GraphAPIError(
                    f"Network error: {exc}"
                ) from exc

            delay = min(
                2 ** attempt,
                30,
            )

            time.sleep(delay)

            continue

        # ----------------------------------------------------
        # Decode JSON response
        # ----------------------------------------------------

        try:

            payload = response.json()

        except ValueError:

            payload = None

        # ----------------------------------------------------
        # Successful response
        # ----------------------------------------------------

        if (
            response.ok
            and isinstance(payload, dict)
            and "error" not in payload
        ):

            return payload

        # ----------------------------------------------------
        # Extract Meta error
        # ----------------------------------------------------

        if isinstance(payload, dict):

            error = payload.get(
                "error",
                {},
            )

        else:

            error = {}

        code = (
            error.get("code")
            if isinstance(
                error.get("code"),
                int,
            )
            else None
        )

        message = (
            error.get("message")
            or
            (
                f"HTTP "
                f"{response.status_code}: "
                f"{response.text[:300]}"
            )
        )

        # ----------------------------------------------------
        # Retry transient errors
        # ----------------------------------------------------

        if (
            response.status_code
            in transient_statuses
            and attempt < retries
        ):

            retry_after = response.headers.get(
                "Retry-After"
            )

            try:

                if retry_after:

                    delay = float(
                        retry_after
                    )

                else:

                    delay = float(
                        2 ** attempt
                    )

            except ValueError:

                delay = float(
                    2 ** attempt
                )

            delay = min(
                max(
                    delay,
                    0.25,
                ),
                30.0,
            )

            time.sleep(delay)

            continue

        raise GraphAPIError(
            str(message),
            code,
        )

    raise GraphAPIError(
        "Graph API request failed after retries."
    )


# ============================================================
# ENGAGEMENT COUNTS
# ============================================================

def total_count(
    post: dict[str, Any],
    key: str,
) -> int:
    """
    Extract:

        FIELD
            -> summary
                -> total_count

    Used for:

        likes
        reactions
        comments
    """

    value = post.get(
        key,
        {},
    )

    if not isinstance(
        value,
        dict,
    ):
        return 0

    summary = value.get(
        "summary",
        {},
    )

    if not isinstance(
        summary,
        dict,
    ):
        return 0

    count = summary.get(
        "total_count",
        0,
    )

    if isinstance(
        count,
        (int, float),
    ):
        return int(count)

    return 0


def shares_count(
    post: dict[str, Any],
) -> int:
    """
    Extract share count.
    """

    shares = post.get(
        "shares",
        {},
    )

    if not isinstance(
        shares,
        dict,
    ):
        return 0

    count = shares.get(
        "count",
        0,
    )

    if isinstance(
        count,
        (int, float),
    ):
        return int(count)

    return 0


# ============================================================
# DATE/TIME PROCESSING
# ============================================================

def split_created_time(
    value: str,
) -> tuple[str, str, str]:
    """
    Convert Facebook created_time into:

        HH:MM:SS
        MM-DD
        YYYY

    This preserves the general structure of the original
    script while parsing the timestamp correctly.
    """

    if not value:

        return (
            "",
            "",
            "",
        )

    # Example:
    #
    # 2026-08-23T14:25:31+0000
    #
    # or:
    #
    # 2026-08-23T14:25:31+00:00

    try:

        dt = datetime.fromisoformat(
            value.replace(
                "Z",
                "+00:00",
            )
        )

    except ValueError:

        dt = datetime.strptime(
            value,
            "%Y-%m-%dT%H:%M:%S%z",
        )

    time_text = dt.strftime(
        "%H:%M:%S"
    )

    date_text = dt.strftime(
        "%m-%d"
    )

    year_text = dt.strftime(
        "%Y"
    )

    return (
        time_text,
        date_text,
        year_text,
    )


# ============================================================
# FETCH POSTS
# ============================================================

def fetch_posts(
    user_id: str,
    token: str,
    app_secret: str | None,
    api_version: str,
    page_size: int,
    max_posts: int,
    timeout: float,
) -> list[dict[str, Any]]:
    """
    Fetch Facebook posts using cursor pagination.
    """

    session = requests.Session()

    # Important:
    #
    # Access token is sent in the HTTP Authorization header.
    #
    # This avoids:
    #
    #     ?access_token=TOKEN
    #
    # appearing in URLs, logs, browser history, etc.

    session.headers.update(
        {
            "Authorization":
                f"Bearer {token}",

            "Accept":
                "application/json",

            "User-Agent":
                "FacebookPostExporter/2.0",
        }
    )

    endpoint = (
        f"{GRAPH_ROOT}/"
        f"{api_version}/"
        f"{user_id}/posts"
    )

    posts: list[
        dict[str, Any]
    ] = []

    after: str | None = None

    seen_cursors: set[str] = set()

    # --------------------------------------------------------
    # Optional Meta App Secret Proof
    # --------------------------------------------------------

    proof = (
        appsecret_proof(
            token,
            app_secret,
        )
        if app_secret
        else None
    )

    # --------------------------------------------------------
    # Cursor-pagination loop
    # --------------------------------------------------------

    while (
        max_posts == 0
        or len(posts) < max_posts
    ):

        if max_posts:

            remaining = (
                max_posts
                - len(posts)
            )

            limit = min(
                page_size,
                remaining,
            )

        else:

            limit = page_size

        params: dict[
            str,
            Any,
        ] = {
            "fields":
                FIELDS,

            "limit":
                limit,
        }

        if after:

            params[
                "after"
            ] = after

        if proof:

            params[
                "appsecret_proof"
            ] = proof

        # ----------------------------------------------------
        # API request
        # ----------------------------------------------------

        payload = api_get(
            session,
            endpoint,
            params,
            timeout,
        )

        data = payload.get(
            "data",
            [],
        )

        if not isinstance(
            data,
            list,
        ):

            raise GraphAPIError(
                "Invalid Graph API response: "
                "'data' is not a list."
            )

        if not data:

            break

        # ----------------------------------------------------
        # Store returned posts
        # ----------------------------------------------------

        for post in data:

            if isinstance(
                post,
                dict,
            ):

                posts.append(
                    post
                )

                if (
                    max_posts
                    and
                    len(posts)
                    >= max_posts
                ):

                    break

        # ----------------------------------------------------
        # Find next paging cursor
        # ----------------------------------------------------

        paging = payload.get(
            "paging",
            {},
        )

        if isinstance(
            paging,
            dict,
        ):

            cursors = paging.get(
                "cursors",
                {},
            )

        else:

            cursors = {}

        if isinstance(
            cursors,
            dict,
        ):

            next_after = cursors.get(
                "after"
            )

        else:

            next_after = None

        if not isinstance(
            next_after,
            str,
        ):

            break

        if not next_after:

            break

        # Protect against an accidental repeating cursor.

        if next_after in seen_cursors:

            break

        seen_cursors.add(
            next_after
        )

        after = next_after

    return posts


# ============================================================
# CONVERT RAW GRAPH API POSTS TO OUTPUT ROWS
# ============================================================

def to_rows(
    posts: list[dict[str, Any]],
) -> list[dict[str, Any]]:

    rows: list[
        dict[str, Any]
    ] = []

    for index, post in enumerate(
        posts,
        start=1,
    ):

        created_time = str(
            post.get(
                "created_time",
                "",
            )
            or ""
        )

        (
            time_text,
            date_text,
            year_text,
        ) = split_created_time(
            created_time
        )

        row = {

            "id":
                index,

            "time":
                time_text,

            "date":
                date_text,

            "year":
                year_text,

            "shares":
                shares_count(
                    post
                ),

            "likes":
                total_count(
                    post,
                    "likes",
                ),

            "reactions":
                total_count(
                    post,
                    "reactions",
                ),

            "comments":
                total_count(
                    post,
                    "comments",
                ),

            "post_id":
                str(
                    post.get(
                        "id",
                        "",
                    )
                    or ""
                ),

            "permalink_url":
                str(
                    post.get(
                        "permalink_url",
                        "",
                    )
                    or ""
                ),

            "message":
                str(
                    post.get(
                        "message",
                        "",
                    )
                    or ""
                ),
        }

        rows.append(
            row
        )

    return rows


# ============================================================
# TSV OUTPUT
# ============================================================

def write_tsv(
    rows: list[dict[str, Any]],
    stream,
) -> None:
    """
    Properly write tab-separated data.

    csv.DictWriter automatically handles messages containing:

        tabs
        quotations
        line breaks
        Unicode
    """

    writer = csv.DictWriter(
        stream,
        fieldnames=COLUMNS,
        delimiter="\t",
        lineterminator="\n",
        quoting=csv.QUOTE_MINIMAL,
    )

    writer.writeheader()

    writer.writerows(
        rows
    )


# ============================================================
# MAIN
# ============================================================

def main() -> int:

    args = arguments()

    # --------------------------------------------------------
    # Securely retrieve access token
    # --------------------------------------------------------

    token = os.environ.get(
        "FB_ACCESS_TOKEN"
    )

    app_secret = os.environ.get(
        "FB_APP_SECRET"
    )

    if not token:

        print(
            "ERROR: FB_ACCESS_TOKEN "
            "environment variable is not set.",
            file=sys.stderr,
        )

        print(
            "",
            file=sys.stderr,
        )

        print(
            "PowerShell:",
            file=sys.stderr,
        )

        print(
            '$env:FB_ACCESS_TOKEN = '
            '"YOUR_ACCESS_TOKEN"',
            file=sys.stderr,
        )

        return 2

    try:

        # ----------------------------------------------------
        # Download posts
        # ----------------------------------------------------

        posts = fetch_posts(
            user_id=
                args.user_id,

            token=
                token,

            app_secret=
                app_secret,

            api_version=
                args.api_version,

            page_size=
                args.page_size,

            max_posts=
                args.max_posts,

            timeout=
                args.timeout,
        )

        # ----------------------------------------------------
        # Process posts
        # ----------------------------------------------------

        rows = to_rows(
            posts
        )

        # ----------------------------------------------------
        # File output
        # ----------------------------------------------------

        if args.output:

            args.output.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            with args.output.open(
                "w",
                encoding="utf-8",
                newline="",
            ) as file:

                write_tsv(
                    rows,
                    file,
                )

            print(
                f"Exported "
                f"{len(rows)} posts "
                f"to {args.output}",
                file=sys.stderr,
            )

        # ----------------------------------------------------
        # Console output
        # ----------------------------------------------------

        else:

            write_tsv(
                rows,
                sys.stdout,
            )

        return 0

    # ========================================================
    # META GRAPH API ERRORS
    # ========================================================

    except GraphAPIError as exc:

        print(
            f"Graph API error: {exc}",
            file=sys.stderr,
        )

        # Invalid / expired access token

        if exc.code == 190:

            print(
                "Hint: the access token "
                "is invalid, expired or revoked.",
                file=sys.stderr,
            )

        # Permission error

        elif exc.code in {
            10,
            200,
        }:

            print(
                "Hint: the application/token "
                "does not have sufficient permission.",
                file=sys.stderr,
            )

            print(
                "For user posts, check user_posts.",
                file=sys.stderr,
            )

            print(
                "For Page engagement data, "
                "permissions such as "
                "pages_read_engagement may be needed.",
                file=sys.stderr,
            )

        # Invalid field / parameter

        elif exc.code == 100:

            print(
                "Hint: a requested field may not "
                "be available for this object/token.",
                file=sys.stderr,
            )

            print(
                "If your Meta app requires App Secret Proof, "
                "also set FB_APP_SECRET.",
                file=sys.stderr,
            )

        return 1


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    raise SystemExit(
        main()
    )
