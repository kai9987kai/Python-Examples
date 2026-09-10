#!/usr/bin/env python3
"""
puttylogs.py - safe, modern PuTTY log archiver.

Replaces the original zip.exe/os.system implementation with Python's standard
library and adds verification, race protection, dry-run mode, retention,
structured logging, and configurable paths.

Python 3.9+
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
import tempfile
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence

APP_NAME = "puttylogs"
APP_VERSION = "3.0.0"
DEFAULT_LOGS_DIR = Path(os.environ.get("PUTTY_LOG_DIR", r"C:\logs\puttylogs"))
CHUNK_SIZE = 1024 * 1024

log = logging.getLogger(APP_NAME)


@dataclass
class Result:
    source: Path
    status: str
    archive: Optional[Path] = None
    source_bytes: int = 0
    archive_bytes: int = 0
    sha256: str = ""
    message: str = ""


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Archive PuTTY .log files into individually verified ZIP files. "
            "A source log is deleted only after the archive passes CRC and "
            "SHA-256 verification and the source is confirmed unchanged."
        )
    )
    p.add_argument(
        "--logs-dir",
        type=Path,
        default=DEFAULT_LOGS_DIR,
        help=r'Log directory. Default: C:\logs\puttylogs or PUTTY_LOG_DIR.',
    )
    p.add_argument(
        "--archive-dir",
        type=Path,
        help="ZIP destination. Default: <logs-dir>/zipped_logs or PUTTY_ARCHIVE_DIR.",
    )
    p.add_argument("--pattern", default="*.log", help='Glob pattern. Default: "*.log".')
    p.add_argument("--recursive", action="store_true", help="Search subdirectories.")
    p.add_argument(
        "--min-age",
        type=float,
        default=60.0,
        metavar="SECONDS",
        help="Skip files modified within this many seconds. Default: 60.",
    )
    p.add_argument(
        "--compression-level",
        type=int,
        choices=range(10),
        default=9,
        metavar="0-9",
        help="DEFLATE compression level. Default: 9.",
    )
    p.add_argument("--keep-originals", action="store_true", help="Do not delete source logs.")
    p.add_argument("--dry-run", action="store_true", help="Make no filesystem changes.")
    p.add_argument("--no-manifest", action="store_true", help="Do not add a JSON manifest.")
    p.add_argument(
        "--retention-days",
        type=float,
        default=0.0,
        metavar="DAYS",
        help="Delete ZIP archives older than N days. 0 disables cleanup.",
    )
    p.add_argument("--log-file", type=Path, help="Optional diagnostic log file.")
    p.add_argument("--verbose", action="store_true", help="Enable debug logging.")
    p.add_argument("--version", action="version", version=f"%(prog)s {APP_VERSION}")
    return p


def configure_logging(verbose: bool, log_file: Optional[Path]) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if log_file:
        log_file = log_file.expanduser().resolve()
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))

    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(message)s",
        handlers=handlers,
        force=True,
    )


def stat_signature(st: os.stat_result) -> tuple[int, int, int, int]:
    """Fields used to detect replacement or modification of a source file."""
    return (
        int(getattr(st, "st_dev", 0)),
        int(getattr(st, "st_ino", 0)),
        int(st.st_size),
        int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1_000_000_000))),
    )


def sha256_file(path: Path) -> tuple[Optional[str], Optional[os.stat_result]]:
    """Hash a file only if it stays unchanged for the whole hashing pass."""
    try:
        with path.open("rb") as fh:
            before = os.fstat(fh.fileno())
            digest = hashlib.sha256()
            for block in iter(lambda: fh.read(CHUNK_SIZE), b""):
                digest.update(block)
            after = os.fstat(fh.fileno())

        current = path.stat()
    except (FileNotFoundError, PermissionError, OSError):
        return None, None

    if stat_signature(before) != stat_signature(after):
        return None, None
    if stat_signature(after) != stat_signature(current):
        return None, None

    return digest.hexdigest(), current


def is_inside(path: Path, directory: Path) -> bool:
    try:
        path.resolve().relative_to(directory.resolve())
        return True
    except ValueError:
        return False


def archive_dir_for(logs_dir: Path, explicit: Optional[Path]) -> Path:
    if explicit:
        return explicit.expanduser().resolve()

    env_value = os.environ.get("PUTTY_ARCHIVE_DIR")
    if env_value:
        return Path(env_value).expanduser().resolve()

    return logs_dir / "zipped_logs"


def unique_destination(archive_dir: Path, source: Path) -> Path:
    stamp = datetime.now().astimezone().strftime("%Y-%m-%d_%H%M%S_%f")
    base = archive_dir / f"{source.name}.{stamp}.zip"
    if not base.exists():
        return base

    for counter in range(1, 10000):
        candidate = archive_dir / f"{source.name}.{stamp}.{counter:04d}.zip"
        if not candidate.exists():
            return candidate

    raise RuntimeError(f"Could not allocate archive filename for {source}")


def manifest_for(
    source: Path,
    logs_dir: Path,
    source_stat: os.stat_result,
    digest: str,
) -> dict:
    try:
        relative = str(source.resolve().relative_to(logs_dir.resolve()))
    except ValueError:
        relative = source.name

    return {
        "schema": 1,
        "archiver": {"name": APP_NAME, "version": APP_VERSION},
        "source": {
            "relative_path": relative,
            "filename": source.name,
            "size_bytes": source_stat.st_size,
            "modified_utc": datetime.fromtimestamp(
                source_stat.st_mtime, timezone.utc
            ).isoformat().replace("+00:00", "Z"),
            "sha256": digest,
        },
        "archive": {
            "created_utc": datetime.now(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
            "compression": "ZIP_DEFLATED",
        },
    }


def verify_archive(path: Path, member: str, expected_sha256: str) -> tuple[bool, str]:
    try:
        if not zipfile.is_zipfile(path):
            return False, "Output is not a valid ZIP file."

        with zipfile.ZipFile(path, "r") as zf:
            bad = zf.testzip()
            if bad is not None:
                return False, f"CRC verification failed for {bad!r}."
            if member not in zf.namelist():
                return False, f"Expected member {member!r} is missing."

            digest = hashlib.sha256()
            with zf.open(member, "r") as fh:
                for block in iter(lambda: fh.read(CHUNK_SIZE), b""):
                    digest.update(block)

        if digest.hexdigest() != expected_sha256:
            return False, "Archived content SHA-256 does not match the source."

        return True, "verified"
    except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
        return False, f"ZIP verification failed: {exc}"


def archive_one(
    source: Path,
    logs_dir: Path,
    archive_dir: Path,
    compression_level: int,
    keep_originals: bool,
    include_manifest: bool,
    dry_run: bool,
) -> Result:
    if dry_run:
        try:
            size = source.stat().st_size
        except OSError as exc:
            return Result(source, "error", message=str(exc))
        action = "archive only" if keep_originals else "archive, verify, then delete source"
        return Result(source, "dry-run", source_bytes=size, message=f"Would {action}.")

    # First stable hash establishes exactly what bytes we intend to archive.
    digest, before = sha256_file(source)
    if digest is None or before is None:
        return Result(source, "changed", message="Source is unavailable or changing; skipped.")

    destination = unique_destination(archive_dir, source)

    fd, temp_name = tempfile.mkstemp(
        prefix=f".{source.name}.",
        suffix=".zip.tmp",
        dir=str(archive_dir),
    )
    os.close(fd)
    temp_zip = Path(temp_name)

    try:
        with zipfile.ZipFile(
            temp_zip,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=compression_level,
            allowZip64=True,
        ) as zf:
            zf.write(source, arcname=source.name)

            if include_manifest:
                manifest = manifest_for(source, logs_dir, before, digest)
                zf.writestr(
                    "__archive_manifest__.json",
                    json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                    compress_type=zipfile.ZIP_DEFLATED,
                    compresslevel=compression_level,
                )

        # Metadata check catches ordinary append/write activity during compression.
        try:
            after_write = source.stat()
        except OSError:
            return Result(source, "changed", source_bytes=before.st_size,
                          message="Source disappeared during archiving; source not deleted.")

        if stat_signature(after_write) != stat_signature(before):
            return Result(source, "changed", source_bytes=before.st_size,
                          message="Source changed while being compressed; source not deleted.")

        ok, reason = verify_archive(temp_zip, source.name, digest)
        if not ok:
            return Result(source, "error", source_bytes=before.st_size,
                          sha256=digest, message=reason)

        # Second source hash catches same-size rewrites and late modifications.
        digest2, stable = sha256_file(source)
        if digest2 != digest or stable is None:
            return Result(source, "changed", source_bytes=before.st_size,
                          sha256=digest,
                          message="Source changed after compression; source not deleted.")

        if stat_signature(stable) != stat_signature(before):
            return Result(source, "changed", source_bytes=before.st_size,
                          sha256=digest,
                          message="Source metadata changed after compression; source not deleted.")

        # Publish only a fully verified archive. temp_zip is created in archive_dir,
        # so os.replace() is atomic on normal local filesystems.
        os.replace(temp_zip, destination)
        archive_size = destination.stat().st_size

        if not keep_originals:
            try:
                latest = source.stat()
                if stat_signature(latest) != stat_signature(stable):
                    return Result(
                        source,
                        "archived-source-changed",
                        destination,
                        before.st_size,
                        archive_size,
                        digest,
                        "Archive is valid, but source changed before deletion; source retained.",
                    )
                source.unlink()
            except (PermissionError, OSError) as exc:
                return Result(
                    source,
                    "archived-delete-failed",
                    destination,
                    before.st_size,
                    archive_size,
                    digest,
                    f"Archive is valid, but source deletion failed: {exc}",
                )

        return Result(
            source,
            "archived",
            destination,
            before.st_size,
            archive_size,
            digest,
            "Archive created and verified.",
        )

    except (PermissionError, OSError, RuntimeError, zipfile.BadZipFile) as exc:
        return Result(source, "error", source_bytes=before.st_size,
                      sha256=digest, message=str(exc))
    finally:
        try:
            temp_zip.unlink(missing_ok=True)
        except OSError:
            log.warning("Could not remove temporary archive %s", temp_zip)


def discover(
    logs_dir: Path,
    archive_dir: Path,
    pattern: str,
    recursive: bool,
    min_age: float,
) -> tuple[list[Path], int]:
    iterator = logs_dir.rglob(pattern) if recursive else logs_dir.glob(pattern)
    now = time.time()
    found: list[Path] = []
    recent = 0

    for path in iterator:
        try:
            if is_inside(path, archive_dir) or path.is_symlink() or not path.is_file():
                continue

            age = now - path.stat().st_mtime
            if age < min_age:
                recent += 1
                log.info("Skipping recent/possibly active log (%0.1fs old): %s", age, path)
                continue

            found.append(path)
        except (FileNotFoundError, PermissionError, OSError) as exc:
            log.warning("Skipping %s: %s", path, exc)

    found.sort(key=lambda p: str(p).casefold())
    return found, recent


def retention_cleanup(archive_dir: Path, days: float, dry_run: bool) -> tuple[int, int]:
    if days <= 0:
        return 0, 0

    cutoff = time.time() - (days * 86400.0)
    removed = errors = 0

    for path in archive_dir.glob("*.zip"):
        try:
            if path.is_symlink() or not path.is_file() or path.stat().st_mtime >= cutoff:
                continue

            if dry_run:
                log.info("[DRY RUN] Would remove expired archive: %s", path)
            else:
                path.unlink()
                log.info("Removed expired archive: %s", path)
            removed += 1
        except (PermissionError, OSError) as exc:
            errors += 1
            log.error("Could not remove %s: %s", path, exc)

    return removed, errors


def human_bytes(value: int) -> str:
    size = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(size) < 1024.0 or unit == "TiB":
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{value} B"


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = parser()
    args = p.parse_args(argv)

    if args.min_age < 0:
        p.error("--min-age cannot be negative.")
    if args.retention_days < 0:
        p.error("--retention-days cannot be negative.")
    if not args.pattern.strip():
        p.error("--pattern cannot be empty.")

    logs_dir = args.logs_dir.expanduser().resolve()
    archive_dir = archive_dir_for(logs_dir, args.archive_dir)

    configure_logging(args.verbose, args.log_file)

    log.info("%s %s", APP_NAME, APP_VERSION)
    log.info("Logs directory:    %s", logs_dir)
    log.info("Archive directory: %s", archive_dir)

    if not logs_dir.is_dir():
        log.error("Logs directory does not exist or is not a directory: %s", logs_dir)
        return 2

    try:
        archive_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        log.error("Cannot create archive directory %s: %s", archive_dir, exc)
        return 2

    files, recent = discover(
        logs_dir,
        archive_dir,
        args.pattern,
        args.recursive,
        args.min_age,
    )

    results: list[Result] = []
    for source in files:
        log.info("Processing: %s", source)
        result = archive_one(
            source,
            logs_dir,
            archive_dir,
            args.compression_level,
            args.keep_originals,
            not args.no_manifest,
            args.dry_run,
        )
        results.append(result)

        if result.status == "archived":
            ratio = (
                result.archive_bytes / result.source_bytes * 100
                if result.source_bytes else 0
            )
            log.info(
                "Archived -> %s | %s -> %s (%0.1f%%) | SHA-256 %s",
                result.archive,
                human_bytes(result.source_bytes),
                human_bytes(result.archive_bytes),
                ratio,
                result.sha256,
            )
        elif result.status == "dry-run":
            log.info("[DRY RUN] %s | %s", source, result.message)
        elif result.status.startswith("archived-"):
            log.warning("%s | %s", result.archive, result.message)
        elif result.status == "changed":
            log.warning("%s | %s", source, result.message)
        else:
            log.error("%s | %s", source, result.message)

    expired, retention_errors = retention_cleanup(
        archive_dir,
        args.retention_days,
        args.dry_run,
    )

    archived = sum(r.status == "archived" for r in results)
    warnings = sum(r.status.startswith("archived-") for r in results)
    changed = sum(r.status == "changed" for r in results)
    errors = sum(r.status == "error" for r in results) + retention_errors
    dry_runs = sum(r.status == "dry-run" for r in results)

    log.info(
        "Summary: archived=%d, warnings=%d, changed/skipped=%d, "
        "recent=%d, dry-run=%d, errors=%d, expired=%d",
        archived, warnings, changed, recent, dry_runs, errors, expired,
    )

    return 1 if errors or warnings else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        raise SystemExit(130)
