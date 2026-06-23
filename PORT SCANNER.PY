#!/usr/bin/env python3
"""
Authorised TCP port scanner.

Use only on systems and networks you own or have explicit permission to test.
Examples:
    python portscanner.py 127.0.0.1 --ports 1-1024 --authorized
    python portscanner.py localhost --ports 22,80,443 --authorized --json
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from time import perf_counter

MAX_PORTS = 2048
MAX_WORKERS = 128


def parse_ports(value: str) -> list[int]:
    """Parse ports such as: 22,80,443,8000-8100."""
    ports: set[int] = set()

    try:
        for part in value.split(","):
            part = part.strip()

            if not part:
                continue

            if "-" in part:
                start_text, end_text = part.split("-", 1)
                start, end = int(start_text), int(end_text)

                if start > end:
                    raise ValueError(f"Invalid range: {part}")

                ports.update(range(start, end + 1))
            else:
                ports.add(int(part))
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "Ports must look like 22,80,443,8000-8100."
        ) from error

    if not ports:
        raise argparse.ArgumentTypeError("Provide at least one port.")

    if any(port < 1 or port > 65535 for port in ports):
        raise argparse.ArgumentTypeError("Port numbers must be from 1 to 65535.")

    if len(ports) > MAX_PORTS:
        raise argparse.ArgumentTypeError(
            f"Too many ports requested. Limit: {MAX_PORTS}."
        )

    return sorted(ports)


def resolve_target(host: str) -> list[tuple[int, int, tuple]]:
    """Resolve a hostname once, returning unique IPv4/IPv6 targets."""
    try:
        results = socket.getaddrinfo(
            host,
            0,
            family=socket.AF_UNSPEC,
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror as error:
        raise RuntimeError(f"Could not resolve '{host}': {error}") from error

    targets = []
    seen = set()

    for family, _, protocol, _, sockaddr in results:
        if family not in (socket.AF_INET, socket.AF_INET6):
            continue

        key = (family, sockaddr)
        if key not in seen:
            seen.add(key)
            targets.append((family, protocol, sockaddr))

    if not targets:
        raise RuntimeError(f"No usable IPv4 or IPv6 addresses found for '{host}'.")

    return targets


def make_socket_address(family: int, sockaddr: tuple, port: int) -> tuple:
    """Replace the port in an IPv4 or IPv6 socket address."""
    if family == socket.AF_INET:
        return sockaddr[0], port

    # IPv6: address, port, flowinfo, scopeid
    return sockaddr[0], port, sockaddr[2], sockaddr[3]


def display_address(family: int, sockaddr: tuple) -> str:
    """Format addresses neatly, including bracketed IPv6."""
    address = sockaddr[0]
    return f"[{address}]" if family == socket.AF_INET6 else address


def check_port(
    family: int,
    protocol: int,
    sockaddr: tuple,
    port: int,
    timeout: float,
) -> dict | None:
    """Return a record only when a TCP connection succeeds."""
    address = make_socket_address(family, sockaddr, port)

    try:
        with socket.socket(family, socket.SOCK_STREAM, protocol) as sock:
            sock.settimeout(timeout)
            result = sock.connect_ex(address)

        if result == 0:
            return {
                "address": display_address(family, sockaddr),
                "port": port,
                "state": "open",
            }

    except OSError:
        # A blocked, unavailable, or malformed route is simply not reported
        # as an open port.
        pass

    return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Small authorised TCP connect port scanner."
    )

    parser.add_argument(
        "host",
        help="Hostname or IP address to scan.",
    )
    parser.add_argument(
        "--ports",
        default="1-1024",
        type=parse_ports,
        help="Ports/ranges, e.g. 22,80,443,8000-8100. Default: 1-1024.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=0.5,
        help="Connection timeout in seconds. Default: 0.5.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=30,
        help="Concurrent checks, 1-%d. Default: 30." % MAX_WORKERS,
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )
    parser.add_argument(
        "--authorized",
        action="store_true",
        help="Confirm you have permission to scan this target.",
    )

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if not args.authorized:
        parser.error("You must provide --authorized before scanning.")

    if not 0.05 <= args.timeout <= 10:
        parser.error("--timeout must be between 0.05 and 10 seconds.")

    if not 1 <= args.workers <= MAX_WORKERS:
        parser.error(f"--workers must be between 1 and {MAX_WORKERS}.")

    try:
        targets = resolve_target(args.host)
    except RuntimeError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2

    jobs = [
        (family, protocol, sockaddr, port)
        for family, protocol, sockaddr in targets
        for port in args.ports
    ]

    worker_count = min(args.workers, len(jobs))
    started = perf_counter()
    open_ports = []

    try:
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = [
                executor.submit(
                    check_port,
                    family,
                    protocol,
                    sockaddr,
                    port,
                    args.timeout,
                )
                for family, protocol, sockaddr, port in jobs
            ]

            for future in as_completed(futures):
                result = future.result()
                if result is not None:
                    open_ports.append(result)

    except KeyboardInterrupt:
        print("\nScan cancelled by user.", file=sys.stderr)
        return 130

    elapsed = perf_counter() - started
    open_ports.sort(key=lambda item: (item["address"], item["port"]))

    addresses = [display_address(family, sockaddr) for family, _, sockaddr in targets]

    report = {
        "target": args.host,
        "resolved_addresses": addresses,
        "ports_requested": len(args.ports),
        "open_ports": open_ports,
        "elapsed_seconds": round(elapsed, 3),
    }

    if args.json:
        print(json.dumps(report, indent=2))
        return 0

    print("=" * 60)
    print(f"Target: {args.host}")
    print(f"Resolved: {', '.join(addresses)}")
    print(f"Ports checked: {len(args.ports)}")
    print("=" * 60)

    if open_ports:
        for item in open_ports:
            print(f"OPEN  {item['address']}:{item['port']}/tcp")
    else:
        print("No open TCP ports found in the requested range.")

    print(f"\nCompleted in {elapsed:.2f} seconds.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
