#!/usr/bin/env python3
"""Modern, robust Gmail API sender for Python 3.10+."""

from __future__ import annotations

import argparse
import base64
import logging
import mimetypes
import os
import re
import sys
from dataclasses import dataclass
from email.message import EmailMessage
from email.policy import SMTP
from email.utils import getaddresses, make_msgid, parseaddr
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable, Sequence

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


SCOPES = ["https://www.googleapis.com/auth/gmail.send"]

DEFAULT_CREDENTIALS = Path("credentials.json")
DEFAULT_TOKEN = Path.home() / ".gmail_sender" / "token.json"
DEFAULT_RETRIES = 4

LOG = logging.getLogger("gmail_sender")


class ConfigurationError(ValueError):
    """Invalid command-line, MIME, recipient, or OAuth configuration."""


class HTMLToText(HTMLParser):
    """
    Lightweight HTML -> plain-text converter.

    Used automatically when an HTML body is supplied without a corresponding
    plain-text alternative.
    """

    BLOCKS = {
        "address",
        "article",
        "aside",
        "blockquote",
        "br",
        "div",
        "footer",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "hr",
        "li",
        "main",
        "nav",
        "ol",
        "p",
        "pre",
        "section",
        "table",
        "tr",
        "ul",
    }

    SKIP = {
        "script",
        "style",
        "noscript",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)

        self.parts: list[str] = []
        self.skip_depth = 0

    def handle_starttag(
        self,
        tag: str,
        attrs,
    ) -> None:  # type: ignore[no-untyped-def]

        tag = tag.lower()

        if tag in self.SKIP:
            self.skip_depth += 1

        elif not self.skip_depth and tag in self.BLOCKS:
            self.parts.append("\n")

    def handle_endtag(
        self,
        tag: str,
    ) -> None:

        tag = tag.lower()

        if tag in self.SKIP and self.skip_depth:
            self.skip_depth -= 1

        elif not self.skip_depth and tag in self.BLOCKS:
            self.parts.append("\n")

    def handle_data(
        self,
        data: str,
    ) -> None:

        if not self.skip_depth:
            self.parts.append(data)

    def result(self) -> str:
        text = "".join(self.parts)

        text = re.sub(
            r"[ \t\f\v]+",
            " ",
            text,
        )

        text = re.sub(
            r" *\n *",
            "\n",
            text,
        )

        text = re.sub(
            r"\n{3,}",
            "\n\n",
            text,
        )

        return text.strip()


def html_to_text(
    html: str,
) -> str:
    parser = HTMLToText()

    parser.feed(html)
    parser.close()

    return parser.result()


def clean_header(
    value: str,
    field: str,
) -> str:
    """
    Prevent header injection through CR/LF characters.
    """

    if "\r" in value or "\n" in value:
        raise ConfigurationError(
            f"{field} cannot contain CR/LF characters."
        )

    return value.strip()


def valid_address(
    address: str,
) -> bool:
    """
    Perform a basic email-address sanity check.

    Gmail remains the final authority on whether an address is deliverable.
    """

    if address.count("@") != 1:
        return False

    if any(character.isspace() for character in address):
        return False

    local_part, domain = address.rsplit("@", 1)

    if not local_part:
        return False

    if not domain:
        return False

    if domain.startswith("."):
        return False

    if domain.endswith("."):
        return False

    return True


def parse_addresses(
    values: Iterable[str] | None,
) -> list[str]:
    """
    Parse repeated and comma-separated recipient arguments.

    Examples accepted:

        --to alice@example.com
        --to alice@example.com --to bob@example.com
        --to "Alice <alice@example.com>, Bob <bob@example.com>"
    """

    if not values:
        return []

    result: list[str] = []

    for name, address in getaddresses(values):

        name = clean_header(
            name,
            "Display name",
        )

        address = clean_header(
            address,
            "Email address",
        )

        if not address:
            continue

        if not valid_address(address):
            raise ConfigurationError(
                f"Invalid email address: {address!r}"
            )

        if name:
            result.append(
                f"{name} <{address}>"
            )

        else:
            result.append(address)

    return result


def parse_sender(
    value: str | None,
) -> str:
    """
    Validate the From address.
    """

    if not value or not value.strip():
        raise ConfigurationError(
            "A From address is required; use --sender ADDRESS."
        )

    value = clean_header(
        value,
        "From",
    )

    name, address = parseaddr(value)

    if not address or not valid_address(address):
        raise ConfigurationError(
            f"Invalid sender address: {value!r}"
        )

    if name:
        return f"{name} <{address}>"

    return address


