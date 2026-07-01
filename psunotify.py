#!/usr/bin/env python3
"""
PDF Collector
-------------

Searches for PDF links using Google Programmable Search / Custom Search JSON API
or reads URLs from a text file, then downloads verified PDFs safely.

Install:
    pip install requests

Google search mode requires:
    GOOGLE_API_KEY
    GOOGLE_CSE_ID

Example:
    python pdf_collector.py --query "GATE PSU 2017" --results 20 --output psu_pdfs

URL-list mode:
    python pdf_collector.py --urls-file urls.txt --output psu_pdfs
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
import time
from dataclasses import dataclass
from itertools import chain
from pathlib import Path
from typing import Iterable
from urllib.parse import unquote, urljoin, urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


GOOGLE_SEARCH_ENDPOINT = "https://customsearch.googleapis.com/customsearch/v1"
CHUNK_SIZE = 64 * 1024
MAX_REDIRECTS = 5


@dataclass
class DownloadResult:
    url: str
    status: str
    path: Path | None = None
    detail: str = ""
    sha256: str | None = None


class DownloadTooLarge(Exception):
    pass


def build_session() -> requests.Session:
    """Create an HTTP session with retries for temporary failures."""
    retry = Retry(
        total=4,
        connect=4,
        read=4,
        status=4,
        backoff_factor=0.8,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        respect_retry_after_header=True,
    )

    session = requests.Session()
    adapter = HTTPAdapter(max_retries=retry)

    session.mount("https://", adapter)
    session.mount("http://", adapter)

    session.headers.update(
        {
            "User-Agent": "PDF-Collector/2.0 (+local educational downloader)",
            "Accept": "application/pdf,application/octet-stream;q=0.9,*/*;q=0.5",
        }
    )

    return session


def valid_http_url(url: str) -> bool:
    """Allow only normal HTTP/HTTPS URLs."""
    parsed = urlparse(url.strip())
    return (
        parsed.scheme in {"http", "https"}
        and bool(parsed.netloc)
        and not parsed.username
        and not parsed.password
    )


def safe_filename(url: str, index: int) -> str:
    """Build a clean local filename from the final URL."""
    parsed = urlparse(url)
    original_name = unquote(Path(parsed.path).name)

    if not original_name:
        original_name = f"document_{index}.pdf"

    stem = Path(original_name).stem or f"document_{index}"
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._-")
    stem = stem[:90] or f"document_{index}"

    return f"{index:03d}_{stem}.pdf"


def unique_path(directory: Path, filename: str) -> Path:
    """Avoid overwriting an existing downloaded PDF."""
    candidate = directory / filename
    counter = 2

    while candidate.exists():
        candidate = directory / f"{Path(filename).stem}_{counter}.pdf"
        counter += 1

    return candidate


def get_with_checked_redirects(
    session: requests.Session,
    url: str,
    timeout: tuple[int, int],
) -> tuple[requests.Response, str]:
    """Follow redirects manually so every target remains HTTP/HTTPS."""
    current_url = url

    for _ in range(MAX_REDIRECTS + 1):
        if not valid_http_url(current_url):
            raise ValueError(f"Blocked unsupported URL: {current_url}")

        response = session.get(
            current_url,
            stream=True,
            timeout=timeout,
            allow_redirects=False,
        )

        if response.is_redirect or response.is_permanent_redirect:
            location = response.headers.get("Location")
            response.close()

            if not location:
                raise requests.RequestException("Redirect response had no Location header.")

            current_url = urljoin(current_url, location)
            continue

        response.raise_for_status()
        return response, current_url

    raise requests.TooManyRedirects(f"Too many redirects for {url}")


def download_pdf(
    session: requests.Session,
    url: str,
    output_dir: Path,
    index: int,
    max_bytes: int,
    timeout: tuple[int, int],
) -> DownloadResult:
    """Download one PDF, validating its file signature before saving."""
    response: requests.Response | None = None
    part_path: Path | None = None

    try:
        response, final_url = get_with_checked_redirects(session, url, timeout)

        content_length = response.headers.get("Content-Length")
        if content_length and int(content_length) > max_bytes:
            return DownloadResult(
                url=url,
                status="skipped",
                detail=f"File exceeds configured size limit ({content_length} bytes).",
            )

        content_type = response.headers.get("Content-Type", "").lower()
        stream = response.iter_content(chunk_size=CHUNK_SIZE)
        first_chunk = next(stream, b"")

        # A proper PDF normally has %PDF- near the beginning.
        # This prevents saving HTML errors, login pages, or fake PDF links.
        if b"%PDF-" not in first_chunk[:1024]:
            return DownloadResult(
                url=url,
                status="skipped",
                detail=(
                    f"Response is not a verified PDF "
                    f"(Content-Type: {content_type or 'unknown'})."
                ),
            )

        target_path = unique_path(output_dir, safe_filename(final_url, index))
        part_path = target_path.with_suffix(".part")

        bytes_written = 0
        digest = hashlib.sha256()

        with part_path.open("wb") as file_handle:
            for chunk in chain((first_chunk,), stream):
                if not chunk:
                    continue

                bytes_written += len(chunk)

                if bytes_written > max_bytes:
                    raise DownloadTooLarge(
                        f"Download exceeded the {max_bytes // (1024 * 1024)} MB limit."
                    )

                digest.update(chunk)
                file_handle.write(chunk)

        part_path.replace(target_path)

        return DownloadResult(
            url=url,
            status="downloaded",
            path=target_path,
            detail=f"{bytes_written:,} bytes",
            sha256=digest.hexdigest(),
        )

    except DownloadTooLarge as error:
        if part_path and part_path.exists():
            part_path.unlink()

        return DownloadResult(url=url, status="skipped", detail=str(error))

    except (requests.RequestException, ValueError, OSError) as error:
        if part_path and part_path.exists():
            part_path.unlink()

        return DownloadResult(url=url, status="failed", detail=str(error))

    finally:
        if response is not None:
            response.close()


def google_pdf_search(
    session: requests.Session,
    query: str,
    api_key: str,
    cse_id: str,
    total_results: int,
    start: int,
    timeout: tuple[int, int],
) -> list[str]:
    """Return PDF links using the documented Google Custom Search endpoint."""
    links: list[str] = []
    seen: set[str] = set()
    position = start

    while len(links) < total_results and position <= 100:
        batch_size = min(10, total_results - len(links), 101 - position)

        params = {
            "key": api_key,
            "cx": cse_id,
            "q": query,
            "fileType": "pdf",
            "num": batch_size,
            "start": position,
            "safe": "active",
        }

        response = session.get(
            GOOGLE_SEARCH_ENDPOINT,
            params=params,
            timeout=timeout,
        )
        response.raise_for_status()

        payload = response.json()
        items = payload.get("items", [])

        if not items:
            break

        for item in items:
            link = item.get("link", "").strip()

            if link and valid_http_url(link) and link not in seen:
                links.append(link)
                seen.add(link)

        position += batch_size

    return links


def read_url_file(file_path: Path) -> list[str]:
    """Read one URL per line; blank lines and # comments are ignored."""
    urls: list[str] = []
    seen: set[str] = set()

    for line in file_path.read_text(encoding="utf-8").splitlines():
        url = line.strip()

        if not url or url.startswith("#"):
            continue

        if valid_http_url(url) and url not in seen:
            urls.append(url)
            seen.add(url)

    return urls


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Search for and download verified PDF files."
    )

    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument(
        "--query",
        help="Search query, e.g. 'GATE PSU 2017'. Requires Google API credentials.",
    )
    source_group.add_argument(
        "--urls-file",
        type=Path,
        help="Text file containing one direct PDF URL per line.",
    )

    parser.add_argument(
        "--output",
        type=Path,
        default=Path("downloads"),
        help="Folder where PDFs will be saved. Default: downloads",
    )
    parser.add_argument(
        "--results",
        type=int,
        default=10,
        help="Number of Google results to request, 1–100. Default: 10",
    )
    parser.add_argument(
        "--start",
        type=int,
        default=1,
        help="Google result position to start from, e.g. 1, 11, 21. Default: 1",
    )
    parser.add_argument(
        "--max-mb",
        type=int,
        default=50,
        help="Largest accepted PDF size in MB. Default: 50",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.4,
        help="Pause between document downloads in seconds. Default: 0.4",
    )
    parser.add_argument(
        "--connect-timeout",
        type=int,
        default=8,
        help="Connection timeout in seconds. Default: 8",
    )
    parser.add_argument(
        "--read-timeout",
        type=int,
        default=30,
        help="Read timeout in seconds. Default: 30",
    )

    args = parser.parse_args()

    if not 1 <= args.results <= 100:
        parser.error("--results must be between 1 and 100.")

    if not 1 <= args.start <= 100:
        parser.error("--start must be between 1 and 100.")

    if args.max_mb < 1:
        parser.error("--max-mb must be at least 1.")

    return args


