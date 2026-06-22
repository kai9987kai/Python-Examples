#!/usr/bin/env python3
"""
portscanner.py — bounded-concurrency TCP connect scanner.

Use only on systems you own or are explicitly authorised to assess.
"""

from __future__ import annotations

import argparse
import csv
import errno
import json
import socket
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from typing import Sequence

DEFAULT_MAX_PORTS = 4096
MAX_WORKERS = 512


@dataclass(frozen=True)
class TargetAddress:
    family: int
    protocol: int
    sockaddr: tuple


@dataclass
class ScanResult:
    port: int
    status: str
    service: str
    banner: str | None = None
    detail: str | None = None


def parse_ports(value: str) -> list[int]:
    """Parse: 22,80,443,8000-8010"""
    ports: set[int] = set()

    for item in value.split(","):
        item = item.strip()
        if not item:
            continue

        try:
            if "-" in item:
                if item.count("-") != 1:
                    raise ValueError

                start_text, end_text = (part.strip() for part in item.split("-", 1))
                start, end = int(start_text), int(end_text)

                if not (1 <= start <= end <= 65535):
                    raise ValueError

                ports.update(range(start, end + 1))
            else:
                port = int(item)

                if not 1 <= port <= 65535:
                    raise ValueError

                ports.add(port)

        except ValueError as exc:
            raise argparse.ArgumentTypeError(
                f"Invalid port or range: {item!r}. Use ports from 1 to 65535."
            ) from exc

    if not ports:
        raise argparse.ArgumentTypeError("No valid ports specified.")

    return sorted(ports)


def positive_float(value: str) -> float:
    try:
        number = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Must be a number.") from exc

    if number <= 0:
        raise argparse.ArgumentTypeError("Must be greater than zero.")

    return number


def worker_count(value: str) -> int:
    try:
        workers = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Workers must be an integer.") from exc

    if not 1 <= workers <= MAX_WORKERS:
        raise argparse.ArgumentTypeError(
            f"Workers must be between 1 and {MAX_WORKERS}."
        )

    return workers


def resolve_target(host: str, family_mode: str) -> TargetAddress:
    family = {
        "auto": socket.AF_UNSPEC,
        "ipv4": socket.AF_INET,
        "ipv6": socket.AF_INET6,
    }[family_mode]

    try:
        candidates = socket.getaddrinfo(
            host,
            None,
            family,
            socket.SOCK_STREAM,
        )
    except socket.gaierror as exc:
        raise ValueError(f"Cannot resolve {host!r}: {exc}") from exc

    for address_family, _, protocol, _, sockaddr in candidates:
        if address_family in (socket.AF_INET, socket.AF_INET6):
            return TargetAddress(address_family, protocol, sockaddr)

    raise ValueError(f"No usable IPv4/IPv6 address found for {host!r}.")


def sockaddr_for_port(sockaddr: tuple, port: int) -> tuple:
    """Preserves IPv6 flow info and scope ID while replacing port."""
    return (sockaddr[0], port, *sockaddr[2:])


def service_for_port(port: int) -> str:
    try:
        return socket.getservbyport(port, "tcp")
    except OSError:
        return ""


def sanitise_banner(data: bytes) -> str | None:
    """Keep received banner data safe for terminal, JSON and CSV output."""
    if not data:
        return None

    text = data.decode("utf-8", errors="replace")
    text = "".join(char if char.isprintable() else " " for char in text)
    text = " ".join(text.split())

    return text[:512] or None


def scan_one(
    target: TargetAddress,
    port: int,
    timeout: float,
    read_banner: bool,
    banner_timeout: float,
    banner_bytes: int,
) -> ScanResult:
    service = service_for_port(port)

    try:
        with socket.socket(
            target.family,
            socket.SOCK_STREAM,
            target.protocol,
        ) as sock:
            sock.settimeout(timeout)
            sock.connect(sockaddr_for_port(target.sockaddr, port))

            banner = None

            if read_banner:
                # Passive read only: no bytes are sent to the target.
                sock.settimeout(min(timeout, banner_timeout))

                try:
                    banner = sanitise_banner(sock.recv(banner_bytes))
                except socket.timeout:
                    pass
                except OSError:
                    pass

            return ScanResult(
                port=port,
                status="open",
                service=service,
                banner=banner,
            )

    except ConnectionRefusedError:
        return ScanResult(port, "closed", service)

    except socket.timeout:
        return ScanResult(
            port,
            "timeout",
            service,
            detail="Connection timed out",
        )

    except OSError as exc:
        if exc.errno == errno.ECONNREFUSED:
            return ScanResult(port, "closed", service)

        if exc.errno in {
            errno.ETIMEDOUT,
            errno.EHOSTUNREACH,
            errno.ENETUNREACH,
        }:
            return ScanResult(
                port,
                "timeout",
                service,
                detail=exc.strerror or str(exc),
            )

        return ScanResult(
            port,
            "error",
            service,
            detail=exc.strerror or str(exc),
        )

    except Exception as exc:
        return ScanResult(
            port,
            "error",
            service,
            detail=str(exc),
        )


