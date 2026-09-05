#!/usr/bin/env python3
"""
karate_sms.py

Modern Python 3 replacement for the 2017 Textlocal/urllib2 script.

Environment variables:
    WEBEX_INTERACT_TOKEN   Webex Interact API access token.
    SMS_SENDER             Verified sender name (3-11 characters).
    DROPBOX                Optional Dropbox root containing database/maindatabase.db.
    SCRIPTS                Optional scripts root; logs are written to SCRIPTS/output.

Safe default:
    Running without --send uses Webex Interact's /v1/sms/test endpoint.
    Running with --send performs a real send and requires typing SEND unless --yes is used.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sqlite3
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


API_URL = "https://api.webexinteract.com/v1/sms"
API_TEST_URL = "https://api.webexinteract.com/v1/sms/test"

DEFAULT_DB_RELATIVE = Path("database") / "maindatabase.db"
DEFAULT_BATCH_SIZE = 500
MAX_RECIPIENTS_PER_REQUEST = 10_000

E164_RE = re.compile(r"^\+[1-9]\d{7,14}$")
IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

PREFERRED_TABLES = (
    "students",
    "student",
    "members",
    "member",
    "contacts",
    "contact",
    "table",
)

NAME_COLUMNS = (
    "name",
    "student_name",
    "studentname",
    "full_name",
    "fullname",
    "first_name",
    "firstname",
)

PHONE_COLUMNS = (
    "number",
    "mobile",
    "mobile_number",
    "phone",
    "phone_number",
    "telephone",
)

GSM7_BASIC = (
    "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞ"
    "ÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?"
    "¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿"
    "abcdefghijklmnopqrstuvwxyzäöñüà"
)

GSM7_EXT = "^{}\\[~]|€"


@dataclass(frozen=True)
class Recipient:
    name: str
    phone: str
    correlation_id: str


class SmsError(RuntimeError):
    """Raised when the SMS provider request cannot be completed safely."""


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Send a Karate Club cancellation SMS "
            "from a SQLite student database."
        )
    )

    parser.add_argument(
        "--send",
        action="store_true",
        help=(
            "Send real SMS messages. "
            "Without this option the Webex Interact test endpoint is used."
        ),
    )

    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip the interactive SEND confirmation in live mode.",
    )

    parser.add_argument(
        "--db",
        type=Path,
        help=(
            "SQLite database path. "
            "Defaults to $DROPBOX/database/maindatabase.db."
        ),
    )

    parser.add_argument(
        "--table",
        help=(
            "Explicit SQLite table. "
            "Otherwise a compatible table is detected automatically."
        ),
    )

    parser.add_argument(
        "--sender",
        default=os.getenv("SMS_SENDER"),
        help=(
            "Verified Webex Interact sender name. "
            "Defaults to the SMS_SENDER environment variable."
        ),
    )

    parser.add_argument(
        "--date",
        help=(
            "Date wording inserted into the standard message, "
            "for example '5 September'."
        ),
    )

    parser.add_argument(
        "--message",
        help=(
            "Full custom message. "
            "Use ${firstname} where the student's name should appear."
        ),
    )

    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=(
            f"Recipients per API request. "
            f"Default {DEFAULT_BATCH_SIZE}; maximum "
            f"{MAX_RECIPIENTS_PER_REQUEST}."
        ),
    )

    parser.add_argument(
        "--timeout",
        type=int,
        default=20,
        help="Network timeout in seconds.",
    )

    parser.add_argument(
        "--retries",
        type=int,
        default=4,
        help=(
            "Retry count for test-mode transient failures "
            "and HTTP 429 responses."
        ),
    )

    return parser.parse_args()


def db_path_from_args(value: Path | None) -> Path:
    if value:
        return value.expanduser().resolve()

    root = os.getenv("DROPBOX") or os.getenv("dropbox")

    if root:
        base = Path(root).expanduser()
    else:
        base = Path.cwd()

    return (base / DEFAULT_DB_RELATIVE).resolve()


def output_dir() -> Path:
    root = os.getenv("SCRIPTS") or os.getenv("scripts")

    if root:
        path = Path(root).expanduser() / "output"
    else:
        path = Path.cwd() / "output"

    path.mkdir(
        parents=True,
        exist_ok=True,
    )

    return path.resolve()


def setup_logging(
    directory: Path,
) -> tuple[logging.Logger, Path, Path]:

    stamp = datetime.now().strftime(
        "%Y%m%d_%H%M%S"
    )

    log_path = directory / (
        f"student_sms_{stamp}.log"
    )

    audit_path = directory / (
        f"student_sms_{stamp}.jsonl"
    )

    logger = logging.getLogger(
        "karate_sms"
    )

    logger.handlers.clear()

    logger.setLevel(
        logging.INFO
    )

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s",
        "%Y-%m-%d %H:%M:%S",
    )

    stdout_handler = logging.StreamHandler(
        sys.stdout
    )

    stdout_handler.setFormatter(
        formatter
    )

    logger.addHandler(
        stdout_handler
    )

    file_handler = logging.FileHandler(
        log_path,
        encoding="utf-8",
    )

    file_handler.setFormatter(
        formatter
    )

    logger.addHandler(
        file_handler
    )

    return (
        logger,
        log_path,
        audit_path,
    )


def qident(
    identifier: str,
) -> str:

    if not IDENT_RE.fullmatch(
        identifier
    ):
        raise ValueError(
            f"Unsafe SQLite identifier: "
            f"{identifier!r}"
        )

    return f'"{identifier}"'


def table_columns(
    conn: sqlite3.Connection,
    table: str,
) -> dict[str, str]:

    rows = conn.execute(
        f"PRAGMA table_info({qident(table)})"
    ).fetchall()

    return {
        str(row[1]).lower(): str(row[1])
        for row in rows
    }


def first_column(
    columns: dict[str, str],
    candidates: Iterable[str],
) -> str | None:

    return next(
        (
            columns[candidate]
            for candidate in candidates
            if candidate in columns
        ),
        None,
    )


def discover_source(
    conn: sqlite3.Connection,
    explicit_table: str | None,
) -> tuple[str, str, str]:

    if explicit_table:

        qident(
            explicit_table
        )

        tables = [
            explicit_table
        ]

    else:

        available = [
            str(row[0])
            for row in conn.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type='table'
                  AND name NOT LIKE 'sqlite_%'
                ORDER BY name
                """
            )
        ]

        tables = [
            table
            for table in PREFERRED_TABLES
            if table in available
        ]

        tables.extend(
            table
            for table in available
            if table not in tables
        )

    for table in tables:

        columns = table_columns(
            conn,
            table,
        )

        name_column = first_column(
            columns,
            NAME_COLUMNS,
        )

        phone_column = first_column(
            columns,
            PHONE_COLUMNS,
        )

        if (
            name_column
            and phone_column
        ):
            return (
                table,
                name_column,
                phone_column,
            )

    raise RuntimeError(
        "No table with a usable student-name "
        "column and phone-number column was found."
    )


