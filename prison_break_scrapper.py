#!/usr/bin/env python3
"""
authorised_downloader.py

Download authorised media/assets from a JSON manifest into organised folders.

Example:
    python authorised_downloader.py assets.json --output downloads \
        --allowed-host media.example.com
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


LOG = logging.getLogger("downloader")
CHUNK_SIZE = 1024 * 1024  # 1 MB


def safe_filename(name: str) -> str:
    """Make a filename safe across common operating systems."""
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    return cleaned or "downloaded_file"


def make_session() -> requests.Session:
    """Create a requests session with sensible retry behaviour."""
    retry = Retry(
        total=4,
        backoff_factor=1,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
        raise_on_status=False,
    )

    session = requests.Session()
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update(
        {
            "User-Agent": "AuthorisedAssetDownloader/1.0",
            "Accept": "*/*",
        }
    )
    return session


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_url(url: str, allowed_hosts: set[str]) -> None:
    parsed = urlparse(url)

    if parsed.scheme not in {"http", "https"}:
        raise ValueError(f"Unsupported URL scheme: {parsed.scheme}")

    if not parsed.hostname:
        raise ValueError(f"Invalid URL: {url}")

    if allowed_hosts and parsed.hostname.lower() not in allowed_hosts:
        raise ValueError(
            f"Host '{parsed.hostname}' is not in the authorised allow-list."
        )


def download_file(
    session: requests.Session,
    item: dict[str, Any],
    output_root: Path,
    allowed_hosts: set[str],
) -> None:
    url = item["url"]
    validate_url(url, allowed_hosts)

    group = safe_filename(str(item.get("folder", "downloads")))
    source_name = Path(urlparse(url).path).name or "downloaded_file"
    filename = safe_filename(str(item.get("filename", source_name)))

    destination = output_root / group / filename
    partial_path = destination.with_suffix(destination.suffix + ".part")
    expected_hash = item.get("sha256", "").lower().strip()

    destination.parent.mkdir(parents=True, exist_ok=True)

    if destination.exists():
        if expected_hash and sha256_file(destination) != expected_hash:
            LOG.warning("Existing file has the wrong hash; downloading again: %s", destination)
        else:
            LOG.info("Already exists, skipped: %s", destination)
            return

    LOG.info("Downloading: %s", url)

    try:
        with session.get(url, stream=True, timeout=(10, 90)) as response:
            response.raise_for_status()

            total_size = int(response.headers.get("content-length", 0))
            downloaded = 0

            with partial_path.open("wb") as file:
                for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                    if not chunk:
                        continue

                    file.write(chunk)
                    downloaded += len(chunk)

                    if total_size:
                        percent = downloaded / total_size * 100
                        print(
                            f"\r{filename}: {percent:6.2f}% "
                            f"({downloaded / 1024 / 1024:.1f} MB)",
                            end="",
                            flush=True,
                        )

        print()

        if expected_hash:
            actual_hash = sha256_file(partial_path)
            if actual_hash != expected_hash:
                partial_path.unlink(missing_ok=True)
                raise ValueError(
                    f"SHA-256 mismatch for {filename}. "
                    "The partial file was removed."
                )

        partial_path.replace(destination)
        LOG.info("Saved: %s", destination)

    except requests.RequestException as exc:
        partial_path.unlink(missing_ok=True)
        raise RuntimeError(f"Download failed for {url}: {exc}") from exc


def load_manifest(manifest_path: Path) -> list[dict[str, Any]]:
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"Manifest not found: {manifest_path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON manifest: {exc}") from exc

    if not isinstance(data, list):
        raise ValueError("Manifest must contain a JSON list of download items.")

    for index, item in enumerate(data, start=1):
        if not isinstance(item, dict) or not item.get("url"):
            raise ValueError(f"Manifest item {index} must contain a 'url' field.")

    return data


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download authorised files listed in a JSON manifest."
    )
    parser.add_argument("manifest", type=Path, help="Path to assets.json")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("downloads"),
        help="Destination directory (default: downloads)",
    )
    parser.add_argument(
        "--allowed-host",
        action="append",
        default=[],
        help="Authorised hostname; repeat for multiple hosts.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show detailed logging.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    allowed_hosts = {host.lower().strip() for host in args.allowed_host if host.strip()}
    items = load_manifest(args.manifest)
    session = make_session()

    succeeded = 0
    failed = 0

    for item in items:
        try:
            download_file(session, item, args.output, allowed_hosts)
            succeeded += 1
        except (RuntimeError, ValueError) as exc:
            failed += 1
            LOG.error("%s", exc)

    LOG.info("Finished: %d succeeded, %d failed.", succeeded, failed)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
