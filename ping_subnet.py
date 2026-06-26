#!/usr/bin/env python3
"""
ping_subnet.py

Ping every usable address in a permitted IPv4 subnet.

Examples:
    python ping_subnet.py 192.168.1
    python ping_subnet.py 192.168.1.0/24
    python ping_subnet.py 10.0.0.0/24 --workers 32 --show-dead
"""

import argparse
import ipaddress
import platform
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import List, Optional


SAFE_NETWORKS = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
)


@dataclass
class PingResult:
    host: str
    alive: bool
    elapsed_ms: int
    error: Optional[str] = None


def parse_network(value: str) -> ipaddress.IPv4Network:
    """Accept 192.168.1 as shorthand for 192.168.1.0/24."""
    value = value.strip()

    if "/" not in value and value.count(".") == 2:
        value += ".0/24"

    try:
        network = ipaddress.ip_network(value, strict=False)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Invalid subnet: {exc}") from exc

    if network.version != 4:
        raise argparse.ArgumentTypeError("Only IPv4 networks are supported.")

    if not any(network.subnet_of(safe_network) for safe_network in SAFE_NETWORKS):
        raise argparse.ArgumentTypeError(
            "Only private, loopback, or link-local IPv4 ranges are allowed."
        )

    return network


def build_ping_command(host: str, count: int) -> List[str]:
    """Build a platform-safe ping command without shell=True."""
    if platform.system().lower().startswith("win"):
        return ["ping", "-n", str(count), host]

    return ["ping", "-c", str(count), host]


def ping_host(host: str, count: int, timeout: float) -> PingResult:
    """Ping one host and return a simple structured result."""
    command = build_ping_command(host, count)
    started = perf_counter()

    try:
        completed = subprocess.run(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
            check=False,
        )

        elapsed_ms = int((perf_counter() - started) * 1000)
        return PingResult(
            host=host,
            alive=(completed.returncode == 0),
            elapsed_ms=elapsed_ms,
        )

    except subprocess.TimeoutExpired:
        elapsed_ms = int((perf_counter() - started) * 1000)
        return PingResult(
            host=host,
            alive=False,
            elapsed_ms=elapsed_ms,
            error="Timed out",
        )

    except FileNotFoundError:
        return PingResult(
            host=host,
            alive=False,
            elapsed_ms=0,
            error="ping command was not found",
        )


def write_log(log_file: Path, network: ipaddress.IPv4Network, results: List[PingResult]) -> None:
    """Write clean, machine-readable scan results."""
    alive_count = sum(result.alive for result in results)
    dead_count = len(results) - alive_count

    log_file.parent.mkdir(parents=True, exist_ok=True)

    with log_file.open("w", encoding="utf-8") as file:
        file.write(f"Subnet: {network}\n")
        file.write(f"Scan completed: {datetime.now().isoformat(timespec='seconds')}\n")
        file.write(f"Alive: {alive_count}\n")
        file.write(f"No reply/error: {dead_count}\n")
        file.write("-" * 60 + "\n")

        for result in results:
            status = "UP" if result.alive else "NO_REPLY"
            details = result.error or f"{result.elapsed_ms} ms"
            file.write(f"{result.host:<15} {status:<10} {details}\n")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Ping hosts on a private IPv4 subnet.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "subnet",
        type=parse_network,
        help="Subnet such as 192.168.1 or 192.168.1.0/24",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=16,
        help="Number of simultaneous ping checks",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=1,
        help="Number of ping packets per host",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=2.0,
        help="Maximum seconds allowed per host",
    )
    parser.add_argument(
        "--max-hosts",
        type=int,
        default=4096,
        help="Safety limit for number of addresses scanned",
    )
    parser.add_argument(
        "--show-dead",
        action="store_true",
        help="Print hosts that did not respond",
    )
    parser.add_argument(
        "--log",
        type=Path,
        help="Optional output log filename",
    )

    args = parser.parse_args()

    if args.workers < 1:
        parser.error("--workers must be at least 1")

    if args.count < 1:
        parser.error("--count must be at least 1")

    if args.timeout <= 0:
        parser.error("--timeout must be greater than 0")

    if shutil.which("ping") is None:
        print("Error: the system ping command was not found.", file=sys.stderr)
        return 2

    hosts = [str(host) for host in args.subnet.hosts()]

    if len(hosts) > args.max_hosts:
        parser.error(
            f"{args.subnet} contains {len(hosts)} usable hosts. "
            f"Increase --max-hosts only for a network you administer."
        )

    print(f"Scanning {args.subnet} ({len(hosts)} usable addresses)...")

    results: List[PingResult] = []

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(ping_host, host, args.count, args.timeout): host
            for host in hosts
        }

        for future in as_completed(futures):
            result = future.result()
            results.append(result)

            if result.alive:
                print(f"UP       {result.host:<15} {result.elapsed_ms} ms")
            elif args.show_dead:
                reason = result.error or "No ICMP reply"
                print(f"NO_REPLY {result.host:<15} {reason}")

    results.sort(key=lambda result: ipaddress.ip_address(result.host))

    alive_count = sum(result.alive for result in results)
    print(f"\nFinished: {alive_count}/{len(results)} hosts responded.")

    default_name = (
        f"ping_{str(args.subnet.network_address).replace('.', '_')}_"
        f"{args.subnet.prefixlen}.log"
    )
    log_file = args.log or Path(default_name)

    write_log(log_file, args.subnet, results)
    print(f"Log written to: {log_file}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
