#!/usr/bin/env python3
"""
powerup_checks_v2.py

Cross-platform server power-up/reachability checker.

Original concept: Craig Richards, 25 June 2013
Modernised version: 2.0.0

Exit codes:
    0   All servers responded, successful dry run, or --always-zero
    1   One or more servers were down or errored
    2   Configuration/database/runtime error
    130 Interrupted with Ctrl+C
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import platform
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, Sequence

PROGRAM = "powerup-checks"
VERSION = "2.0.0"
DEFAULT_DB_RELATIVE = Path("Databases") / "jarvis.db"
DEFAULT_LIST_FILE = "startup_list.txt"
HOST_RE = re.compile(r"^[A-Za-z0-9_.:%\-\[\]]+$")
FILE_RE = re.compile(r"[^A-Za-z0-9_.-]+")

UP = "UP"
DOWN = "DOWN"
ERROR = "ERROR"
SKIPPED = "SKIPPED"


@dataclass(frozen=True)
class PingResult:
    hostname: str
    status: str
    resolved_ip: Optional[str]
    elapsed_ms: Optional[float]
    return_code: Optional[int]
    checked_at: str
    error: Optional[str]


@dataclass(frozen=True)
class Summary:
    site: str
    started_at: str
    finished_at: str
    duration_seconds: float
    total: int
    up: int
    down: int
    errors: int
    skipped: int


class AppError(RuntimeError):
    pass


class Console:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    GREEN = "\033[32m"
    RED = "\033[31m"
    YELLOW = "\033[33m"
    CYAN = "\033[36m"

    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled and sys.stdout.isatty()

    def style(self, text: str, code: str) -> str:
        return f"{code}{text}{self.RESET}" if self.enabled else text

    def heading(self, text: str) -> None:
        print(self.style(text, self.BOLD + self.CYAN))

    def ok(self, text: str) -> None:
        print(self.style(text, self.GREEN))

    def warn(self, text: str) -> None:
        print(self.style(text, self.YELLOW), file=sys.stderr)

    def fail(self, text: str) -> None:
        print(self.style(text, self.RED), file=sys.stderr)


def first_env(*names: str) -> Optional[str]:
    for name in names:
        value = os.getenv(name)
        if value and value.strip():
            return value.strip()
    return None


def default_database() -> Optional[Path]:
    root = first_env("DROPBOX", "dropbox")
    return Path(root).expanduser() / DEFAULT_DB_RELATIVE if root else None


def default_server_list() -> Path:
    root = first_env("MY_CONFIG", "my_config")
    return (Path(root).expanduser() if root else Path.cwd()) / DEFAULT_LIST_FILE


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than 0")
    return parsed


def non_negative_float(value: str) -> float:
    parsed = float(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be 0 or greater")
    return parsed


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog=PROGRAM,
        description=(
            "Load site servers from SQLite, ping them concurrently, and create "
            "text, JSON, or CSV reports."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python powerup_checks_v2.py site1\n"
            "  python powerup_checks_v2.py -site2 --format all\n"
            "  python powerup_checks_v2.py london --database /data/jarvis.db\n"
            "  python powerup_checks_v2.py site1 --repeat 5 --interval 60"
        ),
    )
    p.add_argument("site", nargs="?", help="Value in tp_servers.location")
    p.add_argument("-site1", dest="legacy_site", action="store_const", const="site1")
    p.add_argument("-site2", dest="legacy_site", action="store_const", const="site2")
    p.add_argument(
        "--database",
        type=Path,
        default=default_database(),
        help="SQLite database; defaults to $DROPBOX/Databases/jarvis.db",
    )
    p.add_argument("--output-dir", type=Path, default=Path.cwd())
    p.add_argument("--server-list", type=Path, default=default_server_list())
    p.add_argument("--no-export-list", action="store_true")
    p.add_argument("--format", choices=("text", "json", "csv", "all"), default="text")
    p.add_argument("--count", type=positive_int, default=3)
    p.add_argument("--timeout", type=positive_float, default=2.0)
    p.add_argument(
        "--workers",
        type=positive_int,
        default=min(32, max(4, (os.cpu_count() or 1) * 4)),
    )
    p.add_argument("--repeat", type=positive_int, default=1)
    p.add_argument("--interval", type=non_negative_float, default=0.0)
    p.add_argument("--no-resolve", action="store_true")
    p.add_argument("--include-ping-output", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--always-zero", action="store_true")
    p.add_argument("--no-colour", "--no-color", action="store_true")
    p.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    return p


def resolve_site(args: argparse.Namespace, p: argparse.ArgumentParser) -> str:
    if args.site and args.legacy_site and args.site != args.legacy_site:
        p.error(f"conflicting site values: {args.site!r} and {args.legacy_site!r}")
    site = (args.site or args.legacy_site or "").strip()
    if not site:
        p.error("a site is required, for example: site1 or -site1")
    return site


def validate_paths(database: Optional[Path], output_dir: Path) -> tuple[Path, Path]:
    if database is None:
        raise AppError("pass --database or define DROPBOX/dropbox")
    database = database.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    if not database.is_file():
        raise AppError(f"database does not exist or is not a file: {database}")
    output_dir.mkdir(parents=True, exist_ok=True)
    if not output_dir.is_dir():
        raise AppError(f"output path is not a directory: {output_dir}")
    return database, output_dir


def validate_host(raw: object) -> str:
    host = str(raw).strip()
    if not host:
        raise AppError("database contains an empty hostname")
    if host.startswith("-"):
        raise AppError(f"unsafe hostname begins with '-': {host!r}")
    if len(host) > 253:
        raise AppError(f"hostname is too long: {host!r}")
    if not HOST_RE.fullmatch(host):
        raise AppError(f"hostname contains unsupported characters: {host!r}")
    return host


def connect_read_only(database: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True, timeout=10.0)
    conn.row_factory = sqlite3.Row
    return conn


def load_servers(database: Path, site: str) -> list[str]:
    try:
        with connect_read_only(database) as conn:
            rows = conn.execute(
                """
                SELECT hostname
                FROM tp_servers
                WHERE location = ? AND hostname IS NOT NULL
                ORDER BY hostname COLLATE NOCASE
                """,
                (site,),
            ).fetchall()
            if not rows:
                sites = conn.execute(
                    """
                    SELECT DISTINCT location
                    FROM tp_servers
                    WHERE location IS NOT NULL
                    ORDER BY location COLLATE NOCASE
                    LIMIT 20
                    """
                ).fetchall()
                available = ", ".join(str(row["location"]) for row in sites)
                suffix = f" Available sites: {available}" if available else ""
                raise AppError(f"no servers found for site {site!r}.{suffix}")
    except sqlite3.Error as exc:
        raise AppError(f"SQLite query failed: {exc}") from exc

    unique: dict[str, str] = {}
    for row in rows:
        host = validate_host(row["hostname"])
        unique.setdefault(host.casefold(), host)
    return sorted(unique.values(), key=str.casefold)


def atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temp.write_text(content, encoding="utf-8", newline="\n")
        temp.replace(path)
    finally:
        if temp.exists():
            temp.unlink()


def export_list(path: Path, servers: Sequence[str]) -> Path:
    path = path.expanduser().resolve()
    atomic_text(path, "".join(f"{host}\n" for host in servers))
    return path


def resolve_ip(host: str) -> Optional[str]:
    try:
        records = socket.getaddrinfo(host, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror:
        return None
    addresses: list[tuple[int, str]] = []
    for family, _type, _proto, _canon, sockaddr in records:
        addresses.append((0 if family == socket.AF_INET else 1, str(sockaddr[0])))
    return sorted(addresses)[0][1] if addresses else None


def build_ping_command(host: str, count: int, timeout: float) -> list[str]:
    system = platform.system().lower()
    if system == "windows":
        return ["ping", "-n", str(count), "-w", str(math.ceil(timeout * 1000)), host]
    if system == "linux":
        return ["ping", "-c", str(count), "-W", str(max(1, math.ceil(timeout))), host]
    if system == "darwin":
        return ["ping", "-c", str(count), "-W", str(math.ceil(timeout * 1000)), host]
    if os.name == "posix":
        return ["ping", "-c", str(count), host]
    raise AppError(f"unsupported operating system: {platform.system() or os.name}")


def compact(text: str, limit: int = 280) -> Optional[str]:
    value = " ".join(text.replace("\x00", "").split())
    if not value:
        return None
    return value if len(value) <= limit else value[: limit - 1] + "…"


def ping_one(
    host: str,
    count: int,
    timeout: float,
    resolve_dns: bool,
    include_output: bool,
) -> PingResult:
    checked = datetime.now().astimezone().isoformat(timespec="seconds")
    ip = resolve_ip(host) if resolve_dns else None
    try:
        command = build_ping_command(host, count, timeout)
    except AppError as exc:
        return PingResult(host, ERROR, ip, None, None, checked, str(exc))

    overall_timeout = max(3.0, count * timeout + 3.0)
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=overall_timeout,
            check=False,
            shell=False,
        )
        elapsed = round((time.perf_counter() - started) * 1000, 2)
        status = UP if completed.returncode == 0 else DOWN
        error = compact(completed.stdout) if include_output and status == DOWN else None
        return PingResult(host, status, ip, elapsed, completed.returncode, checked, error)
    except subprocess.TimeoutExpired as exc:
        elapsed = round((time.perf_counter() - started) * 1000, 2)
        output = exc.stdout or ""
        if isinstance(output, bytes):
            output = output.decode("utf-8", errors="replace")
        detail = compact(output) if include_output else None
        message = f"ping timed out after {overall_timeout:.1f}s"
        return PingResult(host, DOWN, ip, elapsed, None, checked, f"{message}: {detail}" if detail else message)
    except FileNotFoundError:
        return PingResult(host, ERROR, ip, None, None, checked, "ping executable not found")
    except OSError as exc:
        return PingResult(host, ERROR, ip, None, None, checked, f"ping failed: {exc}")


def dry_result(host: str, resolve_dns: bool) -> PingResult:
    return PingResult(
        host,
        SKIPPED,
        resolve_ip(host) if resolve_dns else None,
        None,
        None,
        datetime.now().astimezone().isoformat(timespec="seconds"),
        "dry run; ping was not executed",
    )


def console_line(result: PingResult, console: Console) -> str:
    raw = result.status.ljust(7)
    colour = Console.GREEN if result.status == UP else Console.YELLOW if result.status == SKIPPED else Console.RED
    status = console.style(raw, colour)
    elapsed = f"{result.elapsed_ms:.2f} ms" if result.elapsed_ms is not None else "-"
    line = f"[{status}] {result.hostname:<32} ip={(result.resolved_ip or '-'):<39} elapsed={elapsed}"
    return f"{line}  {result.error}" if result.error else line


def check_servers(args: argparse.Namespace, servers: Sequence[str], console: Console) -> list[PingResult]:
    if args.dry_run:
        results = [dry_result(host, not args.no_resolve) for host in servers]
        for result in results:
            print(console_line(result, console))
        return results

    results: list[PingResult] = []
    with ThreadPoolExecutor(max_workers=min(args.workers, len(servers)), thread_name_prefix="ping") as pool:
        futures = {
            pool.submit(
                ping_one,
                host,
                args.count,
                args.timeout,
                not args.no_resolve,
                args.include_ping_output,
            ): host
            for host in servers
        }
        for future in as_completed(futures):
            host = futures[future]
            try:
                result = future.result()
            except Exception as exc:
                result = PingResult(
                    host,
                    ERROR,
                    None,
                    None,
                    None,
                    datetime.now().astimezone().isoformat(timespec="seconds"),
                    f"unexpected worker failure: {exc}",
                )
            results.append(result)
            print(console_line(result, console))
    return sorted(results, key=lambda item: item.hostname.casefold())


def summarise(site: str, started: datetime, finished: datetime, results: Sequence[PingResult]) -> Summary:
    return Summary(
        site=site,
        started_at=started.isoformat(timespec="seconds"),
        finished_at=finished.isoformat(timespec="seconds"),
        duration_seconds=round((finished - started).total_seconds(), 3),
        total=len(results),
        up=sum(item.status == UP for item in results),
        down=sum(item.status == DOWN for item in results),
        errors=sum(item.status == ERROR for item in results),
        skipped=sum(item.status == SKIPPED for item in results),
    )


def text_report(summary: Summary, database: Path, results: Sequence[PingResult]) -> str:
    lines = [
        f"{PROGRAM} {VERSION}",
        f"Site: {summary.site}",
        f"Database: {database}",
        f"Started: {summary.started_at}",
        f"Finished: {summary.finished_at}",
        f"Duration: {summary.duration_seconds:.3f} seconds",
        f"Summary: total={summary.total} up={summary.up} down={summary.down} errors={summary.errors} skipped={summary.skipped}",
        "",
        f"{'STATUS':<8} {'HOSTNAME':<32} {'RESOLVED IP':<39} {'ELAPSED MS':>12}  ERROR",
        "-" * 120,
    ]
    for item in results:
        elapsed = f"{item.elapsed_ms:.2f}" if item.elapsed_ms is not None else "-"
        lines.append(
            f"{item.status:<8} {item.hostname:<32} {(item.resolved_ip or '-'):<39} "
            f"{elapsed:>12}  {item.error or ''}"
        )
    return "\n".join(lines) + "\n"


def safe_name(value: str) -> str:
    return FILE_RE.sub("_", value).strip("._") or "site"


def write_csv(path: Path, results: Sequence[PingResult]) -> None:
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fields = list(PingResult.__dataclass_fields__)
    try:
        with temp.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(asdict(item) for item in results)
        temp.replace(path)
    finally:
        if temp.exists():
            temp.unlink()


def write_reports(
    output_dir: Path,
    report_format: str,
    database: Path,
    summary: Summary,
    results: Sequence[PingResult],
) -> list[Path]:
    stamp = datetime.now().astimezone().strftime("%Y-%m-%d-%H-%M-%S")
    stem = f"server_startup_{safe_name(summary.site)}_{stamp}"
    formats = ("text", "json", "csv") if report_format == "all" else (report_format,)
    paths: list[Path] = []
    for selected in formats:
        if selected == "text":
            path = output_dir / f"{stem}.log"
            atomic_text(path, text_report(summary, database, results))
        elif selected == "json":
            path = output_dir / f"{stem}.json"
            payload = {
                "program": PROGRAM,
                "version": VERSION,
                "database": str(database),
                "summary": asdict(summary),
                "results": [asdict(item) for item in results],
            }
            atomic_text(path, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
        elif selected == "csv":
            path = output_dir / f"{stem}.csv"
            write_csv(path, results)
        else:
            raise AppError(f"unsupported report format: {selected}")
        paths.append(path)
    return paths


def run_once(
    args: argparse.Namespace,
    site: str,
    database: Path,
    output_dir: Path,
    servers: Sequence[str],
    console: Console,
    number: int,
) -> Summary:
    console.heading(f"\nRun {number}/{args.repeat}: checking {len(servers)} server(s) for {site!r}")
    started = datetime.now().astimezone()
    results = check_servers(args, servers, console)
    finished = datetime.now().astimezone()
    summary = summarise(site, started, finished, results)
    reports = write_reports(output_dir, args.format, database, summary, results)
    message = (
        f"Summary: {summary.up}/{summary.total} up, {summary.down} down, "
        f"{summary.errors} errors, {summary.skipped} skipped in "
        f"{summary.duration_seconds:.3f}s"
    )
    console.warn(message) if summary.down or summary.errors else console.ok(message)
    for report in reports:
        print(f"Report: {report}")
    return summary


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = parser()
    args = p.parse_args(argv)
    site = resolve_site(args, p)
    console = Console(not args.no_colour)
    try:
        database, output_dir = validate_paths(args.database, args.output_dir)
        if not args.dry_run and shutil.which("ping") is None:
            raise AppError("operating-system ping executable was not found on PATH")
        servers = load_servers(database, site)

        console.heading(f"Servers for {site!r}")
        for host in servers:
            print(f"  {host}")
        if not args.no_export_list:
            print(f"Server list: {export_list(args.server_list, servers)}")

        failed = False
        for number in range(1, args.repeat + 1):
            summary = run_once(args, site, database, output_dir, servers, console, number)
            failed = failed or bool(summary.down or summary.errors)
            if number < args.repeat and args.interval:
                print(f"Next run begins in {args.interval:g} second(s).")
                time.sleep(args.interval)

        return 0 if args.always_zero or args.dry_run or not failed else 1
    except AppError as exc:
        console.fail(f"Error: {exc}")
        return 2
    except KeyboardInterrupt:
        console.warn("\nInterrupted by user.")
        return 130
    except OSError as exc:
        console.fail(f"Operating-system error: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
