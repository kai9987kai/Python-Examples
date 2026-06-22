#!/usr/bin/env python3
"""
consent_sms.py
A safer Python 3 SMS sender using Twilio's official API.

Features:
- Dry-run by default: nothing is sent unless --send is supplied
- CSV recipient import
- Consent and opt-out enforcement
- E.164 phone validation
- Duplicate prevention
- Rate limiting
- Per-run safety cap
- JSONL audit logging
- Message templates such as: "Hi {first_name}, your code is {code}"

Install:
    python -m pip install twilio

Set environment variables:

Linux/macOS:
    export TWILIO_ACCOUNT_SID="ACxxxxxxxx"
    export TWILIO_AUTH_TOKEN="xxxxxxxx"
    export TWILIO_FROM_NUMBER="+447700900123"

Windows PowerShell:
    $env:TWILIO_ACCOUNT_SID="ACxxxxxxxx"
    $env:TWILIO_AUTH_TOKEN="xxxxxxxx"
    $env:TWILIO_FROM_NUMBER="+447700900123"

Example CSV: recipients.csv

    phone,consent,first_name,code
    +447700900123,yes,Ada,123456
    +447700900124,no,Sam,654321

Dry run:
    python consent_sms.py --recipients recipients.csv --message "Hi {first_name}, your code is {code}"

Actually send:
    python consent_sms.py --recipients recipients.csv --message "Hi {first_name}, your code is {code}" --send

Use only for recipients who have explicitly agreed to receive messages.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


E164_PATTERN = re.compile(r"^\+[1-9]\d{7,14}$")

VALID_CONSENT_VALUES = {
    "1",
    "true",
    "yes",
    "y",
    "opted_in",
    "opted-in",
    "consented",
}


@dataclass(frozen=True)
class Recipient:
    phone: str
    fields: dict[str, str]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Send consented SMS messages through Twilio. Defaults to dry-run mode."
    )

    parser.add_argument(
        "--recipients",
        type=Path,
        required=True,
        help="CSV file containing at least phone and consent columns.",
    )

    parser.add_argument(
        "--message",
        required=True,
        help="Message template. Example: 'Hi {first_name}, your code is {code}'",
    )

    parser.add_argument(
        "--send",
        action="store_true",
        help="Actually send messages. Without this flag, the script performs a dry run.",
    )

    parser.add_argument(
        "--from-number",
        default=os.getenv("TWILIO_FROM_NUMBER"),
        help="Twilio sender number in E.164 format. Defaults to TWILIO_FROM_NUMBER.",
    )

    parser.add_argument(
        "--messaging-service-sid",
        default=os.getenv("TWILIO_MESSAGING_SERVICE_SID"),
        help="Optional Twilio Messaging Service SID. Use this instead of --from-number.",
    )

    parser.add_argument(
        "--opt-outs",
        type=Path,
        default=Path("opt_outs.txt"),
        help="Text file containing one opted-out E.164 phone number per line.",
    )

    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="Seconds to wait between sends. Default: 1.0",
    )

    parser.add_argument(
        "--max-recipients",
        type=int,
        default=50,
        help="Maximum recipients allowed in one run. Default: 50",
    )

    parser.add_argument(
        "--log",
        type=Path,
        default=Path("sms_results.jsonl"),
        help="Audit log file path. Default: sms_results.jsonl",
    )

    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop immediately after the first provider error.",
    )

    parser.add_argument(
        "--max-message-length",
        type=int,
        default=1000,
        help="Reject rendered messages longer than this many characters. Default: 1000",
    )

    args = parser.parse_args()

    if args.delay < 0:
        parser.error("--delay cannot be negative.")

    if args.max_recipients < 1:
        parser.error("--max-recipients must be at least 1.")

    if args.max_message_length < 1:
        parser.error("--max-message-length must be at least 1.")

    if args.send:
        if bool(args.from_number) == bool(args.messaging_service_sid):
            parser.error(
                "When using --send, provide exactly one sender: "
                "--from-number or --messaging-service-sid."
            )

    return args


def mask_phone(phone: str) -> str:
    """Mask a phone number for logs and terminal output."""
    if len(phone) < 7:
        return "<invalid>"

    hidden_count = max(3, len(phone) - 7)
    return f"{phone[:4]}{'*' * hidden_count}{phone[-3:]}"


def write_log(path: Path, record: dict[str, Any]) -> None:
    """Write one JSON record per line to the audit log."""
    path.parent.mkdir(parents=True, exist_ok=True)

    record["timestamp_utc"] = datetime.now(timezone.utc).isoformat()

    with path.open("a", encoding="utf-8") as log_file:
        log_file.write(json.dumps(record, ensure_ascii=False) + "\n")


def read_opt_outs(path: Path) -> set[str]:
    """Load local opt-out numbers from a text file."""
    if not path.exists():
        return set()

    opt_outs = set()

    for line in path.read_text(encoding="utf-8").splitlines():
        number = line.strip()

        if not number:
            continue

        if number.startswith("#"):
            continue

        opt_outs.add(number)

    return opt_outs


def normalise_row(raw_row: dict[str | None, str | None]) -> dict[str, str]:
    """Normalise CSV headers and values."""
    return {
        (key or "").strip().lower(): (value or "").strip()
        for key, value in raw_row.items()
    }


def load_recipients(
    csv_path: Path,
    opt_outs: set[str],
) -> tuple[list[Recipient], list[dict[str, str]]]:
    """Load valid, consented recipients and record skipped entries."""
    if not csv_path.exists():
        raise FileNotFoundError(f"Recipients file not found: {csv_path}")

    accepted: list[Recipient] = []
    skipped: list[dict[str, str]] = []
    seen_numbers: set[str] = set()

    with csv_path.open("r", encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.DictReader(csv_file)

        if not reader.fieldnames:
            raise ValueError("CSV is empty or has no header row.")

        headers = {
            header.strip().lower()
            for header in reader.fieldnames
            if header is not None
        }

        required_columns = {"phone", "consent"}
        missing_columns = required_columns - headers

        if missing_columns:
            missing = ", ".join(sorted(missing_columns))
            raise ValueError(f"CSV is missing required column(s): {missing}")

        for row_number, raw_row in enumerate(reader, start=2):
            row = normalise_row(raw_row)

            phone = row.get("phone", "")
            consent = row.get("consent", "").lower()

            reason: str | None = None

            if not E164_PATTERN.fullmatch(phone):
                reason = "invalid_e164_phone"

            elif consent not in VALID_CONSENT_VALUES:
                reason = "missing_or_invalid_consent"

            elif phone in opt_outs:
                reason = "local_opt_out"

            elif phone in seen_numbers:
                reason = "duplicate_phone"

            if reason:
                skipped.append(
                    {
                        "row": str(row_number),
                        "phone": mask_phone(phone),
                        "reason": reason,
                    }
                )
                continue

            seen_numbers.add(phone)
            accepted.append(Recipient(phone=phone, fields=row))

    return accepted, skipped


def render_message(template: str, fields: dict[str, str]) -> str:
    """Safely render a message template using recipient CSV fields."""

    class MissingFieldDict(dict[str, str]):
        def __missing__(self, key: str) -> str:
            raise ValueError(f"Message template references missing CSV column: {{{key}}}")

    try:
        message = template.format_map(MissingFieldDict(fields)).strip()
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"Invalid message template: {exc}") from exc

    if not message:
        raise ValueError("Message is empty after rendering.")

    return message


def create_twilio_client():
    """Create a Twilio client only when sending is requested."""
    account_sid = os.getenv("TWILIO_ACCOUNT_SID")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN")

    if not account_sid or not auth_token:
        raise RuntimeError(
            "Missing Twilio credentials. Set TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN."
        )

    try:
        from twilio.rest import Client
    except ImportError as exc:
        raise RuntimeError(
            "Twilio is not installed. Run: python -m pip install twilio"
        ) from exc

    return Client(account_sid, auth_token)


def run_dry_run(
    recipients: list[Recipient],
    message_template: str,
    max_message_length: int,
) -> int:
    """Show messages that would be sent without contacting Twilio."""
    print("\n--- DRY RUN: Nothing will be sent ---\n")

    for index, recipient in enumerate(recipients, start=1):
        try:
            body = render_message(message_template, recipient.fields)
        except ValueError as exc:
            print(
                f"[{index}/{len(recipients)}] Template error for "
                f"{mask_phone(recipient.phone)}: {exc}",
                file=sys.stderr,
            )
            return 2

        if len(body) > max_message_length:
            print(
                f"[{index}/{len(recipients)}] Message too long for "
                f"{mask_phone(recipient.phone)}: {len(body)} characters.",
                file=sys.stderr,
            )
            return 2

        print(f"[{index}/{len(recipients)}] To: {mask_phone(recipient.phone)}")
        print(f"Message: {body}")
        print()

    print("Nothing was sent. Add --send after reviewing this output.")
    return 0


def send_messages(
    recipients: list[Recipient],
    args: argparse.Namespace,
) -> int:
    """Send messages through Twilio."""
    try:
        client = create_twilio_client()

        from twilio.base.exceptions import TwilioRestException
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    sent_count = 0
    failed_count = 0

    print("\n--- SEND MODE: Sending messages ---\n")

    for index, recipient in enumerate(recipients, start=1):
        try:
            body = render_message(args.message, recipient.fields)

            if len(body) > args.max_message_length:
                raise ValueError(
                    f"Rendered message is {len(body)} characters; "
                    f"maximum allowed is {args.max_message_length}."
                )

            message_args: dict[str, str] = {
                "to": recipient.phone,
                "body": body,
            }

            if args.messaging_service_sid:
                message_args["messaging_service_sid"] = args.messaging_service_sid
            else:
                message_args["from_"] = args.from_number

            result = client.messages.create(**message_args)

            sent_count += 1

            write_log(
                args.log,
                {
                    "event": "accepted_by_provider",
                    "recipient": mask_phone(recipient.phone),
                    "message_sid": result.sid,
                    "status": result.status,
                },
            )

            print(
                f"[{index}/{len(recipients)}] Accepted: "
                f"{mask_phone(recipient.phone)} ({result.status})"
            )

        except ValueError as exc:
            failed_count += 1

            write_log(
                args.log,
                {
                    "event": "validation_error",
                    "recipient": mask_phone(recipient.phone),
                    "error": str(exc),
                },
            )

            print(
                f"[{index}/{len(recipients)}] Validation failed: "
                f"{mask_phone(recipient.phone)} ({exc})",
                file=sys.stderr,
            )

            if args.fail_fast:
                break

        except TwilioRestException as exc:
            failed_count += 1

            write_log(
                args.log,
                {
                    "event": "provider_error",
                    "recipient": mask_phone(recipient.phone),
                    "code": exc.code,
                    "error": str(exc),
                },
            )

            print(
                f"[{index}/{len(recipients)}] Provider failed: "
                f"{mask_phone(recipient.phone)} "
                f"(code {exc.code})",
                file=sys.stderr,
            )

            if args.fail_fast:
                break

        except Exception as exc:
            failed_count += 1

            write_log(
                args.log,
                {
                    "event": "unexpected_error",
                    "recipient": mask_phone(recipient.phone),
                    "error": str(exc),
                },
            )

            print(
                f"[{index}/{len(recipients)}] Unexpected error: "
                f"{mask_phone(recipient.phone)} ({exc})",
                file=sys.stderr,
            )

            if args.fail_fast:
                break

        if index < len(recipients) and args.delay > 0:
            time.sleep(args.delay)

    print(
        f"\nCompleted: {sent_count} accepted, "
        f"{failed_count} failed."
    )
    print(f"Audit log: {args.log}")

    return 1 if failed_count else 0


def main() -> int:
    args = parse_args()

    try:
        opt_outs = read_opt_outs(args.opt_outs)
        recipients, skipped = load_recipients(args.recipients, opt_outs)
    except (FileNotFoundError, ValueError, csv.Error) as exc:
        print(f"Input error: {exc}", file=sys.stderr)
        return 2

    for item in skipped:
        write_log(args.log, {"event": "skipped", **item})

    if len(recipients) > args.max_recipients:
        print(
            f"Safety cap triggered: {len(recipients)} eligible recipients found, "
            f"but --max-recipients is {args.max_recipients}.",
            file=sys.stderr,
        )
        print(
            "Review your CSV and increase the cap deliberately if appropriate.",
            file=sys.stderr,
        )
        return 2

    print(
        f"Eligible recipients: {len(recipients)} | "
        f"Skipped: {len(skipped)} | "
        f"Mode: {'SEND' if args.send else 'DRY RUN'}"
    )

    if not recipients:
        print("No eligible recipients found. Nothing to do.")
        return 0

    if not args.send:
        return run_dry_run(
            recipients=recipients,
            message_template=args.message,
            max_message_length=args.max_message_length,
        )

    return send_messages(recipients, args)


if __name__ == "__main__":
    raise SystemExit(main())
