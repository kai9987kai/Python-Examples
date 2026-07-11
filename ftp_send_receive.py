#!/usr/bin/env python3
"""Reliable FTP/FTPS command-line client.

Credentials are read from environment variables when available:
    FTP_HOST, FTP_USER, FTP_PASSWORD

FTPS is enabled by default. Use --plain-ftp only for legacy servers.
"""

from __future__ import annotations

import argparse
import ftplib
import getpass
import logging
import os
import posixpath
import socket
import ssl
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, TypeVar

T = TypeVar("T")
LOG = logging.getLogger("ftp-client")


class TransferError(RuntimeError):
    """Raised when an FTP operation cannot be completed."""


@dataclass(frozen=True)
class FTPConfig:
    host: str
    port: int = 21
    username: str = "anonymous"
    password: str = ""
    remote_dir: str = "/"
    timeout: float = 30.0
    retries: int = 3
    retry_delay: float = 2.0
    passive: bool = True
    use_tls: bool = True


class Progress:
    """Simple terminal progress reporter."""

    def __init__(self, total: int | None, label: str) -> None:
        self.total = total
        self.label = label
        self.transferred = 0
        self.last_print = 0.0

    def update(self, block: bytes) -> None:
        self.transferred += len(block)
        now = time.monotonic()
        if now - self.last_print >= 0.15:
            self._print(final=False)
            self.last_print = now

    def finish(self) -> None:
        self._print(final=True)
        print()

    def _print(self, *, final: bool) -> None:
        if self.total and self.total > 0:
            percent = min(100.0, (self.transferred / self.total) * 100)
            text = (
                f"\r{self.label}: {percent:6.2f}% "
                f"({format_bytes(self.transferred)}/{format_bytes(self.total)})"
            )
        else:
            text = f"\r{self.label}: {format_bytes(self.transferred)}"

        print(text, end="" if not final else "", flush=True)


def format_bytes(value: int) -> str:
    size = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if size < 1024 or unit == "TiB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{value} B"