def secure_write(
    path: Path,
    data: str,
) -> None:
    """
    Save OAuth token data and attempt to limit permissions on POSIX systems.
    """

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    path.write_text(
        data,
        encoding="utf-8",
    )

    if os.name != "nt":
        try:
            path.chmod(0o600)

        except OSError:
            LOG.warning(
                "Could not restrict token permissions on %s",
                path,
            )


def get_credentials(
    credentials_file: Path,
    token_file: Path,
) -> Credentials:
    """
    Load cached OAuth credentials, refresh them when possible,
    or start the Desktop OAuth flow.
    """

    creds: Credentials | None = None

    if token_file.exists():

        try:
            creds = Credentials.from_authorized_user_file(
                str(token_file),
                SCOPES,
            )

        except (OSError, ValueError) as exc:
            LOG.warning(
                "Ignoring invalid token file %s: %s",
                token_file,
                exc,
            )

    if creds and creds.valid:
        return creds

    if (
        creds
        and creds.expired
        and creds.refresh_token
    ):

        try:
            LOG.info(
                "Refreshing Gmail OAuth token..."
            )

            creds.refresh(
                Request()
            )

            secure_write(
                token_file,
                creds.to_json(),
            )

            return creds

        except RefreshError as exc:
            LOG.warning(
                "Token refresh failed; re-authenticating: %s",
                exc,
            )

    if not credentials_file.is_file():

        raise ConfigurationError(
            f"OAuth credentials file not found: "
            f"{credentials_file}\n"
            "Create a Google Cloud OAuth Desktop App client, "
            "download the JSON, and save it as credentials.json "
            "or pass --credentials PATH."
        )

    LOG.info(
        "Starting Google OAuth authorization..."
    )

    flow = InstalledAppFlow.from_client_secrets_file(
        str(credentials_file),
        SCOPES,
    )

    creds = flow.run_local_server(
        port=0,
    )

    secure_write(
        token_file,
        creds.to_json(),
    )

    LOG.info(
        "OAuth token saved to %s",
        token_file,
    )

    return creds


def read_utf8(
    path: str | None,
    label: str,
) -> str | None:
    """
    Read a UTF-8 message-body file.
    """

    if path is None:
        return None

    file = Path(path).expanduser()

    if not file.is_file():
        raise ConfigurationError(
            f"{label} file not found: {file}"
        )

    try:
        return file.read_text(
            encoding="utf-8"
        )

    except UnicodeDecodeError as exc:

        raise ConfigurationError(
            f"{label} must be UTF-8: {file}"
        ) from exc


def mime_type(
    path: Path,
) -> tuple[str, str]:
    """
    Determine MIME type using Python's mimetypes database.
    """

    guessed, encoding = mimetypes.guess_type(
        str(path)
    )

    if (
        not guessed
        or encoding is not None
        or "/" not in guessed
    ):
        return (
            "application",
            "octet-stream",
        )

    main_type, sub_type = guessed.split(
        "/",
        1,
    )

    return (
        main_type,
        sub_type,
    )


@dataclass(frozen=True)
class InlineFile:
    path: Path
    cid: str


def parse_inline(
    values: Sequence[str] | None,
) -> list[InlineFile]:
    """
    Parse --inline parameters.

    Syntax:

        --inline image.png

    or:

        --inline image.png:logo

    HTML can then reference:

        <img src="cid:logo">
    """

    output: list[InlineFile] = []
    cids: set[str] = set()

    for raw in values or []:

        whole = Path(raw).expanduser()

        if whole.is_file():

            path = whole

            cid = make_msgid(
                domain="gmail-sender.local"
            )[1:-1]

        else:

            left, separator, right = raw.rpartition(
                ":"
            )

            if (
                not separator
                or not left
                or not right
            ):
                raise ConfigurationError(
                    f"Invalid --inline {raw!r}; "
                    "use PATH or PATH:CID."
                )

            path = Path(
                left
            ).expanduser()

            cid = (
                right
                .strip()
                .strip("<>")
            )

        if not path.is_file():
            raise ConfigurationError(
                f"Inline file not found: {path}"
            )

        if (
            not cid
            or any(
                character.isspace()
                for character in cid
            )
            or "\r" in cid
            or "\n" in cid
        ):
            raise ConfigurationError(
                f"Invalid Content-ID: {cid!r}"
            )

        if cid in cids:
            raise ConfigurationError(
                f"Duplicate Content-ID: {cid!r}"
            )

        cids.add(cid)

        output.append(
            InlineFile(
                path=path,
                cid=cid,
            )
        )

    return output