def clean_name(
    value: Any,
) -> str:

    text = " ".join(
        str(
            value or ""
        ).split()
    )

    text = "".join(
        character
        for character in text
        if character.isprintable()
    )

    return (
        text[:80]
        or "Student"
    )


def normalize_phone(
    value: Any,
) -> str:

    text = re.sub(
        r"[\s().-]+",
        "",
        str(
            value or ""
        ).strip(),
    )

    if not text:
        raise ValueError(
            "empty phone number"
        )

    if text.startswith(
        "00"
    ):
        text = (
            "+"
            + text[2:]
        )

    elif text.startswith(
        "+"
    ):
        pass

    elif text.startswith(
        "0"
    ):
        text = (
            "+44"
            + text[1:]
        )

    elif text.startswith(
        "44"
    ):
        text = (
            "+"
            + text
        )

    elif text.isdigit():

        text = (
            "+"
            + text
        )

    else:

        raise ValueError(
            "unsupported characters"
        )

    if not E164_RE.fullmatch(
        text
    ):
        raise ValueError(
            "not valid E.164"
        )

    return text


def mask_phone(
    phone: str,
) -> str:

    if len(phone) < 8:
        return "***"

    return (
        f"{phone[:4]}"
        f"***"
        f"{phone[-3:]}"
    )


def load_recipients(
    conn: sqlite3.Connection,
    table: str,
    name_col: str,
    phone_col: str,
    logger: logging.Logger,
) -> list[Recipient]:

    sql = (
        f"SELECT "
        f"{qident(name_col)}, "
        f"{qident(phone_col)} "
        f"FROM "
        f"{qident(table)}"
    )

    recipients: list[Recipient] = []

    seen: set[str] = set()

    invalid = 0
    duplicate = 0

    for (
        name_raw,
        phone_raw,
    ) in conn.execute(
        sql
    ):

        try:

            phone = normalize_phone(
                phone_raw
            )

        except ValueError as exc:

            invalid += 1

            logger.warning(
                "Skipping invalid phone number: %s",
                exc,
            )

            continue

        if phone in seen:

            duplicate += 1

            logger.warning(
                "Skipping duplicate %s",
                mask_phone(
                    phone
                ),
            )

            continue

        seen.add(
            phone
        )

        recipient = Recipient(
            name=clean_name(
                name_raw
            ),
            phone=phone,
            correlation_id=(
                "karate-"
                + uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    phone,
                ).hex[:20]
            ),
        )

        recipients.append(
            recipient
        )

    logger.info(
        "Recipients: %d valid, "
        "%d invalid, "
        "%d duplicate.",
        len(recipients),
        invalid,
        duplicate,
    )

    return recipients