def run_scan(
    target: TargetAddress,
    ports: Sequence[int],
    timeout: float,
    workers: int,
    read_banner: bool,
    banner_timeout: float,
    banner_bytes: int,
) -> list[ScanResult]:
    executor = ThreadPoolExecutor(
        max_workers=min(workers, len(ports))
    )

    futures = [
        executor.submit(
            scan_one,
            target,
            port,
            timeout,
            read_banner,
            banner_timeout,
            banner_bytes,
        )
        for port in ports
    ]

    results: list[ScanResult] = []
    interrupted = False

    try:
        for future in as_completed(futures):
            results.append(future.result())

    except KeyboardInterrupt:
        interrupted = True
        print("\n[-] Cancelling queued scan tasks…", file=sys.stderr)

    finally:
        executor.shutdown(
            wait=True,
            cancel_futures=interrupted,
        )

    if interrupted:
        raise KeyboardInterrupt

    return sorted(results, key=lambda result: result.port)


def print_text(
    host: str,
    address: str,
    results: list[ScanResult],
    elapsed: float,
    verbose: bool,
) -> None:
    visible = results if verbose else [
        result for result in results if result.status == "open"
    ]

    print(f"Target: {host} ({address})")
    print(f"{'PORT':<9} {'STATE':<9} {'SERVICE':<16} DETAILS")
    print("-" * 78)

    for result in visible:
        details = result.banner or result.detail or ""

        print(
            f"{result.port}/tcp".ljust(9),
            f"{result.status:<9}",
            f"{(result.service or '-'): <16}",
            details,
        )

    counts: dict[str, int] = {}

    for result in results:
        counts[result.status] = counts.get(result.status, 0) + 1

    count_text = ", ".join(
        f"{name}: {count}"
        for name, count in sorted(counts.items())
    )

    print("-" * 78)
    print(f"Scanned {len(results)} ports in {elapsed:.2f}s — {count_text}")


def print_json(
    host: str,
    address: str,
    results: list[ScanResult],
    elapsed: float,
) -> None:
    payload = {
        "target": {
            "host": host,
            "address": address,
        },
        "elapsed_seconds": round(elapsed, 4),
        "summary": {
            status: sum(result.status == status for result in results)
            for status in sorted({result.status for result in results})
        },
        "results": [asdict(result) for result in results],
    }

    print(json.dumps(payload, indent=2))


def print_csv(results: list[ScanResult]) -> None:
    writer = csv.DictWriter(
        sys.stdout,
        fieldnames=["port", "status", "service", "banner", "detail"],
    )

    writer.writeheader()
    writer.writerows(asdict(result) for result in results)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Bounded-concurrency TCP scanner for authorised assessments."
    )

    parser.add_argument(
        "host",
        help="Single hostname or IP address to scan.",
    )

    parser.add_argument(
        "ports",
        type=parse_ports,
        help="Ports/ranges, e.g. 22,80,443,8000-8010.",
    )

    parser.add_argument(
        "-w",
        "--workers",
        type=worker_count,
        default=100,
        help="Maximum concurrent connections, 1-512. Default: 100.",
    )

    parser.add_argument(
        "-t",
        "--timeout",
        type=positive_float,
        default=1.5,
        help="Per-port connection timeout in seconds. Default: 1.5.",
    )

    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show closed, timeout and error states.",
    )

    parser.add_argument(
        "--banner",
        action="store_true",
        help="Passively receive banner bytes after connection; sends no data.",
    )

    parser.add_argument(
        "--banner-timeout",
        type=positive_float,
        default=0.35,
        help="Maximum passive banner wait. Default: 0.35 seconds.",
    )

    parser.add_argument(
        "--family",
        choices=("auto", "ipv4", "ipv6"),
        default="auto",
        help="Address family to use. Default: auto.",
    )

    parser.add_argument(
        "--format",
        choices=("text", "json", "csv"),
        default="text",
        help="Output format. Default: text.",
    )

    parser.add_argument(
        "--allow-large-scan",
        action="store_true",
        help=f"Permit more than {DEFAULT_MAX_PORTS} requested ports.",
    )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if len(args.ports) > DEFAULT_MAX_PORTS and not args.allow_large_scan:
        parser.error(
            f"{len(args.ports)} ports requested. "
            "Use --allow-large-scan only for an authorised broad scan."
        )

    try:
        target = resolve_target(args.host, args.family)
    except ValueError as exc:
        parser.error(str(exc))

    address = target.sockaddr[0]
    started = time.perf_counter()

    try:
        results = run_scan(
            target=target,
            ports=args.ports,
            timeout=args.timeout,
            workers=args.workers,
            read_banner=args.banner,
            banner_timeout=args.banner_timeout,
            banner_bytes=512,
        )
    except KeyboardInterrupt:
        return 130

    elapsed = time.perf_counter() - started

    if args.format == "json":
        print_json(args.host, address, results, elapsed)

    elif args.format == "csv":
        print_csv(results)

    else:
        print_text(
            args.host,
            address,
            results,
            elapsed,
            args.verbose,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
