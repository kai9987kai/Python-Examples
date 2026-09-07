"""
Advanced Archive Media Downloader
==================================

Modern replacement for a simple BeautifulSoup + requests video downloader.

Features
--------
- Crawls an HTML directory/archive page.
- Discovers linked media files.
- Supports MP4, WEBM, MOV, MP3, etc.
- Uses proper URL joining.
- Follows HTTP -> HTTPS redirects.
- Automatic HTTP retries with exponential backoff.
- Resumable downloads using HTTP Range requests.
- Parallel downloads.
- Streaming to disk instead of loading files into memory.
- Temporary .part files.
- Detects already downloaded files.
- Checks remote/local file size where possible.
- Optional SHA-256 checksums.
- Filename sanitisation.
- Configurable output directory.
- Configurable worker count.
- List-only mode.
- Graceful Ctrl+C handling.
- Cross-platform: Windows/macOS/Linux.

Install
-------

    python -m pip install requests beautifulsoup4

Examples
--------

Download all MP4 files from the default archive:

    python archive_downloader.py

Only list files:

    python archive_downloader.py --list-only

Download to a custom directory:

    python archive_downloader.py -o videos

Use five parallel workers:

    python archive_downloader.py -w 5

Download MP4 and WEBM:

    python archive_downloader.py -e mp4,webm

Calculate SHA-256 checksums:

    python archive_downloader.py --sha256

Download from another archive:

    python archive_downloader.py https://example.com/media/

Only use this program for files you have permission to download.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import os
import re
import sys
import threading
import time

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


# ============================================================
# CONFIGURATION
# ============================================================

DEFAULT_ARCHIVE_URL = (
    "http://www-personal.umich.edu/~csev/books/py4inf/media/"
)

DEFAULT_EXTENSIONS = (
    ".mp4",
)

CHUNK_SIZE = 1024 * 1024       # 1 MiB
CONNECT_TIMEOUT = 10           # seconds
READ_TIMEOUT = 90              # seconds

DEFAULT_WORKERS = 3

DEFAULT_USER_AGENT = (
    "AdvancedArchiveDownloader/3.0 "
    "(Python requests; educational archive downloader)"
)


# Thread-local storage gives every worker its own HTTP session.
_thread_local = threading.local()


# ============================================================
# DATA MODEL
# ============================================================

@dataclass(frozen=True)
class RemoteFile:
    """
    Represents a remote media file discovered on the archive page.
    """

    url: str
    filename: str


# ============================================================
# HTTP SESSION
# ============================================================

def create_session(user_agent: str) -> requests.Session:
    """
    Create a requests Session configured with:

    - connection pooling
    - automatic retries
    - exponential backoff
    - retry-after support
    """

    session = requests.Session()

    retry_strategy = Retry(
        total=5,
        connect=5,
        read=5,
        status=5,

        backoff_factor=0.75,

        status_forcelist=(
            408,    # Request Timeout
            429,    # Too Many Requests
            500,    # Internal Server Error
            502,    # Bad Gateway
            503,    # Service Unavailable
            504,    # Gateway Timeout
        ),

        allowed_methods=frozenset(
            {
                "HEAD",
                "GET",
            }
        ),

        respect_retry_after_header=True,

        # We let requests.raise_for_status() handle the final
        # response rather than raising inside urllib3.
        raise_on_status=False,
    )

    adapter = HTTPAdapter(
        max_retries=retry_strategy,

        # Larger connection pools are useful when several
        # downloads run concurrently.
        pool_connections=20,
        pool_maxsize=20,
    )

    session.mount(
        "http://",
        adapter,
    )

    session.mount(
        "https://",
        adapter,
    )

    session.headers.update(
        {
            "User-Agent": user_agent,
            "Accept": "*/*",
        }
    )

    return session


def get_session(user_agent: str) -> requests.Session:
    """
    Return one persistent HTTP Session per worker thread.

    Sharing one Session across many threads is best avoided,
    so each downloader worker gets its own.
    """

    session = getattr(
        _thread_local,
        "session",
        None,
    )

    if session is None:
        session = create_session(
            user_agent
        )

        _thread_local.session = session

    return session


# ============================================================
# FILE / URL HELPERS
# ============================================================

def sanitize_filename(filename: str) -> str:
    """
    Convert a URL-derived filename into a filesystem-safe filename.

    Especially important on Windows where characters including
    < > : " / \\ | ? *
    are invalid.
    """

    filename = unquote(
        filename
    ).strip()

    filename = re.sub(
        r'[<>:"/\\|?*\x00-\x1f]',
        "_",
        filename,
    )

    filename = filename.rstrip(
        ". "
    )

    if not filename:
        filename = "download.bin"

    return filename


def filename_from_url(url: str) -> str:
    """
    Extract the final path component from a URL.
    """

    parsed = urlparse(
        url
    )

    name = Path(
        parsed.path
    ).name

    return sanitize_filename(
        name
    )


def format_bytes(size: int | None) -> str:
    """
    Convert a byte count into a human-readable representation.
    """

    if size is None:
        return "unknown"

    units = (
        "B",
        "KiB",
        "MiB",
        "GiB",
        "TiB",
    )

    value = float(
        size
    )

    for unit in units:

        if value < 1024 or unit == units[-1]:

            if unit == "B":
                return f"{int(value)} {unit}"

            return f"{value:.2f} {unit}"

        value /= 1024

    return f"{size} B"


# ============================================================
# ARCHIVE DISCOVERY
# ============================================================

def discover_files(
    archive_url: str,
    extensions: tuple[str, ...],
    user_agent: str,
) -> list[RemoteFile]:
    """
    Download an archive/index page and discover matching media links.
    """

    session = get_session(
        user_agent
    )

    response = session.get(
        archive_url,

        timeout=(
            CONNECT_TIMEOUT,
            READ_TIMEOUT,
        ),
    )

    response.raise_for_status()

    print(
        f"Resolved archive URL: {response.url}"
    )

    soup = BeautifulSoup(
        response.text,
        "html.parser",
    )

    # Dictionary automatically removes duplicate URLs.
    discovered: dict[str, RemoteFile] = {}

    for anchor in soup.find_all(
        "a",
        href=True,
    ):

        href = anchor.get(
            "href"
        )

        if not href:
            continue

        # Much safer than:
        #
        # archive_url + href
        #
        # because href might be absolute, relative, ../ etc.
        absolute_url = urljoin(
            response.url,
            href,
        )

        parsed = urlparse(
            absolute_url
        )

        # Ignore mailto:, javascript:, ftp:, etc.
        if parsed.scheme not in {
            "http",
            "https",
        }:
            continue

        path_lower = parsed.path.lower()

        matches_extension = any(
            path_lower.endswith(
                extension.lower()
            )
            for extension in extensions
        )

        if not matches_extension:
            continue

        filename = filename_from_url(
            absolute_url
        )

        discovered[absolute_url] = RemoteFile(
            url=absolute_url,
            filename=filename,
        )

    files = sorted(
        discovered.values(),
        key=lambda item: item.filename.lower(),
    )

    return files


# ============================================================
# REMOTE METADATA
# ============================================================

def get_remote_size(
    url: str,
    user_agent: str,
) -> int | None:
    """
    Attempt to determine remote file size using HEAD.

    Returns None when the server does not expose Content-Length.
    """

    session = get_session(
        user_agent
    )

    try:

        response = session.head(
            url,
            allow_redirects=True,

            timeout=(
                CONNECT_TIMEOUT,
                READ_TIMEOUT,
            ),
        )

        if response.ok:

            length = response.headers.get(
                "Content-Length"
            )

            if length and length.isdigit():

                return int(
                    length
                )

    except requests.RequestException:
        pass

    return None


# ============================================================
# CHECKSUM
# ============================================================

def calculate_sha256(
    path: Path,
) -> str:
    """
    Calculate SHA-256 without loading the entire file into memory.
    """

    digest = hashlib.sha256()

    with path.open(
        "rb"
    ) as file_handle:

        for block in iter(
            lambda: file_handle.read(
                CHUNK_SIZE
            ),
            b"",
        ):

            digest.update(
                block
            )

    return digest.hexdigest()


# ============================================================
# COLLISION HANDLING
# ============================================================

def choose_unique_path(
    output_directory: Path,
    filename: str,
) -> Path:
    """
    Generate:

        video.mp4
        video_2.mp4
        video_3.mp4

    if necessary.
    """

    candidate = (
        output_directory
        / filename
    )

    if not candidate.exists():
        return candidate

    stem = candidate.stem
    suffix = candidate.suffix

    index = 2

    while True:

        alternative = (
            output_directory
            / f"{stem}_{index}{suffix}"
        )

        if not alternative.exists():
            return alternative

        index += 1


# ============================================================
# SINGLE FILE DOWNLOAD
# ============================================================

def download_file(
    item: RemoteFile,
    output_directory: Path,
    user_agent: str,
    overwrite: bool,
    resume: bool,
    verify_sha256: bool,
) -> tuple[str, str]:
    """
    Download one file.

    Returns:

        ("downloaded", message)

    or

        ("skipped", message)
    """

    session = get_session(
        user_agent
    )

    destination = (
        output_directory
        / item.filename
    )

    partial = destination.with_suffix(
        destination.suffix + ".part"
    )

    # --------------------------------------------------------
    # EXISTING FILE HANDLING
    # --------------------------------------------------------

    if destination.exists() and not overwrite:

        remote_size = get_remote_size(
            item.url,
            user_agent,
        )

        local_size = destination.stat().st_size

        # If size matches, we know the existing file is likely complete.
        if (
            remote_size is not None
            and local_size == remote_size
        ):

            return (
                "skipped",
                (
                    f"{item.filename} already exists "
                    f"and matches the remote size"
                ),
            )

        # If the server does not provide its size, preserve
        # the existing file rather than overwriting it.
        if remote_size is None:

            return (
                "skipped",
                (
                    f"{item.filename} already exists "
                    f"(remote size unavailable)"
                ),
            )

        # Existing file appears incomplete.
        if resume:

            if partial.exists():

                # Keep the larger partial download.
                if (
                    destination.stat().st_size
                    > partial.stat().st_size
                ):

                    partial.unlink()

                    destination.replace(
                        partial
                    )

                else:

                    destination.unlink()

            else:

                destination.replace(
                    partial
                )

        else:

            destination = choose_unique_path(
                output_directory,
                item.filename,
            )

            partial = destination.with_suffix(
                destination.suffix + ".part"
            )

    # --------------------------------------------------------
    # OVERWRITE
    # --------------------------------------------------------

    if overwrite:

        if destination.exists():
            destination.unlink()

        if partial.exists():
            partial.unlink()

    # --------------------------------------------------------
    # RESUME STATE
    # --------------------------------------------------------

    existing_size = 0

    if resume and partial.exists():

        existing_size = partial.stat().st_size

    headers: dict[str, str] = {}

    file_mode = "wb"

    if resume and existing_size > 0:

        headers["Range"] = (
            f"bytes={existing_size}-"
        )

        file_mode = "ab"

        print(
            f"[RESUME] {item.filename} "
            f"from {format_bytes(existing_size)}"
        )

    # --------------------------------------------------------
    # HTTP GET
    # --------------------------------------------------------

    response = session.get(
        item.url,

        stream=True,

        headers=headers,

        timeout=(
            CONNECT_TIMEOUT,
            READ_TIMEOUT,
        ),
    )

    # --------------------------------------------------------
    # SERVER IGNORED RANGE
    # --------------------------------------------------------

    if (
        existing_size > 0
        and response.status_code == 200
    ):

        # Server did not honour our Range request.
        # Restart from zero instead of accidentally appending
        # the entire file to the partial file.
        existing_size = 0
        file_mode = "wb"

        print(
            f"[RESTART] Server does not support resume for "
            f"{item.filename}"
        )

    # --------------------------------------------------------
    # RANGE NOT SATISFIABLE
    # --------------------------------------------------------

    if response.status_code == 416:

        if partial.exists():

            expected_size = get_remote_size(
                item.url,
                user_agent,
            )

            partial_size = partial.stat().st_size

            if (
                expected_size is not None
                and partial_size == expected_size
            ):

                partial.replace(
                    destination
                )

                return (
                    "downloaded",
                    (
                        f"{destination.name} "
                        f"was already fully downloaded"
                    ),
                )

            # The partial file is inconsistent.
            partial.unlink(
                missing_ok=True
            )

        # Retry cleanly from scratch.
        return download_file(
            item=item,
            output_directory=output_directory,
            user_agent=user_agent,
            overwrite=True,
            resume=resume,
            verify_sha256=verify_sha256,
        )

    response.raise_for_status()

    # --------------------------------------------------------
    # EXPECTED SIZE
    # --------------------------------------------------------

    content_length = response.headers.get(
        "Content-Length"
    )

    remaining_size: int | None = None

    if (
        content_length
        and content_length.isdigit()
    ):

        remaining_size = int(
            content_length
        )

    if remaining_size is not None:

        total_size = (
            existing_size
            + remaining_size
        )

    else:

        total_size = None

    # --------------------------------------------------------
    # DOWNLOAD LOOP
    # --------------------------------------------------------

    downloaded = existing_size

    started_at = time.monotonic()

    last_progress_update = started_at

    with partial.open(
        file_mode
    ) as file_handle:

        for chunk in response.iter_content(
            chunk_size=CHUNK_SIZE
        ):

            if not chunk:
                continue

            file_handle.write(
                chunk
            )

            downloaded += len(
                chunk
            )

            now = time.monotonic()

            # Avoid printing thousands of progress messages.
            if (
                now - last_progress_update
                >= 1.0
            ):

                elapsed = max(
                    now - started_at,
                    0.001,
                )

                transferred_this_session = max(
                    downloaded - existing_size,
                    0,
                )

                speed = (
                    transferred_this_session
                    / elapsed
                )

                # --------------------------------------------
                # KNOWN TOTAL SIZE
                # --------------------------------------------

                if total_size:

                    percentage = (
                        downloaded
                        / total_size
                    ) * 100

                    print(
                        f"[DOWNLOAD] "
                        f"{item.filename}: "
                        f"{percentage:6.2f}%  "
                        f"{format_bytes(downloaded)} / "
                        f"{format_bytes(total_size)}  "
                        f"{format_bytes(int(speed))}/s",
                        flush=True,
                    )

                # --------------------------------------------
                # UNKNOWN TOTAL SIZE
                # --------------------------------------------

                else:

                    print(
                        f"[DOWNLOAD] "
                        f"{item.filename}: "
                        f"{format_bytes(downloaded)}  "
                        f"{format_bytes(int(speed))}/s",
                        flush=True,
                    )

                last_progress_update = now

        # Push buffered Python data to the OS.
        file_handle.flush()

        # Request that the OS flush the data to the underlying
        # storage device.
        os.fsync(
            file_handle.fileno()
        )

    # --------------------------------------------------------
    # SIZE VERIFICATION
    # --------------------------------------------------------

    actual_size = partial.stat().st_size

    if (
        total_size is not None
        and actual_size != total_size
    ):

        raise IOError(
            f"File-size mismatch for {item.filename}: "
            f"expected {total_size:,} bytes but received "
            f"{actual_size:,} bytes."
        )

    # --------------------------------------------------------
    # ATOMICISH FINALISATION
    # --------------------------------------------------------

    partial.replace(
        destination
    )

    final_size = destination.stat().st_size

    # --------------------------------------------------------
    # OPTIONAL CHECKSUM
    # --------------------------------------------------------

    if verify_sha256:

        checksum = calculate_sha256(
            destination
        )

        return (
            "downloaded",
            (
                f"{destination.name} "
                f"({format_bytes(final_size)}) "
                f"SHA256={checksum}"
            ),
        )

    return (
        "downloaded",
        (
            f"{destination.name} "
            f"({format_bytes(final_size)})"
        ),
    )


# ============================================================
# EXTENSION PARSER
# ============================================================

def parse_extensions(
    raw: str,
) -> tuple[str, ...]:
    """
    Convert:

        mp4,webm,mov

    into:

        (".mp4", ".webm", ".mov")
    """

    extensions: list[str] = []

    for value in raw.split(","):

        value = value.strip().lower()

        if not value:
            continue

        if not value.startswith("."):
            value = "." + value

        extensions.append(
            value
        )

    if not extensions:

        raise argparse.ArgumentTypeError(
            "At least one file extension is required."
        )

    # dict preserves insertion order and removes duplicates.
    return tuple(
        dict.fromkeys(
            extensions
        )
    )


# ============================================================
# ARGUMENT PARSER
# ============================================================

def build_parser() -> argparse.ArgumentParser:
    """
    Build command-line interface.
    """

    parser = argparse.ArgumentParser(
        description=(
            "Discover and download linked media files "
            "from an HTML archive/index page."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument(
        "url",
        nargs="?",
        default=DEFAULT_ARCHIVE_URL,

        help=(
            "Archive/index webpage URL."
        ),
    )

    parser.add_argument(
        "-o",
        "--output",

        type=Path,

        default=Path(
            "downloads"
        ),

        help=(
            "Directory where downloaded files are stored."
        ),
    )

    parser.add_argument(
        "-e",
        "--extensions",

        type=parse_extensions,

        default=DEFAULT_EXTENSIONS,

        help=(
            "Comma-separated file extensions, "
            "for example mp4,webm,mov."
        ),
    )

    parser.add_argument(
        "-w",
        "--workers",

        type=int,

        default=DEFAULT_WORKERS,

        help=(
            "Number of simultaneous downloads."
        ),
    )

    parser.add_argument(
        "--list-only",

        action="store_true",

        help=(
            "Discover and display matching files "
            "without downloading them."
        ),
    )

    parser.add_argument(
        "--overwrite",

        action="store_true",

        help=(
            "Overwrite matching existing files."
        ),
    )

    parser.add_argument(
        "--no-resume",

        action="store_true",

        help=(
            "Disable .part-file resume support."
        ),
    )

    parser.add_argument(
        "--sha256",

        action="store_true",

        help=(
            "Calculate a SHA-256 checksum after each download."
        ),
    )

    parser.add_argument(
        "--user-agent",

        default=DEFAULT_USER_AGENT,

        help=(
            "HTTP User-Agent header."
        ),
    )

    return parser


# ============================================================
# MAIN APPLICATION
# ============================================================

def main() -> int:
    """
    Application entry point.

    Return codes
    ------------

    0:
        Success.

    1:
        One or more network/download errors.

    2:
        Invalid arguments/configuration.

    130:
        Interrupted using Ctrl+C.
    """

    parser = build_parser()

    args = parser.parse_args()

    # --------------------------------------------------------
    # VALIDATE WORKER COUNT
    # --------------------------------------------------------

    if not 1 <= args.workers <= 32:

        print(
            "Error: --workers must be between 1 and 32.",
            file=sys.stderr,
        )

        return 2

    # --------------------------------------------------------
    # CREATE OUTPUT DIRECTORY
    # --------------------------------------------------------

    try:

        args.output.mkdir(
            parents=True,
            exist_ok=True,
        )

    except OSError as error:

        print(
            f"Unable to create output directory: {error}",
            file=sys.stderr,
        )

        return 1

    # --------------------------------------------------------
    # HEADER
    # --------------------------------------------------------

    print(
        "=" * 72
    )

    print(
        "ADVANCED ARCHIVE MEDIA DOWNLOADER"
    )

    print(
        "=" * 72
    )

    print(
        f"Archive:    {args.url}"
    )

    print(
        f"Output:     {args.output.resolve()}"
    )

    print(
        f"Extensions: {', '.join(args.extensions)}"
    )

    print(
        f"Workers:    {args.workers}"
    )

    print(
        f"Resume:     {'No' if args.no_resume else 'Yes'}"
    )

    print(
        f"SHA-256:    {'Yes' if args.sha256 else 'No'}"
    )

    print()

    # --------------------------------------------------------
    # DISCOVERY
    # --------------------------------------------------------

    print(
        "[SCAN] Reading archive..."
    )

    try:

        files = discover_files(
            archive_url=args.url,
            extensions=args.extensions,
            user_agent=args.user_agent,
        )

    except requests.RequestException as error:

        print(
            f"[ERROR] Failed to read archive page: {error}",
            file=sys.stderr,
        )

        return 1

    except Exception as error:

        print(
            f"[ERROR] Archive discovery failed: {error}",
            file=sys.stderr,
        )

        return 1

    # --------------------------------------------------------
    # NOTHING FOUND
    # --------------------------------------------------------

    if not files:

        print(
            "[INFO] No matching files found."
        )

        return 0

    # --------------------------------------------------------
    # DISPLAY DISCOVERY RESULTS
    # --------------------------------------------------------

    print()

    print(
        f"[FOUND] {len(files)} matching file(s)"
    )

    print(
        "-" * 72
    )

    for number, item in enumerate(
        files,
        start=1,
    ):

        print(
            f"{number:03d}. {item.filename}"
        )

        print(
            f"     {item.url}"
        )

    print(
        "-" * 72
    )

    # --------------------------------------------------------
    # LIST-ONLY MODE
    # --------------------------------------------------------

    if args.list_only:

        print(
            "\nList-only mode: no files downloaded."
        )

        return 0

    # --------------------------------------------------------
    # DOWNLOAD START
    # --------------------------------------------------------

    print()

    print(
        f"[START] Downloading {len(files)} file(s) "
        f"using {args.workers} worker(s)"
    )

    print()

    downloaded = 0
    skipped = 0
    failed = 0

    # --------------------------------------------------------
    # CONCURRENT DOWNLOADS
    # --------------------------------------------------------

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=args.workers,
        thread_name_prefix="archive-download",
    ) as executor:

        future_to_file = {
            executor.submit(
                download_file,

                item,

                args.output,

                args.user_agent,

                args.overwrite,

                not args.no_resume,

                args.sha256,

            ): item

            for item in files
        }

        try:

            for future in concurrent.futures.as_completed(
                future_to_file
            ):

                item = future_to_file[
                    future
                ]

                try:

                    status, message = future.result()

                except requests.RequestException as error:

                    failed += 1

                    print(
                        f"[FAILED] "
                        f"{item.filename}: "
                        f"network error: {error}",
                        file=sys.stderr,
                    )

                    continue

                except OSError as error:

                    failed += 1

                    print(
                        f"[FAILED] "
                        f"{item.filename}: "
                        f"filesystem error: {error}",
                        file=sys.stderr,
                    )

                    continue

                except Exception as error:

                    failed += 1

                    print(
                        f"[FAILED] "
                        f"{item.filename}: "
                        f"{type(error).__name__}: "
                        f"{error}",
                        file=sys.stderr,
                    )

                    continue

                if status == "downloaded":

                    downloaded += 1

                    print(
                        f"[OK] {message}"
                    )

                elif status == "skipped":

                    skipped += 1

                    print(
                        f"[SKIP] {message}"
                    )

        # ----------------------------------------------------
        # CTRL+C
        # ----------------------------------------------------

        except KeyboardInterrupt:

            print(
                "\n[INTERRUPTED] "
                "Cancelling queued downloads...",
                file=sys.stderr,
            )

            for future in future_to_file:

                future.cancel()

            print(
                "Partially transferred files remain as .part files "
                "and can normally be resumed next time."
            )

            return 130

    # --------------------------------------------------------
    # FINAL SUMMARY
    # --------------------------------------------------------

    print()

    print(
        "=" * 72
    )

    print(
        "DOWNLOAD SUMMARY"
    )

    print(
        "=" * 72
    )

    print(
        f"Discovered : {len(files)}"
    )

    print(
        f"Downloaded : {downloaded}"
    )

    print(
        f"Skipped    : {skipped}"
    )

    print(
        f"Failed     : {failed}"
    )

    print(
        f"Directory  : {args.output.resolve()}"
    )

    print(
        "=" * 72
    )

    if failed:

        print(
            "\nCompleted with one or more errors."
        )

        return 1

    print(
        "\nAll requested downloads completed successfully."
    )

    return 0


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    raise SystemExit(
        main()
    )