def default_date() -> str:

    now = datetime.now()

    return (
        f"{now.day} "
        f"{now.strftime('%B')}"
    )


def default_message(
    date_text: str,
) -> str:

    return (
        "Hello ${firstname}, "
        "Karate training is cancelled tonight "
        f"({date_text}). "
        "Sorry for the late notice. "
        "An email has also been sent. "
        "Please do not reply."
    )


def gsm7_units(
    text: str,
) -> int | None:

    total = 0

    for character in text:

        if character in GSM7_BASIC:

            total += 1

        elif character in GSM7_EXT:

            total += 2

        else:

            return None

    return total


def estimate_parts(
    text: str,
) -> tuple[str, int, int]:

    gsm_units = gsm7_units(
        text
    )

    if gsm_units is not None:

        if gsm_units <= 160:

            parts = 1

        else:

            parts = (
                gsm_units + 152
            ) // 153

        return (
            "GSM-7",
            gsm_units,
            parts,
        )

    count = len(
        text
    )

    if count <= 70:

        parts = 1

    else:

        parts = (
            count + 66
        ) // 67

    return (
        "Unicode",
        count,
        parts,
    )


def batches(
    items: list[Recipient],
    size: int,
) -> Iterable[list[Recipient]]:

    for index in range(
        0,
        len(items),
        size,
    ):

        yield items[
            index:
            index + size
        ]


def payload_for(
    batch: list[Recipient],
    sender: str,
    message: str,
) -> dict[str, Any]:

    destinations = []

    for recipient in batch:

        destinations.append(
            {
                "correlation_id":
                    recipient.correlation_id,

                "phone": [
                    recipient.phone
                ],

                "merge_fields": {
                    "firstname":
                        recipient.name
                },
            }
        )

    return {
        "message_body":
            message,

        "from":
            sender,

        /*
        Keep Webex Interact's
        account opt-out checks enabled.
        */
        "skip_optout_check":
            False,

        "name":
            (
                "karate-cancellation-"
                + datetime.now().strftime(
                    "%Y%m%d-%H%M%S"
                )
            ),

        "to":
            destinations,
    }


def redact(
    value: Any,
) -> Any:

    if isinstance(
        value,
        dict,
    ):

        output: dict[str, Any] = {}

        for (
            key,
            item,
        ) in value.items():

            if (
                key in {
                    "to",
                    "phone",
                    "phone_number",
                }
                and isinstance(
                    item,
                    str,
                )
            ):

                output[key] = mask_phone(
                    item
                )

            elif (
                key == "phone"
                and isinstance(
                    item,
                    list,
                )
            ):

                output[key] = [
                    mask_phone(
                        str(number)
                    )
                    for number in item
                ]

            else:

                output[key] = redact(
                    item
                )

        return output

    if isinstance(
        value,
        list,
    ):

        return [
            redact(
                item
            )
            for item in value
        ]

    return value