class FTPClient:
    def __init__(self, config: FTPConfig) -> None:
        self.config = config
        self.ftp: ftplib.FTP | ftplib.FTP_TLS | None = None

    def __enter__(self) -> "FTPClient":
        self.connect()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:  # type: ignore[no-untyped-def]
        self.close()

    def connect(self) -> None:
        """Connect, authenticate, configure data mode, and select remote directory."""
        self.close()

        if self.config.use_tls:
            tls_context = ssl.create_default_context()
            ftp: ftplib.FTP | ftplib.FTP_TLS = ftplib.FTP_TLS(
                timeout=self.config.timeout,
                context=tls_context,
            )
        else:
            ftp = ftplib.FTP(timeout=self.config.timeout)

        try:
            LOG.info("Connecting to %s:%s", self.config.host, self.config.port)
            ftp.connect(self.config.host, self.config.port)
            ftp.login(self.config.username, self.config.password)

            if isinstance(ftp, ftplib.FTP_TLS):
                ftp.prot_p()  # Encrypt file listings and transfer data.

            ftp.set_pasv(self.config.passive)
            if self.config.remote_dir:
                ftp.cwd(self.config.remote_dir)

            self.ftp = ftp
            LOG.info("Connected; current directory: %s", ftp.pwd())
        except Exception:
            try:
                ftp.close()
            finally:
                raise

    def close(self) -> None:
        ftp, self.ftp = self.ftp, None
        if ftp is None:
            return
        try:
            ftp.quit()
        except (ftplib.Error, OSError, EOFError):
            ftp.close()

    def _require_connection(self) -> ftplib.FTP | ftplib.FTP_TLS:
        if self.ftp is None:
            raise TransferError("FTP client is not connected")
        return self.ftp

    def _retry(self, operation_name: str, operation: Callable[[], T]) -> T:
        last_error: Exception | None = None

        for attempt in range(1, self.config.retries + 1):
            try:
                if self.ftp is None:
                    self.connect()
                return operation()
            except (
                ftplib.Error,
                OSError,
                EOFError,
                socket.timeout,
            ) as exc:
                last_error = exc
                LOG.warning(
                    "%s failed on attempt %d/%d: %s",
                    operation_name,
                    attempt,
                    self.config.retries,
                    exc,
                )
                self.close()
                if attempt < self.config.retries:
                    time.sleep(self.config.retry_delay * attempt)

        raise TransferError(
            f"{operation_name} failed after {self.config.retries} attempts"
        ) from last_error

    def pwd(self) -> str:
        return self._retry("read current directory", lambda: self._require_connection().pwd())

    def list_directory(self, remote_path: str = ".") -> list[str]:
        def operation() -> list[str]:
            ftp = self._require_connection()
            lines: list[str] = []
            ftp.retrlines(f"LIST {remote_path}", lines.append)
            return lines

        return self._retry(f"list {remote_path}", operation)

    def make_directories(self, remote_path: str) -> None:
        """Create a remote directory tree without changing the final working directory."""
        normalized = posixpath.normpath(remote_path)
        if normalized in ("", ".", "/"):
            return

        def operation() -> None:
            ftp = self._require_connection()
            original = ftp.pwd()
            try:
                if normalized.startswith("/"):
                    ftp.cwd("/")

                for part in normalized.split("/"):
                    if not part or part == ".":
                        continue
                    try:
                        ftp.cwd(part)
                    except ftplib.error_perm:
                        ftp.mkd(part)
                        ftp.cwd(part)
            finally:
                ftp.cwd(original)

        self._retry(f"create directory {remote_path}", operation)

    def delete(self, remote_path: str) -> None:
        self._retry(
            f"delete {remote_path}",
            lambda: self._require_connection().delete(remote_path),
        )

    def download(
        self,
        remote_path: str,
        local_path: Path,
        *,
        resume: bool = False,
        block_size: int = 64 * 1024,
    ) -> None:
        local_path = local_path.expanduser().resolve()
        local_path.parent.mkdir(parents=True, exist_ok=True)
        partial_path = local_path.with_name(local_path.name + ".part")

        def operation() -> None:
            ftp = self._require_connection()
            total = safe_remote_size(ftp, remote_path)
            offset = partial_path.stat().st_size if resume and partial_path.exists() else 0

            if total is not None and offset > total:
                LOG.warning("Partial file is larger than remote file; restarting")
                offset = 0

            mode = "ab" if offset else "wb"
            progress = Progress(total, f"Downloading {posixpath.basename(remote_path)}")
            progress.transferred = offset

            with partial_path.open(mode) as destination:
                def write_block(block: bytes) -> None:
                    destination.write(block)
                    progress.update(block)

                ftp.retrbinary(
                    f"RETR {remote_path}",
                    write_block,
                    blocksize=block_size,
                    rest=offset or None,
                )
                destination.flush()
                os.fsync(destination.fileno())

            progress.finish()

            if total is not None and partial_path.stat().st_size != total:
                raise TransferError(
                    f"Size verification failed: expected {total} bytes, "
                    f"received {partial_path.stat().st_size} bytes"
                )

            partial_path.replace(local_path)

        self._retry(f"download {remote_path}", operation)
        LOG.info("Saved to %s", local_path)

    def upload(
        self,
        local_path: Path,
        remote_path: str | None = None,
        *,
        resume: bool = False,
        create_dirs: bool = False,
        block_size: int = 64 * 1024,
    ) -> None:
        local_path = local_path.expanduser().resolve()
        if not local_path.is_file():
            raise FileNotFoundError(f"Local file not found: {local_path}")

        remote_path = remote_path or local_path.name
        remote_dir = posixpath.dirname(remote_path)
        if create_dirs and remote_dir:
            self.make_directories(remote_dir)

        def operation() -> None:
            ftp = self._require_connection()
            total = local_path.stat().st_size
            offset = safe_remote_size(ftp, remote_path) if resume else 0
            offset = offset or 0

            if offset > total:
                LOG.warning("Remote file is larger than local file; restarting")
                offset = 0
            elif offset == total and total > 0:
                LOG.info("Remote file already matches local size; nothing to upload")
                return

            progress = Progress(total, f"Uploading {local_path.name}")
            progress.transferred = offset

            with local_path.open("rb") as source:
                source.seek(offset)

                def sent_block(block: bytes) -> None:
                    progress.update(block)

                try:
                    ftp.storbinary(
                        f"STOR {remote_path}",
                        source,
                        blocksize=block_size,
                        callback=sent_block,
                        rest=offset or None,
                    )
                except ftplib.error_perm:
                    if not offset:
                        raise
                    LOG.warning("Server does not support resumed uploads; restarting")
                    source.seek(0)
                    progress.transferred = 0
                    ftp.storbinary(
                        f"STOR {remote_path}",
                        source,
                        blocksize=block_size,
                        callback=sent_block,
                    )

            progress.finish()
            remote_size = safe_remote_size(ftp, remote_path)
            if remote_size is not None and remote_size != total:
                raise TransferError(
                    f"Size verification failed: local={total} bytes, remote={remote_size} bytes"
                )

        self._retry(f"upload {local_path}", operation)
        LOG.info("Uploaded to %s", remote_path)