def main() -> int:
    args = parse_args()
    timeout = (args.connect_timeout, args.read_timeout)
    max_bytes = args.max_mb * 1024 * 1024

    args.output.mkdir(parents=True, exist_ok=True)
    session = build_session()

    try:
        if args.query:
            api_key = os.environ.get("GOOGLE_API_KEY")
            cse_id = os.environ.get("GOOGLE_CSE_ID")

            if not api_key or not cse_id:
                print(
                    "Missing GOOGLE_API_KEY or GOOGLE_CSE_ID environment variables.",
                    file=sys.stderr,
                )
                return 2

            print(f"Searching for PDFs: {args.query!r}")
            urls = google_pdf_search(
                session=session,
                query=args.query,
                api_key=api_key,
                cse_id=cse_id,
                total_results=args.results,
                start=args.start,
                timeout=timeout,
            )
        else:
            if not args.urls_file.exists():
                print(f"URL list not found: {args.urls_file}", file=sys.stderr)
                return 2

            urls = read_url_file(args.urls_file)

        if not urls:
            print("No usable URLs found.")
            return 1

        print(f"Found {len(urls)} candidate URL(s). Downloading to: {args.output}\n")

        saved_hashes: dict[str, Path] = {}
        downloaded = 0
        skipped = 0
        failed = 0

        for index, url in enumerate(urls, start=1):
            print(f"[{index}/{len(urls)}] {url}")

            result = download_pdf(
                session=session,
                url=url,
                output_dir=args.output,
                index=index,
                max_bytes=max_bytes,
                timeout=timeout,
            )

            if result.status == "downloaded" and result.path and result.sha256:
                existing = saved_hashes.get(result.sha256)

                if existing:
                    result.path.unlink(missing_ok=True)
                    skipped += 1
                    print(f"  Duplicate of {existing.name}; skipped.")
                else:
                    saved_hashes[result.sha256] = result.path
                    downloaded += 1
                    print(f"  Saved: {result.path.name} ({result.detail})")

            elif result.status == "skipped":
                skipped += 1
                print(f"  Skipped: {result.detail}")

            else:
                failed += 1
                print(f"  Failed: {result.detail}")

            if args.delay > 0 and index < len(urls):
                time.sleep(args.delay)

        print(
            f"\nFinished — downloaded: {downloaded}, "
            f"skipped: {skipped}, failed: {failed}"
        )

        return 0 if downloaded else 1

    except requests.RequestException as error:
        print(f"Search/network error: {error}", file=sys.stderr)
        return 1

    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