def api_post(
    url: str,
    token: str,
    payload: dict[str, Any],
    timeout: int,
    retries: int,
    live: bool,
    logger: logging.Logger,
) -> dict[str, Any] | list[Any]:

    body = json.dumps(
        payload,
        ensure_ascii=False,
    ).encode(
        "utf-8"
    )

    headers = {
        "X-AUTH-KEY":
            token,

        "Content-Type":
            "application/json",

        "Accept":
            "application/json",

        "User-Agent":
            "KarateClubSMS/2.0",
    }

    for attempt in range(
        1,
        retries + 1,
    ):

        try:

            request = Request(
                url,
                data=body,
                headers=headers,
                method="POST",
            )

            with urlopen(
                request,
                timeout=timeout,
            ) as response:

                raw = response.read().decode(
                    "utf-8"
                )

                if not raw.strip():

                    return {}

                return json.loads(
                    raw
                )

        except HTTPError as exc:

            raw = exc.read().decode(
                "utf-8",
                "replace",
            )

            try:

                detail: Any = json.loads(
                    raw
                )

            except json.JSONDecodeError:

                detail = {
                    "raw":
                        raw[:1000]
                }

            /*
            HTTP 429 means the request
            was rate-limited.

            A replay is reasonable.

            HTTP 5xx is only retried in
            TEST mode because a LIVE
            request may have reached the
            SMS service before the error
            response occurred.

            Automatically replaying it
            could therefore send duplicate
            messages.
            */

            retryable = (
                exc.code == 429
                or (
                    not live
                    and 500 <= exc.code <= 599
                )
            )

            if (
                retryable
                and attempt < retries
            ):

                retry_after = (
                    exc.headers.get(
                        "Retry-After"
                    )
                )

                try:

                    delay = (
                        float(
                            retry_after
                        )
                        if retry_after
                        else min(
                            2 ** (
                                attempt - 1
                            ),
                            16,
                        )
                    )

                except ValueError:

                    delay = min(
                        2 ** (
                            attempt - 1
                        ),
                        16,
                    )

                logger.warning(
                    "HTTP %d; retrying in %.1fs.",
                    exc.code,
                    delay,
                )

                time.sleep(
                    delay
                )

                continue

            raise SmsError(
                "Provider HTTP "
                f"{exc.code}: "
                + json.dumps(
                    redact(
                        detail
                    ),
                    ensure_ascii=False,
                )
            ) from exc

        except (
            URLError,
            TimeoutError,
        ) as exc:

            if (
                not live
                and attempt < retries
            ):

                delay = min(
                    2 ** (
                        attempt - 1
                    ),
                    16,
                )

                logger.warning(
                    "TEST request network failure; "
                    "retrying in %.1fs.",
                    delay,
                )

                time.sleep(
                    delay
                )

                continue

            if live:

                raise SmsError(
                    "Ambiguous LIVE network failure. "
                    "The request was not automatically "
                    "retried because that could duplicate "
                    "an SMS. Check Webex Interact outbound "
                    "history or webhooks before retrying."
                ) from exc

            raise SmsError(
                "Network failure after "
                f"{retries} attempts: "
                f"{exc}"
            ) from exc

        except json.JSONDecodeError as exc:

            raise SmsError(
                "Provider returned invalid JSON."
            ) from exc

    raise SmsError(
        "Unexpected retry-loop exit."
    )


def response_counts(
    response: dict[str, Any] | list[Any],
) -> tuple[int, int]:

    accepted = 0
    errors = 0

    if isinstance(
        response,
        list,
    ):
        objects = response
    else:
        objects = [
            response
        ]

    for item in objects:

        if not isinstance(
            item,
            dict,
        ):
            continue

        messages = item.get(
            "messages"
        )

        provider_errors = item.get(
            "errors"
        )

        if isinstance(
            messages,
            list,
        ):
            accepted += len(
                messages
            )

        if isinstance(
            provider_errors,
            list,
        ):
            errors += len(
                provider_errors
            )

    return (
        accepted,
        errors,
    )


def append_audit(
    path: Path,
    mode: str,
    batch_number: int,
    size: int,
    response: Any,
) -> None:

    entry = {
        "timestamp":
            datetime.now()
            .astimezone()
            .isoformat(),

        "mode":
            mode,

        "batch":
            batch_number,

        "recipient_count":
            size,

        "response":
            redact(
                response
            ),
    }

    with path.open(
        "a",
        encoding="utf-8",
    ) as file:

        file.write(
            json.dumps(
                entry,
                ensure_ascii=False,
            )
            + "\n"
        )


def validate_sender(
    sender: str | None,
) -> str:

    if not sender:

        raise RuntimeError(
            "Set SMS_SENDER or pass "
            "--sender with a verified "
            "Webex Interact sender."
        )

    sender = sender.strip()

    if not (
        3
        <= len(sender)
        <= 11
    ):

        raise RuntimeError(
            "Sender must contain "
            "3-11 characters."
        )

    if not re.fullmatch(
        r"[A-Za-z0-9 .&_ -]+",
        sender,
    ):

        raise RuntimeError(
            "Sender contains unsupported "
            "characters."
        )

    return sender


