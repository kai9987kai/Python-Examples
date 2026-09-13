#!/usr/bin/env python3
"""Advanced asynchronous HTTP downloader built on asyncio + aiohttp.

Features
--------
- Bounded global/per-host concurrency.
- Streams response bodies to disk instead of buffering whole files in RAM.
- Retries transient HTTP/network failures with exponential backoff + jitter.
- Honors Retry-After when practical.
- Atomic .part -> final rename.
- Safe resume support using Range + If-Range validators (ETag/Last-Modified).
- Collision-safe output filenames and explicit existing-file policy.
- Optional maximum file size enforcement.
- SHA-256 calculation for completed files.
- Clean synchronous and asynchronous APIs.
- CLI support, including reading URLs from a text file.

Requires Python 3.11+ and aiohttp 3.9+.

Install:
    python -m pip install "aiohttp>=3.9,<5"

Examples:
    python advanced_async_downloader.py https://example.com/file.zip
    python advanced_async_downloader.py --url-file urls.txt -o downloads -c 12
    python advanced_async_downloader.py URL1 URL2 --existing skip --max-size-mb 2048
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import random
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from enum import Enum
from pathlib import Path
from typing import Iterable, Sequence
from urllib.parse import unquote, urlsplit

import aiohttp


LOGGER = logging.getLogger("async_downloader")

RETRYABLE_HTTP_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504})
WINDOWS_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)
INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
CONTENT_RANGE_RE = re.compile(r"bytes\s+(\d+)-(\d+)/(\d+|\*)", re.IGNORECASE)
UNSATISFIED_RANGE_RE = re.compile(r"bytes\s+\*/(\d+)", re.IGNORECASE)


class ExistingPolicy(str, Enum):
    RENAME = "rename"
    SKIP = "skip"
    OVERWRITE = "overwrite"


class DownloadStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class DownloadError(Exception):
    """Base downloader error."""


class RetryableDownloadError(DownloadError):
    """Error that should normally be retried."""


class PermanentDownloadError(DownloadError):
    """Error that should not normally be retried."""


@dataclass(slots=True, frozen=True)
class DownloadConfig:
    output_dir: Path = Path("downloads")
    concurrency: int = 8
    per_host: int = 4
    retries: int = 4
    total_timeout: float | None = None
    connect_timeout: float = 15.0
    read_timeout: float = 60.0
    chunk_size: int = 1024 * 1024
    max_file_size: int | None = None
    existing: ExistingPolicy = ExistingPolicy.RENAME
    resume: bool = True
    calculate_sha256: bool = True
    max_redirects: int = 10
    backoff_base: float = 0.75
    backoff_cap: float = 30.0
    user_agent: str = "AdvancedAsyncDownloader/2.0 (+aiohttp)"
    trust_env: bool = False

    def __post_init__(self) -> None:
        if self.concurrency < 1:
            raise ValueError("concurrency must be >= 1")
        if self.per_host < 1:
            raise ValueError("per_host must be >= 1")
        if self.retries < 0:
            raise ValueError("retries must be >= 0")
        if self.chunk_size < 4096:
            raise ValueError("chunk_size must be >= 4096 bytes")
        if self.max_file_size is not None and self.max_file_size <= 0:
            raise ValueError("max_file_size must be positive")
        if self.max_redirects < 0:
            raise ValueError("max_redirects must be >= 0")


@dataclass(slots=True, frozen=True)
class DownloadJob:
    index: int
    url: str
    target: Path

    @property
    def part_path(self) -> Path:
        return self.target.with_name(self.target.name + ".part")

    @property
    def meta_path(self) -> Path:
        return self.target.with_name(self.target.name + ".part.json")


@dataclass(slots=True)
class DownloadResult:
    index: int
    url: str
    status: DownloadStatus
    path: Path | None = None
    bytes_written: int = 0
    elapsed: float = 0.0
    sha256: str | None = None
    http_status: int | None = None
    attempts: int = 0
    resumed_from: int = 0
    error: str | None = None

    @property
    def speed_bps(self) -> float:
        return self.bytes_written / self.elapsed if self.elapsed > 0 else 0.0


@dataclass(slots=True)
class DownloadReport:
    results: list[DownloadResult] = field(default_factory=list)

    @property
    def succeeded(self) -> list[DownloadResult]:
        return [r for r in self.results if r.status is DownloadStatus.SUCCESS]

    @property
    def failed(self) -> list[DownloadResult]:
        return [r for r in self.results if r.status is DownloadStatus.FAILED]

    @property
    def skipped(self) -> list[DownloadResult]:
        return [r for r in self.results if r.status is DownloadStatus.SKIPPED]

    @property
    def ok(self) -> bool:
        return not self.failed


class AsyncDownloader:
    """Reusable, bounded-concurrency aiohttp downloader."""

    def __init__(self, config: DownloadConfig | None = None) -> None:
        self.config = config or DownloadConfig()
        self.config.output_dir.mkdir(parents=True, exist_ok=True)

    async def download_many(self, urls: Iterable[str]) -> DownloadReport:
        cleaned_urls = self._validate_urls(urls)
        if not cleaned_urls:
            return DownloadReport()

        jobs = self._prepare_jobs(cleaned_urls)
        queue: asyncio.Queue[DownloadJob | None] = asyncio.Queue()
        results: list[DownloadResult | None] = [None] * len(jobs)

        for job in jobs:
            queue.put_nowait(job)

        timeout = aiohttp.ClientTimeout(
            total=self.config.total_timeout,
            connect=self.config.connect_timeout,
            sock_connect=self.config.connect_timeout,
            sock_read=self.config.read_timeout,
        )
        connector = aiohttp.TCPConnector(
            limit=self.config.concurrency,
            limit_per_host=min(self.config.per_host, self.config.concurrency),
            ttl_dns_cache=300,
            enable_cleanup_closed=True,
        )
        headers = {
            "User-Agent": self.config.user_agent,
            # A downloader should generally save the representation itself rather
            # than transparently receiving gzip/br transport compression.
            "Accept-Encoding": "identity",
        }

        async with aiohttp.ClientSession(
            timeout=timeout,
            connector=connector,
            headers=headers,
            trust_env=self.config.trust_env,
            auto_decompress=False,
        ) as session:
            workers = [
                asyncio.create_task(
                    self._worker(worker_id, queue, session, results),
                    name=f"download-worker-{worker_id}",
                )
                for worker_id in range(min(self.config.concurrency, len(jobs)))
            ]

            try:
                await queue.join()
            finally:
                for _ in workers:
                    queue.put_nowait(None)
                await asyncio.gather(*workers, return_exceptions=True)

        return DownloadReport([r for r in results if r is not None])

    async def _worker(
        self,
        worker_id: int,
        queue: asyncio.Queue[DownloadJob | None],
        session: aiohttp.ClientSession,
        results: list[DownloadResult | None],
    ) -> None:
        while True:
            job = await queue.get()
            try:
                if job is None:
                    return
                results[job.index] = await self._download_with_retries(job, session)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # Defensive isolation: one URL must not kill all workers.
                LOGGER.exception("Worker %s crashed while processing %s", worker_id, job.url if job else "<sentinel>")
                if job is not None:
                    results[job.index] = DownloadResult(
                        index=job.index,
                        url=job.url,
                        status=DownloadStatus.FAILED,
                        path=job.target,
                        error=f"Unexpected error: {type(exc).__name__}: {exc}",
                    )
            finally:
                queue.task_done()

    async def _download_with_retries(
        self,
        job: DownloadJob,
        session: aiohttp.ClientSession,
    ) -> DownloadResult:
        if job.target.exists() and self.config.existing is ExistingPolicy.SKIP:
            size = job.target.stat().st_size
            LOGGER.info("SKIP  %s -> %s (%s)", job.url, job.target, _human_bytes(size))
            return DownloadResult(
                index=job.index,
                url=job.url,
                status=DownloadStatus.SKIPPED,
                path=job.target,
                bytes_written=size,
            )

        if self.config.existing is ExistingPolicy.OVERWRITE:
            _safe_unlink(job.target)

        started = time.perf_counter()
        last_error: str | None = None
        last_status: int | None = None
        attempts_made = 0
        initial_resume_size = job.part_path.stat().st_size if job.part_path.exists() else 0

        for attempt in range(1, self.config.retries + 2):
            attempts_made = attempt
            try:
                result = await self._download_one_attempt(job, session, attempt, started)
                return result
            except PermanentDownloadError as exc:
                last_error = str(exc)
                LOGGER.error("FAIL  %s: %s", job.url, last_error)
                break
            except RetryableDownloadError as exc:
                last_error = str(exc)
            except asyncio.TimeoutError:
                last_error = "Request timed out"
            except (aiohttp.ClientError, OSError) as exc:
                last_error = f"{type(exc).__name__}: {exc}"

            if attempt > self.config.retries:
                break

            delay = self._backoff_delay(attempt)
            LOGGER.warning(
                "RETRY %s (%d/%d) in %.2fs: %s",
                job.url,
                attempt,
                self.config.retries + 1,
                delay,
                last_error,
            )
            await asyncio.sleep(delay)

        elapsed = time.perf_counter() - started
        return DownloadResult(
            index=job.index,
            url=job.url,
            status=DownloadStatus.FAILED,
            path=job.target,
            bytes_written=job.part_path.stat().st_size if job.part_path.exists() else 0,
            elapsed=elapsed,
            http_status=last_status,
            attempts=attempts_made,
            resumed_from=initial_resume_size,
            error=last_error or "Unknown download failure",
        )

    async def _download_one_attempt(
        self,
        job: DownloadJob,
        session: aiohttp.ClientSession,
        attempt: int,
        started: float,
    ) -> DownloadResult:
        resume_from, validator = self._resume_state(job)
        request_headers: dict[str, str] = {}

        if resume_from > 0:
            request_headers["Range"] = f"bytes={resume_from}-"
            if validator:
                request_headers["If-Range"] = validator

        LOGGER.info(
            "GET   %s%s",
            job.url,
            f" (resume at {_human_bytes(resume_from)})" if resume_from else "",
        )

        async with session.get(
            job.url,
            headers=request_headers or None,
            allow_redirects=True,
            max_redirects=self.config.max_redirects,
        ) as response:
            status = response.status

            if status in RETRYABLE_HTTP_STATUSES:
                retry_after = _parse_retry_after(response.headers.get("Retry-After"))
                if retry_after is not None and retry_after > 0:
                    # Keep server-requested pauses bounded. A malicious server must
                    # not be able to stall the process for hours.
                    await asyncio.sleep(min(retry_after, self.config.backoff_cap))
                raise RetryableDownloadError(f"HTTP {status} {response.reason or ''}".strip())

            if status == 416 and resume_from > 0:
                total = _parse_unsatisfied_total(response.headers.get("Content-Range"))
                if total is not None and total == resume_from and job.part_path.exists():
                    os.replace(job.part_path, job.target)
                    _safe_unlink(job.meta_path)
                    return await self._successful_result(
                        job=job,
                        attempt=attempt,
                        started=started,
                        http_status=status,
                        resumed_from=resume_from,
                    )
                self._discard_partial(job)
                raise RetryableDownloadError("Server rejected the stored partial file; restarting")

            if status >= 400:
                raise PermanentDownloadError(f"HTTP {status} {response.reason or ''}".strip())

            if status not in {200, 206}:
                raise PermanentDownloadError(f"Unexpected HTTP status {status}")

            write_mode = "wb"
            effective_resume = 0

            if resume_from > 0 and status == 206:
                range_start, _, total_size = _parse_content_range(response.headers.get("Content-Range"))
                if range_start != resume_from:
                    self._discard_partial(job)
                    raise RetryableDownloadError(
                        f"Invalid Content-Range start {range_start!r}; expected {resume_from}"
                    )
                write_mode = "ab"
                effective_resume = resume_from
            elif resume_from > 0 and status == 200:
                # Server ignored Range or If-Range failed because the remote file
                # changed. Restart from byte zero rather than corrupting the file.
                self._discard_partial(job)
                resume_from = 0

            expected_total = self._expected_total_size(response, effective_resume)
            self._enforce_size_limit(expected_total)
            self._write_resume_metadata(job, response)

            bytes_on_disk = effective_resume
            try:
                with job.part_path.open(write_mode) as output:
                    async for chunk in response.content.iter_chunked(self.config.chunk_size):
                        if not chunk:
                            continue
                        bytes_on_disk += len(chunk)
                        self._enforce_size_limit(bytes_on_disk)
                        output.write(chunk)
                    output.flush()
                    os.fsync(output.fileno())
            except asyncio.CancelledError:
                raise
            except OSError as exc:
                raise PermanentDownloadError(f"Disk write failed: {exc}") from exc

            if expected_total is not None and bytes_on_disk != expected_total:
                raise RetryableDownloadError(
                    f"Size mismatch: received {bytes_on_disk} bytes, expected {expected_total}"
                )

            if not job.part_path.exists():
                raise RetryableDownloadError("Temporary file disappeared before completion")

            os.replace(job.part_path, job.target)
            _safe_unlink(job.meta_path)

            return await self._successful_result(
                job=job,
                attempt=attempt,
                started=started,
                http_status=status,
                resumed_from=effective_resume,
            )

    async def _successful_result(
        self,
        *,
        job: DownloadJob,
        attempt: int,
        started: float,
        http_status: int,
        resumed_from: int,
    ) -> DownloadResult:
        elapsed = time.perf_counter() - started
        final_size = job.target.stat().st_size
        checksum = None
        if self.config.calculate_sha256:
            checksum = await asyncio.to_thread(_sha256_file, job.target, self.config.chunk_size)

        LOGGER.info(
            "OK    %s -> %s | %s | %s/s%s",
            job.url,
            job.target,
            _human_bytes(final_size),
            _human_bytes(final_size / elapsed if elapsed > 0 else 0),
            f" | sha256={checksum}" if checksum else "",
        )

        return DownloadResult(
            index=job.index,
            url=job.url,
            status=DownloadStatus.SUCCESS,
            path=job.target,
            bytes_written=final_size,
            elapsed=elapsed,
            sha256=checksum,
            http_status=http_status,
            attempts=attempt,
            resumed_from=resumed_from,
        )

    def _resume_state(self, job: DownloadJob) -> tuple[int, str | None]:
        if not self.config.resume or not job.part_path.exists():
            if not self.config.resume:
                self._discard_partial(job)
            return 0, None

        size = job.part_path.stat().st_size
        if size <= 0:
            self._discard_partial(job)
            return 0, None

        try:
            meta = json.loads(job.meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            # Resuming without a validator can splice together two different
            # remote versions of a file. Restart instead.
            self._discard_partial(job)
            return 0, None

        if meta.get("url") != job.url:
            self._discard_partial(job)
            return 0, None

        etag = meta.get("etag")
        last_modified = meta.get("last_modified")

        # If-Range must not use a weak ETag.
        validator = etag if isinstance(etag, str) and not etag.startswith("W/") else None
        if validator is None and isinstance(last_modified, str):
            validator = last_modified

        if validator is None:
            self._discard_partial(job)
            return 0, None

        return size, validator

    def _write_resume_metadata(self, job: DownloadJob, response: aiohttp.ClientResponse) -> None:
        if not self.config.resume:
            return

        etag = response.headers.get("ETag")
        last_modified = response.headers.get("Last-Modified")
        meta = {
            "url": job.url,
            "etag": etag,
            "last_modified": last_modified,
        }

        # A validator is required for safe cross-process resume. If none exists,
        # leave no metadata so a later run will safely restart the partial file.
        strong_etag = etag if etag and not etag.startswith("W/") else None
        if strong_etag is None and last_modified is None:
            _safe_unlink(job.meta_path)
            return

        temp_meta = job.meta_path.with_name(job.meta_path.name + ".tmp")
        temp_meta.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        os.replace(temp_meta, job.meta_path)

    def _expected_total_size(
        self,
        response: aiohttp.ClientResponse,
        resume_from: int,
    ) -> int | None:
        if response.status == 206:
            _, _, total = _parse_content_range(response.headers.get("Content-Range"))
            if total is not None:
                return total

        content_length = response.headers.get("Content-Length")
        if content_length and content_length.isdigit():
            return resume_from + int(content_length)
        return None

    def _enforce_size_limit(self, size: int | None) -> None:
        if (
            size is not None
            and self.config.max_file_size is not None
            and size > self.config.max_file_size
        ):
            raise PermanentDownloadError(
                f"File exceeds configured maximum size "
                f"({_human_bytes(size)} > {_human_bytes(self.config.max_file_size)})"
            )

    def _discard_partial(self, job: DownloadJob) -> None:
        _safe_unlink(job.part_path)
        _safe_unlink(job.meta_path)

    def _backoff_delay(self, attempt: int) -> float:
        exponential = min(
            self.config.backoff_cap,
            self.config.backoff_base * (2 ** max(0, attempt - 1)),
        )
        # Full-ish jitter prevents many concurrent jobs from retrying in lockstep.
        return min(self.config.backoff_cap, exponential * random.uniform(0.75, 1.25))

    def _validate_urls(self, urls: Iterable[str]) -> list[str]:
        cleaned: list[str] = []
        for raw in urls:
            url = raw.strip()
            if not url:
                continue
            parts = urlsplit(url)
            if parts.scheme.lower() not in {"http", "https"} or not parts.netloc:
                raise ValueError(f"Unsupported or malformed URL: {url!r}")
            cleaned.append(url)
        return cleaned

    def _prepare_jobs(self, urls: Sequence[str]) -> list[DownloadJob]:
        claimed: set[Path] = set()
        jobs: list[DownloadJob] = []

        for index, url in enumerate(urls):
            base_target = self.config.output_dir / _filename_from_url(url)
            target = base_target

            if self.config.existing is ExistingPolicy.RENAME:
                target = _unique_path(base_target, claimed)
            elif target in claimed:
                # Even overwrite/skip modes need separate targets for duplicate URLs
                # submitted in the same batch to avoid concurrent writers.
                target = _unique_path(base_target, claimed)

            claimed.add(target)
            jobs.append(DownloadJob(index=index, url=url, target=target))

        return jobs


def _filename_from_url(url: str) -> str:
    parts = urlsplit(url)
    path_name = unquote(Path(parts.path).name)

    if path_name:
        candidate = path_name
    else:
        host = parts.hostname or "download"
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:10]
        candidate = f"{host}-{digest}.download"

    candidate = INVALID_FILENAME_CHARS.sub("_", candidate)
    candidate = candidate.strip(" .")
    if not candidate:
        candidate = "download.bin"

    stem_upper = Path(candidate).stem.upper()
    if stem_upper in WINDOWS_RESERVED_NAMES:
        candidate = f"_{candidate}"

    # Keep enough room for suffixes and .part metadata on common filesystems.
    if len(candidate) > 220:
        suffix = Path(candidate).suffix[:20]
        stem = Path(candidate).stem[: 220 - len(suffix) - 13]
        digest = hashlib.sha256(candidate.encode("utf-8")).hexdigest()[:10]
        candidate = f"{stem}-{digest}{suffix}"

    return candidate


def _unique_path(base: Path, claimed: set[Path]) -> Path:
    if base not in claimed and not base.exists():
        return base

    suffix = base.suffix
    stem = base.stem
    for number in range(1, 1_000_000):
        candidate = base.with_name(f"{stem} ({number}){suffix}")
        if candidate not in claimed and not candidate.exists():
            return candidate
    raise RuntimeError(f"Could not allocate unique filename for {base}")


def _parse_content_range(value: str | None) -> tuple[int | None, int | None, int | None]:
    if not value:
        return None, None, None
    match = CONTENT_RANGE_RE.fullmatch(value.strip())
    if not match:
        return None, None, None
    start = int(match.group(1))
    end = int(match.group(2))
    total = None if match.group(3) == "*" else int(match.group(3))
    return start, end, total


def _parse_unsatisfied_total(value: str | None) -> int | None:
    if not value:
        return None
    match = UNSATISFIED_RANGE_RE.fullmatch(value.strip())
    return int(match.group(1)) if match else None


def _parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        target = parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if target.tzinfo is None:
        target = target.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    return max(0.0, (target - now).total_seconds())


def _sha256_file(path: Path, chunk_size: int) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        while chunk := file.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_unlink(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def _human_bytes(value: float | int) -> str:
    size = float(value)
    units = ("B", "KiB", "MiB", "GiB", "TiB", "PiB")
    for unit in units:
        if abs(size) < 1024.0 or unit == units[-1]:
            return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{size:.2f} PiB"


def _read_url_file(path: Path) -> list[str]:
    urls: list[str] = []
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            urls.append(stripped)
    return urls


def _print_report(report: DownloadReport) -> None:
    print("\n" + "=" * 88)
    print(
        f"Completed: {len(report.results)} | "
        f"success={len(report.succeeded)} | "
        f"skipped={len(report.skipped)} | "
        f"failed={len(report.failed)}"
    )
    print("=" * 88)

    for result in report.results:
        symbol = {
            DownloadStatus.SUCCESS: "OK",
            DownloadStatus.SKIPPED: "SKIP",
            DownloadStatus.FAILED: "FAIL",
        }[result.status]
        path_text = str(result.path) if result.path else "-"
        detail = f"{_human_bytes(result.bytes_written)}"
        if result.elapsed > 0:
            detail += f", {_human_bytes(result.speed_bps)}/s, {result.elapsed:.2f}s"
        if result.error:
            detail += f", error={result.error}"
        print(f"[{symbol:<4}] {result.url}\n       -> {path_text} ({detail})")
        if result.sha256:
            print(f"       sha256: {result.sha256}")


async def async_download(
    urls: Iterable[str],
    *,
    config: DownloadConfig | None = None,
) -> DownloadReport:
    """Asynchronous API suitable for existing asyncio applications/notebooks."""
    return await AsyncDownloader(config).download_many(urls)


def download(
    urls: Iterable[str],
    *,
    config: DownloadConfig | None = None,
    print_report: bool = True,
) -> DownloadReport:
    """Synchronous convenience API.

    Do not call this function from a thread that already has a running asyncio
    event loop; in that case use: ``await async_download(...)``.
    """
    report = asyncio.run(async_download(urls, config=config))
    if print_report:
        _print_report(report)
    return report


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Concurrent, resumable, streaming HTTP/HTTPS downloader using asyncio + aiohttp.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("urls", nargs="*", help="HTTP/HTTPS URLs to download")
    parser.add_argument(
        "--url-file",
        type=Path,
        help="Text file containing one URL per line (# comments and blank lines ignored)",
    )
    parser.add_argument("-o", "--output-dir", type=Path, default=Path("downloads"))
    parser.add_argument("-c", "--concurrency", type=int, default=8)
    parser.add_argument("--per-host", type=int, default=4)
    parser.add_argument("--retries", type=int, default=4)
    parser.add_argument("--connect-timeout", type=float, default=15.0)
    parser.add_argument("--read-timeout", type=float, default=60.0)
    parser.add_argument(
        "--total-timeout",
        type=float,
        default=None,
        help="Whole-request timeout in seconds; omit for no total cap",
    )
    parser.add_argument(
        "--chunk-size-kib",
        type=int,
        default=1024,
        help="Streaming write chunk size in KiB",
    )
    parser.add_argument(
        "--max-size-mb",
        type=float,
        default=None,
        help="Reject any individual file larger than this many MiB",
    )
    parser.add_argument(
        "--existing",
        choices=[p.value for p in ExistingPolicy],
        default=ExistingPolicy.RENAME.value,
        help="What to do if a destination filename already exists",
    )
    parser.add_argument("--no-resume", action="store_true", help="Disable safe partial-file resume")
    parser.add_argument("--no-sha256", action="store_true", help="Do not calculate SHA-256 after download")
    parser.add_argument("--max-redirects", type=int, default=10)
    parser.add_argument(
        "--trust-env",
        action="store_true",
        help="Honor proxy credentials/settings from the environment and .netrc",
    )
    parser.add_argument("-q", "--quiet", action="store_true", help="Suppress per-request logging")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    urls = list(args.urls)
    if args.url_file:
        try:
            urls.extend(_read_url_file(args.url_file))
        except OSError as exc:
            parser.error(f"Cannot read --url-file: {exc}")

    if not urls:
        parser.error("Provide at least one URL or use --url-file")

    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(message)s",
        datefmt="%H:%M:%S",
    )

    max_file_size = None
    if args.max_size_mb is not None:
        if args.max_size_mb <= 0:
            parser.error("--max-size-mb must be positive")
        max_file_size = int(args.max_size_mb * 1024 * 1024)

    try:
        config = DownloadConfig(
            output_dir=args.output_dir,
            concurrency=args.concurrency,
            per_host=args.per_host,
            retries=args.retries,
            total_timeout=args.total_timeout,
            connect_timeout=args.connect_timeout,
            read_timeout=args.read_timeout,
            chunk_size=args.chunk_size_kib * 1024,
            max_file_size=max_file_size,
            existing=ExistingPolicy(args.existing),
            resume=not args.no_resume,
            calculate_sha256=not args.no_sha256,
            max_redirects=args.max_redirects,
            trust_env=args.trust_env,
        )
    except ValueError as exc:
        parser.error(str(exc))

    try:
        report = download(urls, config=config, print_report=True)
    except KeyboardInterrupt:
        print("\nCancelled by user.", file=sys.stderr)
        return 130
    except ValueError as exc:
        print(f"Input error: {exc}", file=sys.stderr)
        return 2

    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
