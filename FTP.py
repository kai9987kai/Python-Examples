#!/usr/bin/env python3
"""
ftp_tool.py

List, upload, download, and manage files on FTP or explicit FTPS servers.

Examples:
    python ftp_tool.py list ftp.example.com
    python ftp_tool.py list ftp.example.com --user myuser
    python ftp_tool.py download ftp.example.com /remote/report.pdf ./report.pdf
    python ftp_tool.py upload ftp.example.com ./report.pdf /uploads/report.pdf
    python ftp_tool.py list ftp.example.com --ftps
"""

from __future__ import annotations

import argparse
import os
import ssl
from ftplib import FTP, FTP_TLS, all_errors, error_perm
from pathlib import Path


DEFAULT_TIMEOUT = 20


def connect_ftp(
    host: str,
    user: str,
    password: str,
    port: int,
    use_ftps: bool,
    timeout: int,
) -> FTP:
    """Connect and log in to an FTP or explicit FTPS server."""

    if use_ftps:
        context = ssl.create_default_context()
        ftp: FTP = FTP_TLS(
            timeout=timeout,
            context=context,
            encoding="utf-8",
        )
    else:
        ftp = FTP(timeout=timeout, encoding="utf-8")

    ftp.connect(host=host, port=port)
    ftp.login(user=user, passwd=password)
    ftp.set_pasv(True)  # Works better through most firewalls/NAT setups.

    if use_ftps:
        # Encrypt the data channel, not only the login/control channel.
        assert isinstance(ftp, FTP_TLS)
        ftp.prot_p()

    return ftp


def list_directory(ftp: FTP, remote_path: str) -> None:
    """Show a readable directory listing."""

    print(f"\nContents of: {remote_path}\n")

    try:
        # MLSD gives machine-readable names and metadata when supported.
        for name, facts in ftp.mlsd(remote_path):
            kind = facts.get("type", "unknown")
            size = facts.get("size", "-")
            modified = facts.get("modify", "-")
            print(f"{kind:9} {size:>12} {modified:>14}  {name}")

    except error_perm:
        # Older servers may not support MLSD.
        print("Server does not support MLSD; using NLST instead.\n")
        for name in ftp.nlst(remote_path):
            print(name)


def download_file(ftp: FTP, remote_file: str, local_file: Path) -> None:
    """Download one file in binary mode."""

    local_file.parent.mkdir(parents=True, exist_ok=True)

    with local_file.open("wb") as output_file:
        ftp.retrbinary(
            command=f"RETR {remote_file}",
            callback=output_file.write,
            blocksize=64 * 1024,
        )

    print(f"Downloaded: {remote_file} -> {local_file}")


def upload_file(ftp: FTP, local_file: Path, remote_file: str) -> None:
    """Upload one file in binary mode."""

    if not local_file.is_file():
        raise FileNotFoundError(f"Local file not found: {local_file}")

    with local_file.open("rb") as input_file:
        ftp.storbinary(
            command=f"STOR {remote_file}",
            fp=input_file,
            blocksize=64 * 1024,
        )

    print(f"Uploaded: {local_file} -> {remote_file}")


def delete_file(ftp: FTP, remote_file: str) -> None:
    """Delete a remote file."""

    ftp.delete(remote_file)
    print(f"Deleted: {remote_file}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="A small FTP / FTPS command-line client."
    )

    parser.add_argument(
        "action",
        choices=["list", "download", "upload", "delete", "pwd"],
        help="Action to perform.",
    )
    parser.add_argument("host", help="FTP server hostname, e.g. ftp.example.com")
    parser.add_argument(
        "path1",
        nargs="?",
        default=".",
        help="Remote path, or local file for uploads.",
    )
    parser.add_argument(
        "path2",
        nargs="?",
        help="Local destination for downloads, or remote path for uploads.",
    )

    parser.add_argument("--port", type=int, default=None)
    parser.add_argument(
        "--user",
        default=os.getenv("FTP_USER", "anonymous"),
        help="Username. Defaults to FTP_USER or anonymous.",
    )
    parser.add_argument(
        "--password",
        default=os.getenv("FTP_PASSWORD", "anonymous@"),
        help="Password. Defaults to FTP_PASSWORD or anonymous@.",
    )
    parser.add_argument(
        "--ftps",
        action="store_true",
        help="Use explicit FTPS with TLS encryption.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT,
        help=f"Connection timeout in seconds. Default: {DEFAULT_TIMEOUT}",
    )

    return parser


def main() -> None:
    args = build_parser().parse_args()

    port = args.port or (21 if args.ftps else 21)

    try:
        with connect_ftp(
            host=args.host,
            user=args.user,
            password=args.password,
            port=port,
            use_ftps=args.ftps,
            timeout=args.timeout,
        ) as ftp:

            print(f"Connected to: {ftp.getwelcome()}")

            if args.action == "list":
                list_directory(ftp, args.path1)

            elif args.action == "pwd":
                print(ftp.pwd())

            elif args.action == "download":
                if not args.path2:
                    raise ValueError(
                        "Download requires a remote file and a local destination."
                    )
                download_file(ftp, args.path1, Path(args.path2))

            elif args.action == "upload":
                if not args.path2:
                    raise ValueError(
                        "Upload requires a local file and a remote destination."
                    )
                upload_file(ftp, Path(args.path1), args.path2)

            elif args.action == "delete":
                delete_file(ftp, args.path1)

    except (all_errors, OSError, ValueError) as error:
        print(f"FTP error: {error}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