def main() -> int:

    args = arguments()

    if not (
        1
        <= args.batch_size
        <= MAX_RECIPIENTS_PER_REQUEST
    ):

        print(
            "--batch-size must be "
            f"1-{MAX_RECIPIENTS_PER_REQUEST}",
            file=sys.stderr,
        )

        return 2

    if (
        args.timeout < 1
        or args.retries < 1
    ):

        print(
            "--timeout and --retries "
            "must be positive integers",
            file=sys.stderr,
        )

        return 2

    (
        logger,
        log_path,
        audit_path,
    ) = setup_logging(
        output_dir()
    )

    try:

        token = os.getenv(
            "WEBEX_INTERACT_TOKEN"
        )

        if not token:

            raise RuntimeError(
                "WEBEX_INTERACT_TOKEN "
                "is not set."
            )

        sender = validate_sender(
            args.sender
        )

        database = db_path_from_args(
            args.db
        )

        if not database.is_file():

            raise FileNotFoundError(
                "Database not found: "
                f"{database}"
            )

        if args.date:

            date_text = args.date.strip()

        else:

            date_text = default_date()

        if args.message:

            message = args.message

        else:

            message = default_message(
                date_text
            )

        sample = message.replace(
            "${firstname}",
            "Alex",
        )

        (
            encoding,
            units,
            part_count,
        ) = estimate_parts(
            sample
        )

        logger.info(
            "Database: %s",
            database,
        )

        logger.info(
            "Log: %s",
            log_path,
        )

        logger.info(
            "Message estimate: "
            "%s, %d units/chars, "
            "%d SMS part(s) "
            "for sample name.",
            encoding,
            units,
            part_count,
        )

        if part_count > 1:

            logger.warning(
                "This message is likely "
                "to be billed as %d SMS "
                "parts per recipient.",
                part_count,
            )

        /*
        Open SQLite in read-only mode.

        Even if there is a bug elsewhere
        in this script, it cannot UPDATE,
        DELETE or INSERT student records.
        */

        uri = (
            database.as_uri()
            + "?mode=ro"
        )

        with sqlite3.connect(
            uri,
            uri=True,
        ) as connection:

            (
                table,
                name_column,
                phone_column,
            ) = discover_source(
                connection,
                args.table,
            )

            logger.info(
                "Using table=%s, "
                "name=%s, phone=%s",
                table,
                name_column,
                phone_column,
            )

            recipients = load_recipients(
                connection,
                table,
                name_column,
                phone_column,
                logger,
            )

        if not recipients:

            raise RuntimeError(
                "No valid recipients found."
            )

        live = bool(
            args.send
        )

        mode = (
            "LIVE"
            if live
            else "TEST"
        )

        url = (
            API_URL
            if live
            else API_TEST_URL
        )

        logger.info(
            "%s mode: "
            "%d recipient(s), "
            "batch size %d.",
            mode,
            len(recipients),
            args.batch_size,
        )

        if (
            live
            and not args.yes
        ):

            print()

            print(
                "LIVE SEND: "
                f"{len(recipients)} "
                "recipient(s), "
                f"sender={sender}"
            )

            confirmation = input(
                "Type SEND to continue: "
            ).strip()

            if confirmation != "SEND":

                logger.warning(
                    "Cancelled."
                )

                return 130

        total_ok = 0
        total_errors = 0

        all_batches = list(
            batches(
                recipients,
                args.batch_size,
            )
        )

        for (
            index,
            batch,
        ) in enumerate(
            all_batches,
            1,
        ):

            logger.info(
                "Submitting batch "
                "%d/%d "
                "(%d recipients).",
                index,
                len(all_batches),
                len(batch),
            )

            payload = payload_for(
                batch,
                sender,
                message,
            )

            response = api_post(
                url=url,
                token=token,
                payload=payload,
                timeout=args.timeout,
                retries=args.retries,
                live=live,
                logger=logger,
            )

            (
                accepted,
                errors,
            ) = response_counts(
                response
            )

            total_ok += accepted
            total_errors += errors

            append_audit(
                audit_path,
                mode,
                index,
                len(batch),
                response,
            )

            logger.info(
                "Batch %d: "
                "%d accepted/validated, "
                "%d errors.",
                index,
                accepted,
                errors,
            )

            if errors:

                logger.warning(
                    "Provider errors: %s",
                    json.dumps(
                        redact(
                            response
                        ),
                        ensure_ascii=False,
                    ),
                )

        logger.info(
            "Finished: "
            "%d accepted/validated, "
            "%d provider errors, "
            "%d intended recipients.",
            total_ok,
            total_errors,
            len(recipients),
        )

        logger.info(
            "Audit: %s",
            audit_path,
        )

        if total_errors:

            return 1

        return 0

    except KeyboardInterrupt:

        logger.warning(
            "Cancelled."
        )

        return 130

    except (
        FileNotFoundError,
        RuntimeError,
        ValueError,
        sqlite3.Error,
        SmsError,
    ) as exc:

        logger.error(
            "%s",
            exc,
        )

        return 1


if __name__ == "__main__":

    raise SystemExit(
        main()
    )