def add_attachments(
    message: EmailMessage,
    files: Sequence[str],
) -> None:
    """
    Add normal MIME attachments.
    """

    for raw in files:

        path = Path(
            raw
        ).expanduser()

        if not path.is_file():
            raise ConfigurationError(
                f"Attachment not found: {path}"
            )

        main_type, sub_type = mime_type(
            path
        )

        message.add_attachment(
            path.read_bytes(),
            maintype=main_type,
            subtype=sub_type,
            filename=path.name,
        )

        LOG.debug(
            "Attached %s as %s/%s",
            path,
            main_type,
            sub_type,
        )


def add_inline_files(
    message: EmailMessage,
    files: Sequence[InlineFile],
) -> None:
    """
    Add Content-ID resources to the HTML MIME part.
    """

    if not files:
        return

    payload = message.get_payload()

    if (
        not isinstance(payload, list)
        or not payload
        or payload[-1].get_content_type()
        != "text/html"
    ):
        raise ConfigurationError(
            "Inline files require an HTML alternative."
        )

    html_part = payload[-1]

    for item in files:

        main_type, sub_type = mime_type(
            item.path
        )

        html_part.add_related(
            item.path.read_bytes(),
            maintype=main_type,
            subtype=sub_type,
            cid=f"<{item.cid}>",
            filename=item.path.name,
            disposition="inline",
        )

        LOG.debug(
            "Embedded %s as cid:%s",
            item.path,
            item.cid,
        )


def build_message(
    *,
    sender: str,
    to: Sequence[str],
    cc: Sequence[str],
    bcc: Sequence[str],
    subject: str,
    text: str,
    html: str | None,
    attachments: Sequence[str],
    inline_files: Sequence[InlineFile],
    reply_to: str | None,
    in_reply_to: str | None,
    references: str | None,
) -> EmailMessage:
    """
    Build a standards-compliant MIME message.
    """

    if not (
        to
        or cc
        or bcc
    ):
        raise ConfigurationError(
            "At least one To, Cc, or Bcc recipient is required."
        )

    subject = clean_header(
        subject,
        "Subject",
    )

    if not subject:
        raise ConfigurationError(
            "Subject cannot be empty."
        )

    message = EmailMessage(
        policy=SMTP
    )

    message["From"] = sender

    if to:
        message["To"] = ", ".join(
            to
        )

    if cc:
        message["Cc"] = ", ".join(
            cc
        )

    if bcc:
        message["Bcc"] = ", ".join(
            bcc
        )

    message["Subject"] = subject

    if reply_to:

        addresses = parse_addresses(
            [reply_to]
        )

        if len(addresses) != 1:
            raise ConfigurationError(
                "--reply-to must contain exactly one address."
            )

        message["Reply-To"] = addresses[0]

    if in_reply_to:

        message["In-Reply-To"] = clean_header(
            in_reply_to,
            "In-Reply-To",
        )

    if references:

        message["References"] = clean_header(
            references,
            "References",
        )

    message.set_content(
        text,
        charset="utf-8",
    )

    if html is not None:

        message.add_alternative(
            html,
            subtype="html",
            charset="utf-8",
        )

        add_inline_files(
            message,
            inline_files,
        )

    elif inline_files:

        raise ConfigurationError(
            "--inline requires --html or --html-file."
        )

    add_attachments(
        message,
        attachments,
    )

    return message


def encode_for_gmail(
    message: EmailMessage,
) -> str:
    """
    Convert RFC MIME message into Gmail API base64url representation.
    """

    message_bytes = message.as_bytes(
        policy=SMTP
    )

    encoded = base64.urlsafe_b64encode(
        message_bytes
    )

    return encoded.decode(
        "ascii"
    )


