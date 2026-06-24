#!/usr/bin/env python3
"""
Script Name : nmap_scan.py
Description : Scan selected TCP ports on one authorised target host.

Requirements:
    pip install python-nmap
    Nmap must also be installed and available on your system PATH.

Example:
    python nmap_scan.py -H 127.0.0.1 -p 22,80,443
    python nmap_scan.py -H example.local -p 1-1024
"""

from __future__ import annotations

import argparse
import re
import sys

import nmap


def validate_ports(port_spec: str) -> str:
    """Validate comma-separated TCP ports and port ranges."""
    pattern = re.compile(r"^\d{1,5}(-\d{1,5})?$")

    for item in port_spec.split(","):
        item = item.strip()

        if not pattern.fullmatch(item):
            raise argparse.ArgumentTypeError(
                f"Invalid port specification: '{item}'. "
                "Use formats such as 22, 80, 443, or 1-1024."
            )

        if "-" in item:
            start, end = map(int, item.split("-"))

            if not (1 <= start <= 65535 and 1 <= end <= 65535):
                raise argparse.ArgumentTypeError(
                    f"Ports must be between 1 and 65535: '{item}'."
                )

            if start > end:
                raise argparse.ArgumentTypeError(
                    f"Port-range start must not exceed end: '{item}'."
                )
        else:
            port = int(item)

            if not 1 <= port <= 65535:
                raise argparse.ArgumentTypeError(
                    f"Port must be between 1 and 65535: '{item}'."
                )

    return port_spec


def scan_host(
    scanner: nmap.PortScanner,
    host: str,
    ports: str,
    skip_host_discovery: bool = False,
) -> None:
    """Run a TCP connect scan and print clear results."""
    arguments = "-sT"

    if skip_host_discovery:
        arguments += " -Pn"

    try:
        scanner.scan(hosts=host, ports=ports, arguments=arguments)
    except nmap.PortScannerError as error:
        print(f"[!] Nmap error: {error}")
        return
    except Exception as error:
        print(f"[!] Unexpected scan error: {error}")
        return

    if not scanner.all_hosts():
        print(f"[!] No reachable hosts found for: {host}")
        return

    for scanned_host in scanner.all_hosts():
        host_state = scanner[scanned_host].state()

        print(f"\n[*] Host: {scanned_host}")
        print(f"[*] Host status: {host_state}")

        if "tcp" not in scanner[scanned_host]:
            print("[!] No TCP scan results returned.")
            continue

        print("\nPORT       STATE       SERVICE")

        for port in sorted(scanner[scanned_host]["tcp"]):
            details = scanner[scanned_host]["tcp"][port]
            state = details.get("state", "unknown")
            service = details.get("name", "unknown")

            print(f"{port}/tcp".ljust(11) + f"{state}".ljust(12) + service)


def build_parser() -> argparse.ArgumentParser:
    """Create the command-line interface."""
    parser = argparse.ArgumentParser(
        description="Perform a TCP port scan on one authorised host.",
        epilog="Only scan hosts and networks that you own or have permission to test.",
    )

    parser.add_argument(
        "-H",
        "--host",
        required=True,
        help="Target hostname or IP address, for example: 127.0.0.1",
    )

    parser.add_argument(
        "-p",
        "--ports",
        required=True,
        type=validate_ports,
        help="Ports to scan, for example: 22,80,443 or 1-1024",
    )

    parser.add_argument(
        "--skip-host-discovery",
        action="store_true",
        help="Scan even if the host does not respond to discovery probes (-Pn).",
    )

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        scanner = nmap.PortScanner()
    except nmap.PortScannerError:
        print("[!] Nmap was not found. Install Nmap and ensure it is on your PATH.")
        return 1

    print(f"[*] Scanning authorised target: {args.host}")
    print(f"[*] TCP ports: {args.ports}")

    scan_host(
        scanner=scanner,
        host=args.host,
        ports=args.ports,
        skip_host_discovery=args.skip_host_discovery,
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
