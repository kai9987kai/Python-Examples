#!/usr/bin/env python3
"""
Log Hit Monitor
Count client-IP hits in Apache or Nginx access logs.

Examples:
    python log_hits.py /var/log/nginx/access.log
    python log_hits.py /var/log/apache2/access.log --top 20
    python log_hits.py /var/log/nginx/access.log --format json
    sudo python log_hits.py /var/log/nginx/access.log --follow
    zcat /var/log/nginx/access.log.1.gz | python log_hits.py -
"""

from __future__ import annotations

import argparse
import csv
import gzip
import ipaddress
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path
from typing import IO, Iterator


def extract_ip(line: str) -> str | None:
    """Return a valid IPv4/IPv6 address from the first log field."""
    if not line.strip():
        return None

    candidate = line.split(maxsplit=1)[0]

    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return None


def is_public_ip(address: str) -> bool:
    """Return True only for globally routable addresses."""
    ip = ipaddress.ip_address(address)
    return ip.is_global


def open_log(path: str) -> IO[str]:
    """Open a normal or gzip-compressed log file as text."""
    if path.endswith(".gz"):
        return gzip.open(path, mode="rt", encoding="utf-8", errors="replace")

    return open(path, mode="r", encoding="utf-8", errors="replace")


def read_ips(
    file_handle: IO[str],
    counts: Counter[str],
    public_only: bool = False,
) -> tuple[int, int]:
    """Read log lines and update IP hit counts."""
    valid_lines = 0
    skipped_lines = 0

    for line in file_handle:
        ip = extract_ip(line)

        if ip is None:
            skipped_lines += 1
            continue

        if public_only and not is_public_ip(ip):
            skipped_lines += 1
            continue

        counts[ip] += 1
        valid_lines += 1

    return valid_lines, skipped_lines


def ranked_results(
    counts: Counter[str],
    top: int | None,
    minimum_hits: int,
) -> list[tuple[str, int]]:
    """Sort and filter IP results."""
    results = [
        (ip, hits)
        for ip, hits in counts.most_common()
        if hits >= minimum_hits
    ]

    return results[:top] if top else results


def print_table(results: list[tuple[str, int]]) -> None:
    """Print a readable terminal table."""
    if not results:
        print("No matching IP addresses found.")
        return

    ip_width = max(len("IP Address"), max(len(ip) for ip, _ in results))
    hit_width = max(len("Hits"), max(len(str(hits)) for _, hits in results))

    print(f"{'IP Address':<{ip_width}}  {'Hits':>{hit_width}}")
    print(f"{'-' * ip_width}  {'-' * hit_width}")

    for ip, hits in results:
        print(f"{ip:<{ip_width}}  {hits:>{hit_width}}")


def print_json(results: list[tuple[str, int]]) -> None:
    """Print machine-readable JSON."""
    payload = [
        {"ip_address": ip, "hits": hits}
        for ip, hits in results
    ]
    print(json.dumps(payload, indent=2))


def print_csv(results: list[tuple[str, int]]) -> None:
    """Print CSV to standard output."""
    writer = csv.writer(sys.stdout)
    writer.writerow(["ip_address", "hits"])
    writer.writerows(results)


def display_report(
    counts: Counter[str],
    output_format: str,
    top: int | None,
    minimum_hits: int,
) -> None:
    results = ranked_results(counts, top, minimum_hits)

    if output_format == "json":
        print_json(results)
    elif output_format == "csv":
        print_csv(results)
    else:
        print_table(results)


def follow_log(
    path: str,
    counts: Counter[str],
    public_only: bool,
    refresh_seconds: float,
    top: int | None,
    minimum_hits: int,
) -> None:
    """
    Follow a normal log file, detecting truncation and typical log rotation.
    Gzip logs cannot be followed.
    """
    if path.endswith(".gz"):
        raise ValueError("Live monitoring is not available for gzip files.")

    log_path = Path(path)

    with open_log(path) as log_file:
        log_file.seek(0, os.SEEK_END)
        current_inode = os.fstat(log_file.fileno()).st_ino
        last_report = time.monotonic()

        print(f"Monitoring {path}. Press Ctrl+C to stop.")

        while True:
            line = log_file.readline()

            if line:
                ip = extract_ip(line)
                if ip and (not public_only or is_public_ip(ip)):
                    counts[ip] += 1
                continue

            try:
                stat = log_path.stat()
            except FileNotFoundError:
                time.sleep(1)
                continue

            # Handles normal truncation and common rotate-and-recreate behaviour.
            if stat.st_ino != current_inode or stat.st_size < log_file.tell():
                log_file.close()
                log_file = open_log(path)
                current_inode = os.fstat(log_file.fileno()).st_ino

            if time.monotonic() - last_report >= refresh_seconds:
                os.system("cls" if os.name == "nt" else "clear")
                print(f"Live report: {path} | unique IPs: {len(counts)}\n")
                display_report(counts, "table", top, minimum_hits)
                last_report = time.monotonic()

            time.sleep(0.2)


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Count client IP hits in Apache/Nginx access logs."
    )

    parser.add_argument(
        "logfile",
        help="Path to access log, .gz archive, or '-' to read from stdin.",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=20,
        help="Show only the top N IP addresses. Use 0 to show all. Default: 20.",
    )
    parser.add_argument(
        "--min-hits",
        type=int,
        default=1,
        help="Only show IPs with at least this many hits. Default: 1.",
    )
    parser.add_argument(
        "--public-only",
        action="store_true",
        help="Ignore private, loopback, reserved, and local network addresses.",
    )
    parser.add_argument(
        "--format",
        choices=("table", "json", "csv"),
        default="table",
        help="Output format. Default: table.",
    )
    parser.add_argument(
        "--follow",
        action="store_true",
        help="Monitor the log continuously, like tail -f.",
    )
    parser.add_argument(
        "--refresh",
        type=float,
        default=5.0,
        help="Seconds between live report refreshes. Default: 5.",
    )

    return parser.parse_args()


def main() -> int:
    args = parse_arguments()

    if args.top < 0:
        print("--top must be zero or greater.", file=sys.stderr)
        return 2

    if args.min_hits < 1:
        print("--min-hits must be at least 1.", file=sys.stderr)
        return 2

    counts: Counter[str] = Counter()
    top = None if args.top == 0 else args.top

    try:
        if args.follow:
            follow_log(
                args.logfile,
                counts,
                args.public_only,
                args.refresh,
                top,
                args.min_hits,
            )
            return 0

        if args.logfile == "-":
            valid, skipped = read_ips(sys.stdin, counts, args.public_only)
        else:
            with open_log(args.logfile) as log_file:
                valid, skipped = read_ips(log_file, counts, args.public_only)

        display_report(counts, args.format, top, args.min_hits)

        if args.format == "table":
            print(
                f"\nProcessed hits: {valid} | "
                f"Unique IPs: {len(counts)} | "
                f"Skipped lines: {skipped}"
            )

        return 0

    except FileNotFoundError:
        print(f"Log file not found: {args.logfile}", file=sys.stderr)
        return 1
    except PermissionError:
        print(
            f"Permission denied reading: {args.logfile}\n"
            "Try running with sudo or grant your user read access.",
            file=sys.stderr,
        )
        return 1
    except KeyboardInterrupt:
        print("\nMonitoring stopped.")
        return 0
    except (OSError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