def send(
    service,
    message: EmailMessage,
    thread_id: str | None,
    retries: int,
) -> dict:
    """
    Submit the generated message through users.messages.send().
    """

    body: dict[str, str] = {
        "raw": encode_for_gmail(
            message
        )
    }

    if thread_id:
        body["threadId"] = thread_id

    try:

        result = (
            service
            .users()
            .messages()
            .send(
                userId="me",
                body=body,
            )
            .execute(
                num_retries=max(
                    0,
                    retries,
                )
            )
        )

        return result

    except HttpError as exc:

        status = getattr(
            exc.resp,
            "status",
            "unknown",
        )

        reason = (
            getattr(
                exc,
                "reason",
                None,
            )
            or str(exc)
        )

        raise RuntimeError(
            f"Gmail API send failed "
            f"(HTTP {status}): {reason}"
        ) from exc


def resolve_bodies(
    args: argparse.Namespace,
) -> tuple[str, str | None]:
    """
    Resolve plain-text and HTML bodies.

    If only HTML exists, a plain-text fallback is generated automatically.
    """

    if (
        args.text is not None
        and args.text_file is not None
    ):
        raise ConfigurationError(
            "Choose either --text or --text-file, not both."
        )

    if (
        args.html is not None
        and args.html_file is not None
    ):
        raise ConfigurationError(
            "Choose either --html or --html-file, not both."
        )

    if args.text is not None:
        text = args.text

    else:
        text = read_utf8(
            args.text_file,
            "Text body",
        )

    if args.html is not None:
        html = args.html

    else:
        html = read_utf8(
            args.html_file,
            "HTML body",
        )

    if (
        text is None
        and html is None
    ):
        raise ConfigurationError(
            "Provide --text/--text-file "
            "or --html/--html-file."
        )

    if (
        text is None
        and html is not None
    ):

        text = html_to_text(
            html
        )

        if not text:
            text = (
                "This message contains "
                "an HTML version."
            )

    return (
        text or "",
        html,
    )


def prompt_missing(
    args: argparse.Namespace,
) -> None:
    """
    Preserve the convenience of the original interactive program.
    """

    if (
        not args.to
        and not args.cc
        and not args.bcc
    ):

        value = input(
            "Recipient email address: "
        ).strip()

        if value:
            args.to = [value]

    if args.sender is None:

        args.sender = input(
            "From address: "
        ).strip()

    if args.subject is None:

        args.subject = input(
            "Subject: "
        ).strip()

    if (
        args.text is None
        and args.text_file is None
        and args.html is None
        and args.html_file is None
    ):

        args.text = input(
            "Message: "
        )


