#!/usr/bin/env python3
"""
nslookup_check.py

Checks DNS entries for servers listed in a text file using nslookup.

Example:
    python nslookup_check.py
    python nslookup_check.py --file server_list.txt --workers 10 --timeout 8
"""

from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter


@dataclass
class LookupResult:
    server: str
    status: str
    duration_seconds: float
    output: str


def load_servers(filename: Path) -> list[str]:
    """Load server names/IPs, ignoring empty lines and comments."""
    if not filename.is_file():
        raise FileNotFoundError(f"Server list file not found: {filename}")

    servers = []

    for line in filename.read_text(encoding="utf-8").splitlines():
        server = line.strip()

        if not server or server.startswith("#"):
            continue

        servers.append(server)

    # Preserve order while removing duplicates.
    return list(dict.fromkeys(servers))


def check_dns(server: str, timeout: int) -> LookupResult:
    """Run nslookup safely for one server."""
    started = perf_counter()

    try:
        completed = subprocess.run(
            ["nslookup", server],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )

        output = (completed.stdout + completed.stderr).strip()
        duration = perf_counter() - started

        # nslookup can sometimes return code 0 despite DNS failure,
        # so inspect its output too.
        failure_terms = (
            "non-existent domain",
            "nxdomain",
            "can't find",
            "server failed",
            "timed out",
            "no response",
            "not found",
        )

        output_lower = output.lower()

        if completed.returncode != 0 or any(term in output_lower for term in failure_terms):
            status = "FAILED"
        else:
            status = "OK"

        return LookupResult(server, status, duration, output)

    except subprocess.TimeoutExpired:
        return LookupResult(
            server=server,
            status="TIMEOUT",
            duration_seconds=perf_counter() - started,
            output=f"Lookup exceeded {timeout} seconds.",
        )

    except FileNotFoundError:
        return LookupResult(
            server=server,
            status="ERROR",
            duration_seconds=perf_counter() - started,
            output="nslookup was not found. Ensure DNS tools are installed and available in PATH.",
        )

    except OSError as error:
        return LookupResult(
            server=server,
            status="ERROR",
            duration_seconds=perf_counter() - started,
            output=str(error),
        )


def save_report(results: list[LookupResult], report_file: Path) -> None:
    """Save results as a CSV report."""
    with report_file.open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(["Server", "Status", "Duration (seconds)", "Output"])

        for result in results:
            writer.writerow([
                result.server,
                result.status,
                f"{result.duration_seconds:.2f}",
                result.output,
            ])


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check DNS entries listed in a file using nslookup."
    )
    parser.add_argument(
        "--file",
        default="server_list.txt",
        help="Text file containing server names or IP addresses.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=5,
        help="Maximum seconds allowed per nslookup request.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=5,
        help="Number of lookups to run at once.",
    )
    parser.add_argument(
        "--report",
        default="dns_lookup_report.csv",
        help="CSV output filename.",
    )

    args = parser.parse_args()

    if args.timeout < 1:
        parser.error("--timeout must be at least 1 second.")

    if args.workers < 1:
        parser.error("--workers must be at least 1.")

    try:
        servers = load_servers(Path(args.file))
    except (FileNotFoundError, OSError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    if not servers:
        print("No valid servers found in the input file.")
        return 1

    print(f"Checking {len(servers)} DNS entries...\n")

    results: list[LookupResult] = []

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(check_dns, server, args.timeout): server
            for server in servers
        }

        for future in as_completed(futures):
            result = future.result()
            results.append(result)

            print(
                f"[{result.status:7}] "
                f"{result.server:<35} "
                f"{result.duration_seconds:.2f}s"
            )

    # Restore original file ordering in the report.
    server_order = {server: index for index, server in enumerate(servers)}
    results.sort(key=lambda result: server_order[result.server])

    report_path = Path(args.report)
    save_report(results, report_path)

    successful = sum(result.status == "OK" for result in results)
    failed = len(results) - successful

    print("\nSummary")
    print("-" * 40)
    print(f"Successful: {successful}")
    print(f"Failed:     {failed}")
    print(f"Report:     {report_path.resolve()}")

    return 0 if failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