def safe_remote_size(ftp: ftplib.FTP, remote_path: str) -> int | None:
    """Return remote file size when supported by the server."""
    try:
        ftp.voidcmd("TYPE I")
        size = ftp.size(remote_path)
        return int(size) if size is not None else None
    except (ftplib.error_perm, ValueError, TypeError):
        return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Upload and download files using FTP or encrypted FTPS."
    )
    parser.add_argument("--host", default=os.getenv("FTP_HOST"))
    parser.add_argument("--port", type=int, default=int(os.getenv("FTP_PORT", "21")))
    parser.add_argument("--user", default=os.getenv("FTP_USER"))
    parser.add_argument("--remote-dir", default=os.getenv("FTP_REMOTE_DIR", "/"))
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--retry-delay", type=float, default=2.0)
    parser.add_argument(
        "--plain-ftp",
        action="store_true",
        help="Disable TLS. Credentials and data will be sent unencrypted.",
    )
    parser.add_argument(
        "--active",
        action="store_true",
        help="Use active mode instead of passive mode.",
    )
    parser.add_argument("--debug", action="store_true")

    commands = parser.add_subparsers(dest="command", required=True)

    upload = commands.add_parser("upload", help="Upload one file")
    upload.add_argument("local", type=Path)
    upload.add_argument("remote", nargs="?")
    upload.add_argument("--resume", action="store_true")
    upload.add_argument("--create-dirs", action="store_true")

    download = commands.add_parser("download", help="Download one file")
    download.add_argument("remote")
    download.add_argument("local", type=Path, nargs="?")
    download.add_argument("--resume", action="store_true")

    list_cmd = commands.add_parser("list", help="List a remote directory")
    list_cmd.add_argument("path", nargs="?", default=".")

    mkdir = commands.add_parser("mkdir", help="Create a remote directory tree")
    mkdir.add_argument("path")

    delete = commands.add_parser("delete", help="Delete a remote file")
    delete.add_argument("path")

    commands.add_parser("pwd", help="Print current remote directory")
    return parser


def resolve_config(args: argparse.Namespace) -> FTPConfig:
    host = args.host or input("FTP host: ").strip()
    username = args.user or input("FTP username: ").strip()
    password = os.getenv("FTP_PASSWORD")
    if password is None:
        password = getpass.getpass("FTP password: ")

    if not host:
        raise ValueError("FTP host is required")
    if not username:
        raise ValueError("FTP username is required")
    if args.port < 1 or args.port > 65535:
        raise ValueError("Port must be between 1 and 65535")
    if args.retries < 1:
        raise ValueError("Retries must be at least 1")

    return FTPConfig(
        host=host,
        port=args.port,
        username=username,
        password=password,
        remote_dir=args.remote_dir,
        timeout=args.timeout,
        retries=args.retries,
        retry_delay=args.retry_delay,
        passive=not args.active,
        use_tls=not args.plain_ftp,
    )


def run_command(client: FTPClient, args: argparse.Namespace) -> None:
    if args.command == "upload":
        client.upload(
            args.local,
            args.remote,
            resume=args.resume,
            create_dirs=args.create_dirs,
        )
    elif args.command == "download":
        local = args.local or Path(posixpath.basename(args.remote))
        client.download(args.remote, local, resume=args.resume)
    elif args.command == "list":
        for line in client.list_directory(args.path):
            print(line)
    elif args.command == "mkdir":
        client.make_directories(args.path)
        print(f"Created: {args.path}")
    elif args.command == "delete":
        client.delete(args.path)
        print(f"Deleted: {args.path}")
    elif args.command == "pwd":
        print(client.pwd())
    else:
        raise ValueError(f"Unknown command: {args.command}")


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    try:
        config = resolve_config(args)
        with FTPClient(config) as client:
            run_command(client, args)
        return 0
    except KeyboardInterrupt:
        LOG.error("Cancelled by user")
        return 130
    except (ValueError, FileNotFoundError, TransferError, ftplib.Error, OSError) as exc:
        LOG.error("%s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