def parser() -> argparse.ArgumentParser:
    """
    Build command-line interface.
    """

    command_parser = argparse.ArgumentParser(
        description=(
            "Send plain-text/HTML email "
            "through the Gmail API."
        ),
        formatter_class=(
            argparse.RawDescriptionHelpFormatter
        ),
        epilog=(
            "Examples:\n"
            "\n"
            "  python advanced_gmail_sender.py "
            "--sender me@gmail.com "
            "--to you@example.com "
            "--subject 'Hello' "
            "--text 'Hi'\n"
            "\n"
            "  python advanced_gmail_sender.py "
            "--sender me@gmail.com "
            "--to you@example.com "
            "--subject 'Report' "
            "--html-file report.html "
            "--attach report.pdf\n"
            "\n"
            "  python advanced_gmail_sender.py "
            "--sender me@gmail.com "
            "--to you@example.com "
            "--subject 'Logo' "
            "--html '<img src=\"cid:logo\">' "
            "--inline logo.png:logo\n"
        ),
    )

    command_parser.add_argument(
        "--sender",
        help=(
            "From address; normally the authenticated "
            "Gmail account or configured alias."
        ),
    )

    command_parser.add_argument(
        "--to",
        action="append",
        help=(
            "Recipient; repeat or use "
            "comma-separated addresses."
        ),
    )

    command_parser.add_argument(
        "--cc",
        action="append",
        help=(
            "Cc recipient; repeat as needed."
        ),
    )

    command_parser.add_argument(
        "--bcc",
        action="append",
        help=(
            "Bcc recipient; repeat as needed."
        ),
    )

    command_parser.add_argument(
        "--reply-to",
        help="Optional Reply-To address.",
    )

    command_parser.add_argument(
        "--subject",
        help="Email subject.",
    )

    body_group = command_parser.add_argument_group(
        "message body"
    )

    body_group.add_argument(
        "--text",
        help="Plain-text body.",
    )

    body_group.add_argument(
        "--text-file",
        help="UTF-8 plain-text file.",
    )

    body_group.add_argument(
        "--html",
        help="HTML body.",
    )

    body_group.add_argument(
        "--html-file",
        help="UTF-8 HTML file.",
    )

    file_group = command_parser.add_argument_group(
        "files"
    )

    file_group.add_argument(
        "--attach",
        action="append",
        default=[],
        help=(
            "Attachment; repeat as needed."
        ),
    )

    file_group.add_argument(
        "--inline",
        action="append",
        default=[],
        metavar="PATH[:CID]",
        help=(
            "Inline file for cid: references."
        ),
    )

    thread_group = command_parser.add_argument_group(
        "threading"
    )

    thread_group.add_argument(
        "--thread-id",
        help=(
            "Existing Gmail threadId."
        ),
    )

    thread_group.add_argument(
        "--in-reply-to",
        help=(
            "RFC Message-ID being replied to."
        ),
    )

    thread_group.add_argument(
        "--references",
        help=(
            "RFC References header value."
        ),
    )

    oauth_group = command_parser.add_argument_group(
        "OAuth"
    )

    oauth_group.add_argument(
        "--credentials",
        type=Path,
        default=DEFAULT_CREDENTIALS,
        help=(
            "OAuth Desktop App JSON."
        ),
    )

    oauth_group.add_argument(
        "--token",
        type=Path,
        default=DEFAULT_TOKEN,
        help=(
            "Token cache path."
        ),
    )

    oauth_group.add_argument(
        "--reset-token",
        action="store_true",
        help=(
            "Delete cached OAuth token "
            "before login."
        ),
    )

    command_parser.add_argument(
        "--retries",
        type=int,
        default=DEFAULT_RETRIES,
        help=(
            "Transient API retry count."
        ),
    )

    command_parser.add_argument(
        "--dry-run",
        type=Path,
        metavar="FILE.eml",
        help=(
            "Write MIME message to .eml "
            "without sending."
        ),
    )

    command_parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging.",
    )

    return command_parser


def main(
    argv: Sequence[str] | None = None,
) -> int:
    """
    Program entry point.
    """

    args = parser().parse_args(
        argv
    )

    logging.basicConfig(
        level=(
            logging.DEBUG
            if args.verbose
            else logging.INFO
        ),
        format="%(levelname)s: %(message)s",
    )

    try:

        prompt_missing(
            args
        )

        text_body, html_body = resolve_bodies(
            args
        )

        message = build_message(
            sender=parse_sender(
                args.sender
            ),
            to=parse_addresses(
                args.to
            ),
            cc=parse_addresses(
                args.cc
            ),
            bcc=parse_addresses(
                args.bcc
            ),
            subject=(
                args.subject
                or ""
            ),
            text=text_body,
            html=html_body,
            attachments=args.attach,
            inline_files=parse_inline(
                args.inline
            ),
            reply_to=args.reply_to,
            in_reply_to=args.in_reply_to,
            references=args.references,
        )

        if args.dry_run:

            args.dry_run.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            args.dry_run.write_bytes(
                message.as_bytes(
                    policy=SMTP
                )
            )

            print(
                "Dry run complete: "
                f"{args.dry_run.resolve()}"
            )

            return 0

        token_path = args.token.expanduser()

        if (
            args.reset_token
            and token_path.exists()
        ):

            token_path.unlink()

            LOG.info(
                "Removed cached token %s",
                token_path,
            )

        credentials = get_credentials(
            args.credentials.expanduser(),
            token_path,
        )

        service = build(
            "gmail",
            "v1",
            credentials=credentials,
            cache_discovery=False,
        )

        result = send(
            service=service,
            message=message,
            thread_id=args.thread_id,
            retries=args.retries,
        )

        print(
            "Email sent successfully."
        )

        print(
            "Message ID: "
            f"{result.get('id', '<not returned>')}"
        )

        if result.get("threadId"):

            print(
                "Thread ID:  "
                f"{result['threadId']}"
            )

        return 0

    except (
        ConfigurationError,
        RuntimeError,
        OSError,
    ) as exc:

        LOG.error(
            "%s",
            exc,
        )

        return 2

    except KeyboardInterrupt:

        print(
            "\nCancelled.",
            file=sys.stderr,
        )

        return 130


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
