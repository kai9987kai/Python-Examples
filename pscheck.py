#!/usr/bin/env python3
"""
pscheck.py - advanced cross-platform process inspection utility.

Author of original script: Craig Richards
Modernised version: 3.0

Requires:
    python -m pip install psutil

Examples:
    python pscheck.py python
    python pscheck.py nginx --exact --field name
    python pscheck.py --pid 1234 --verbose
    python pscheck.py chrome --sort memory --limit 10
    python pscheck.py "python.*worker" --regex --watch 2
    python pscheck.py --all --cpu-min 5 --format json
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import platform
import re
import shlex
import shutil
import socket
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Callable, Iterable, Sequence, TextIO, TypeVar

try:
    import psutil
except ImportError:
    print(
        "pscheck requires the 'psutil' package.\n"
        "Install it with: python -m pip install psutil",
        file=sys.stderr,
    )
    raise SystemExit(3)


APP_NAME = "pscheck"
APP_VERSION = "3.0.0"
DEFAULT_LIMIT = 25
DEFAULT_SAMPLE_SECONDS = 0.15
DEFAULT_WATCH_SECONDS = 2.0
EXIT_OK = 0
EXIT_NO_MATCH = 1
EXIT_USAGE_OR_RUNTIME_ERROR = 2
EXIT_INTERRUPTED = 130

T = TypeVar("T")


@dataclass(slots=True)
class ProcessRecord:
    pid: int
    ppid: int | None
    name: str
    username: str | None
    status: str | None
    cpu_percent: float
    memory_percent: float
    rss_bytes: int
    thread_count: int | None
    create_time_epoch: float | None
    started: str | None
    elapsed_seconds: float | None
    elapsed: str | None
    executable: str | None
    working_directory: str | None
    command_line: str | None


@dataclass(slots=True)
class Snapshot:
    timestamp: str
    hostname: str
    query: str | None
    matched_count: int
    displayed_count: int
    new_pids: list[int]
    exited_pids: list[int]
    processes: list[ProcessRecord]


def positive_float(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a number") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def non_negative_float(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a number") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return parsed


def non_negative_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return parsed


def positive_int(value: str) -> int:
    parsed = non_negative_int(value)
    if parsed == 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=APP_NAME,
        description=(
            "Find and inspect running processes safely without parsing shell output. "
            "Matching is case-insensitive substring matching by default."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        allow_abbrev=False,
    )
    parser.add_argument(
        "query",
        nargs="?",
        help="process name, executable path, or command-line text to find",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {APP_VERSION} (psutil {psutil.__version__})",
    )
    parser.add_argument(
        "-p",
        "--pid",
        dest="pids",
        action="append",
        type=positive_int,
        metavar="PID",
        help="inspect a specific PID; may be supplied more than once",
    )
    parser.add_argument(
        "-a",
        "--all",
        action="store_true",
        help="show all visible processes instead of requiring a query",
    )
    parser.add_argument(
        "-f",
        "--field",
        choices=("all", "name", "exe", "cmdline"),
        default="name",
        help="process field searched by QUERY",
    )

    match_group = parser.add_mutually_exclusive_group()
    match_group.add_argument(
        "-e",
        "--exact",
        action="store_true",
        help="require an exact field match",
    )
    match_group.add_argument(
        "-r",
        "--regex",
        action="store_true",
        help="interpret QUERY as a Python regular expression",
    )
    parser.add_argument(
        "-c",
        "--case-sensitive",
        action="store_true",
        help="use case-sensitive matching",
    )
    parser.add_argument(
        "--include-self",
        action="store_true",
        help="include the current pscheck process in results",
    )
    parser.add_argument(
        "--user",
        help="only include usernames containing this text",
    )
    parser.add_argument(
        "--status",
        action="append",
        metavar="STATE",
        help="only include a process state; may be supplied more than once",
    )
    parser.add_argument(
        "--cpu-min",
        type=non_negative_float,
        default=0.0,
        metavar="PERCENT",
        help="minimum sampled CPU percentage",
    )
    parser.add_argument(
        "--memory-min",
        type=non_negative_float,
        default=0.0,
        metavar="PERCENT",
        help="minimum physical-memory percentage",
    )
    parser.add_argument(
        "--sample",
        type=non_negative_float,
        default=DEFAULT_SAMPLE_SECONDS,
        metavar="SECONDS",
        help="CPU sampling window; zero disables the wait",
    )
    parser.add_argument(
        "--sort",
        choices=("cpu", "memory", "rss", "pid", "name", "start"),
        default="cpu",
        help="result sort key",
    )
    parser.add_argument(
        "--ascending",
        action="store_true",
        help="sort from lowest to highest instead of highest to lowest",
    )
    parser.add_argument(
        "-n",
        "--limit",
        type=non_negative_int,
        default=DEFAULT_LIMIT,
        metavar="COUNT",
        help="maximum rows to show; zero means unlimited",
    )
    parser.add_argument(
        "-o",
        "--format",
        choices=("table", "json", "csv"),
        default="table",
        help="output format",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="show full details below the table",
    )
    parser.add_argument(
        "-w",
        "--watch",
        nargs="?",
        const=DEFAULT_WATCH_SECONDS,
        type=positive_float,
        metavar="SECONDS",
        help="refresh continuously; default interval is 2 seconds",
    )
    return parser


def safe_call(function: Callable[[], T], default: T) -> T:
    try:
        return function()
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, OSError):
        return default


def command_line_text(arguments: Sequence[str] | None) -> str | None:
    if not arguments:
        return None
    try:
        if os.name == "nt":
            return subprocess.list2cmdline(list(arguments))
        return shlex.join(arguments)
    except (TypeError, ValueError):
        return " ".join(str(argument) for argument in arguments)


def selected_match_values(info: dict[str, object], field: str) -> list[str]:
    name = str(info.get("name") or "")
    executable = str(info.get("exe") or "")
    raw_cmdline = info.get("cmdline")
    cmdline = command_line_text(raw_cmdline if isinstance(raw_cmdline, (list, tuple)) else None) or ""

    values = {
        "name": [name],
        "exe": [executable],
        "cmdline": [cmdline],
        "all": [name, executable, cmdline],
    }
    return values[field]


def build_matcher(args: argparse.Namespace, query: str | None) -> Callable[[dict[str, object]], bool]:
    if query is None:
        return lambda _info: True

    if args.regex:
        flags = 0 if args.case_sensitive else re.IGNORECASE
        try:
            expression = re.compile(query, flags)
        except re.error as exc:
            raise ValueError(f"invalid regular expression: {exc}") from exc

        return lambda info: any(
            expression.search(value) is not None
            for value in selected_match_values(info, args.field)
        )

    expected = query if args.case_sensitive else query.casefold()

    def matches(info: dict[str, object]) -> bool:
        for value in selected_match_values(info, args.field):
            candidate = value if args.case_sensitive else value.casefold()
            if args.exact and candidate == expected:
                return True
            if not args.exact and expected in candidate:
                return True
        return False

    return matches


def discover_processes(
    args: argparse.Namespace,
    matcher: Callable[[dict[str, object]], bool],
) -> list[psutil.Process]:
    attributes = ["pid", "name", "exe", "cmdline", "username", "status"]
    requested_pids = set(args.pids or [])
    requested_statuses = {state.casefold() for state in (args.status or [])}
    requested_user = args.user.casefold() if args.user else None
    own_pid = os.getpid()
    matches: list[psutil.Process] = []

    for process in psutil.process_iter(attrs=attributes, ad_value=None):
        info = process.info
        pid = int(info["pid"])

        if not args.include_self and pid == own_pid:
            continue
        if requested_pids and pid not in requested_pids:
            continue
        if requested_statuses:
            status = str(info.get("status") or "").casefold()
            if status not in requested_statuses:
                continue
        if requested_user:
            username = str(info.get("username") or "").casefold()
            if requested_user not in username:
                continue
        if not matcher(info):
            continue

        matches.append(process)

    return matches


def format_duration(seconds: float | None) -> str | None:
    if seconds is None:
        return None
    seconds = max(0, int(seconds))
    days, remainder = divmod(seconds, 86_400)
    hours, remainder = divmod(remainder, 3_600)
    minutes, secs = divmod(remainder, 60)
    if days:
        return f"{days}d {hours:02}:{minutes:02}:{secs:02}"
    return f"{hours:02}:{minutes:02}:{secs:02}"


def format_bytes(value: int) -> str:
    amount = float(max(0, value))
    units = ("B", "KiB", "MiB", "GiB", "TiB", "PiB")
    for unit in units:
        if amount < 1024.0 or unit == units[-1]:
            if unit == "B":
                return f"{amount:.0f} {unit}"
            return f"{amount:.1f} {unit}"
        amount /= 1024.0
    return f"{amount:.1f} PiB"


def collect_records(processes: Iterable[psutil.Process], sample_seconds: float) -> list[ProcessRecord]:
    live_processes: list[psutil.Process] = []

    for process in processes:
        try:
            process.cpu_percent(interval=None)
            live_processes.append(process)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    if sample_seconds > 0 and live_processes:
        time.sleep(sample_seconds)

    now = time.time()
    records: list[ProcessRecord] = []

    for process in live_processes:
        try:
            with process.oneshot():
                pid = process.pid
                ppid = safe_call(process.ppid, None)
                name = safe_call(process.name, f"pid-{pid}")
                username = safe_call(process.username, None)
                status = safe_call(process.status, None)
                cpu_percent = safe_call(lambda: process.cpu_percent(interval=None), 0.0)
                memory_percent = safe_call(process.memory_percent, 0.0)
                memory_info = safe_call(process.memory_info, None)
                thread_count = safe_call(process.num_threads, None)
                create_time = safe_call(process.create_time, None)
                executable = safe_call(process.exe, None)
                working_directory = safe_call(process.cwd, None)
                arguments = safe_call(process.cmdline, None)
        except (psutil.NoSuchProcess, psutil.ZombieProcess):
            continue

        rss_bytes = int(memory_info.rss) if memory_info is not None else 0
        started = (
            datetime.fromtimestamp(create_time).astimezone().isoformat(timespec="seconds")
            if create_time is not None
            else None
        )
        elapsed_seconds = max(0.0, now - create_time) if create_time is not None else None

        records.append(
            ProcessRecord(
                pid=pid,
                ppid=ppid,
                name=name,
                username=username,
                status=status,
                cpu_percent=round(float(cpu_percent), 2),
                memory_percent=round(float(memory_percent), 3),
                rss_bytes=rss_bytes,
                thread_count=thread_count,
                create_time_epoch=create_time,
                started=started,
                elapsed_seconds=elapsed_seconds,
                elapsed=format_duration(elapsed_seconds),
                executable=executable,
                working_directory=working_directory,
                command_line=command_line_text(arguments),
            )
        )

    return records


def filter_sort_limit(
    records: list[ProcessRecord],
    args: argparse.Namespace,
) -> tuple[list[ProcessRecord], int, set[int]]:
    filtered = [
        record
        for record in records
        if record.cpu_percent >= args.cpu_min
        and record.memory_percent >= args.memory_min
    ]

    sorters: dict[str, Callable[[ProcessRecord], object]] = {
        "cpu": lambda record: record.cpu_percent,
        "memory": lambda record: record.memory_percent,
        "rss": lambda record: record.rss_bytes,
        "pid": lambda record: record.pid,
        "name": lambda record: record.name.casefold(),
        "start": lambda record: record.create_time_epoch or 0.0,
    }
    filtered.sort(key=sorters[args.sort], reverse=not args.ascending)

    matched_count = len(filtered)
    matched_pids = {record.pid for record in filtered}
    displayed = filtered[: args.limit] if args.limit else filtered
    return displayed, matched_count, matched_pids


def truncate(value: object, width: int) -> str:
    text = "-" if value is None or value == "" else str(value)
    if len(text) <= width:
        return text
    if width <= 3:
        return text[:width]
    return text[: width - 3] + "..."


def table_columns(terminal_width: int) -> list[tuple[str, str, int, str]]:
    columns: list[tuple[str, str, int, str]] = [
        ("pid", "PID", 7, ">"),
        ("cpu", "CPU%", 7, ">"),
        ("memory", "MEM%", 7, ">"),
        ("rss", "RSS", 10, ">"),
        ("status", "STATUS", 10, "<"),
        ("elapsed", "ELAPSED", 12, ">"),
    ]

    if terminal_width >= 100:
        columns.insert(1, ("user", "USER", 16, "<"))
    if terminal_width >= 118:
        columns.insert(1, ("ppid", "PPID", 7, ">"))
        columns.insert(-1, ("threads", "THR", 5, ">"))
    if terminal_width >= 145:
        columns.insert(-1, ("started", "STARTED", 25, "<"))

    fixed_width = sum(column[2] for column in columns) + (len(columns) * 2)
    name_width = max(12, terminal_width - fixed_width - 1)
    columns.append(("name", "NAME", name_width, "<"))
    return columns


def record_cell(record: ProcessRecord, key: str) -> object:
    values: dict[str, object] = {
        "pid": record.pid,
        "ppid": record.ppid,
        "user": record.username,
        "cpu": f"{record.cpu_percent:.1f}",
        "memory": f"{record.memory_percent:.2f}",
        "rss": format_bytes(record.rss_bytes),
        "threads": record.thread_count,
        "status": record.status,
        "started": record.started,
        "elapsed": record.elapsed,
        "name": record.name,
    }
    return values[key]


def render_table(snapshot: Snapshot, args: argparse.Namespace, stream: TextIO = sys.stdout) -> None:
    terminal_width = max(72, shutil.get_terminal_size(fallback=(120, 30)).columns)
    title = f"{APP_NAME} {APP_VERSION} | {snapshot.hostname} | {snapshot.timestamp}"
    print(title, file=stream)

    target = f"query={snapshot.query!r}" if snapshot.query is not None else "query=<all>"
    changes = ""
    if snapshot.new_pids or snapshot.exited_pids:
        changes = f" | new={snapshot.new_pids or '-'} | exited={snapshot.exited_pids or '-'}"
    shown = (
        f" | shown={snapshot.displayed_count}"
        if snapshot.displayed_count != snapshot.matched_count
        else ""
    )
    print(f"{target} | matches={snapshot.matched_count}{shown}{changes}", file=stream)

    if not snapshot.processes:
        print("No matching processes found.", file=stream)
        return

    columns = table_columns(terminal_width)
    header = "  ".join(
        f"{truncate(label, width):{alignment}{width}}"
        for _key, label, width, alignment in columns
    )
    separator = "  ".join("-" * width for _key, _label, width, _alignment in columns)
    print(separator, file=stream)
    print(header, file=stream)
    print(separator, file=stream)

    for record in snapshot.processes:
        row = "  ".join(
            f"{truncate(record_cell(record, key), width):{alignment}{width}}"
            for key, _label, width, alignment in columns
        )
        print(row, file=stream)

    print(separator, file=stream)

    if args.verbose:
        for record in snapshot.processes:
            print(f"\n[{record.pid}] {record.name}", file=stream)
            print(f"  Parent PID       : {record.ppid if record.ppid is not None else '-'}", file=stream)
            print(f"  Owner            : {record.username or '-'}", file=stream)
            print(f"  Status           : {record.status or '-'}", file=stream)
            print(f"  CPU              : {record.cpu_percent:.2f}%", file=stream)
            print(f"  Memory           : {record.memory_percent:.3f}% ({format_bytes(record.rss_bytes)} RSS)", file=stream)
            print(f"  Threads          : {record.thread_count if record.thread_count is not None else '-'}", file=stream)
            print(f"  Started          : {record.started or '-'}", file=stream)
            print(f"  Elapsed          : {record.elapsed or '-'}", file=stream)
            print(f"  Executable       : {record.executable or '-'}", file=stream)
            print(f"  Working directory: {record.working_directory or '-'}", file=stream)
            print(f"  Command line     : {record.command_line or '-'}", file=stream)


def render_json(snapshot: Snapshot, stream: TextIO = sys.stdout) -> None:
    payload = {
        "application": APP_NAME,
        "version": APP_VERSION,
        "psutil_version": psutil.__version__,
        **asdict(snapshot),
    }
    json.dump(payload, stream, indent=2, ensure_ascii=False)
    stream.write("\n")


def render_csv(snapshot: Snapshot, stream: TextIO = sys.stdout) -> None:
    fieldnames = list(asdict(snapshot.processes[0]).keys()) if snapshot.processes else [
        field.name for field in ProcessRecord.__dataclass_fields__.values()
    ]
    writer = csv.DictWriter(stream, fieldnames=fieldnames)
    writer.writeheader()
    for record in snapshot.processes:
        writer.writerow(asdict(record))


def make_snapshot(
    records: list[ProcessRecord],
    matched_count: int,
    matched_pids: set[int],
    query: str | None,
    previous_pids: set[int] | None,
) -> Snapshot:
    current_pids = matched_pids
    new_pids = sorted(current_pids - previous_pids) if previous_pids is not None else []
    exited_pids = sorted(previous_pids - current_pids) if previous_pids is not None else []
    return Snapshot(
        timestamp=datetime.now().astimezone().isoformat(timespec="seconds"),
        hostname=socket.gethostname() or platform.node() or "unknown-host",
        query=query,
        matched_count=matched_count,
        displayed_count=len(records),
        new_pids=new_pids,
        exited_pids=exited_pids,
        processes=records,
    )


def clear_terminal() -> None:
    if sys.stdout.isatty():
        sys.stdout.write("\033[2J\033[H")
        sys.stdout.flush()


def resolve_query(args: argparse.Namespace, parser: argparse.ArgumentParser) -> str | None:
    if args.query and args.pids:
        parser.error("QUERY and --pid cannot be used together")
    if args.all and (args.query or args.pids):
        parser.error("--all cannot be combined with QUERY or --pid")
    if args.watch is not None and args.format != "table":
        parser.error("--watch currently requires --format table")
    if args.verbose and args.format != "table":
        parser.error("--verbose requires --format table")

    if args.query:
        return args.query
    if args.pids or args.all:
        return None

    if not sys.stdin.isatty():
        parser.error("provide QUERY, --pid PID, or --all when standard input is not interactive")

    try:
        query = input("Enter the name, path, or command text of the process to check: ").strip()
    except EOFError:
        parser.error("no query supplied")

    if not query:
        parser.error("query cannot be empty")
    return query


def run_once(
    args: argparse.Namespace,
    query: str | None,
    matcher: Callable[[dict[str, object]], bool],
    previous_pids: set[int] | None,
) -> tuple[Snapshot, set[int]]:
    processes = discover_processes(args, matcher)
    records = collect_records(processes, args.sample)
    displayed, matched_count, matched_pids = filter_sort_limit(records, args)
    snapshot = make_snapshot(displayed, matched_count, matched_pids, query, previous_pids)
    return snapshot, matched_pids


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    query = resolve_query(args, parser)

    try:
        matcher = build_matcher(args, query)
    except ValueError as exc:
        parser.error(str(exc))

    previous_pids: set[int] | None = None

    try:
        while True:
            cycle_started = time.monotonic()
            snapshot, current_pids = run_once(args, query, matcher, previous_pids)

            if args.watch is not None:
                clear_terminal()

            if args.format == "json":
                render_json(snapshot)
            elif args.format == "csv":
                render_csv(snapshot)
            else:
                render_table(snapshot, args)

            if args.watch is None:
                return EXIT_OK if snapshot.matched_count else EXIT_NO_MATCH

            previous_pids = current_pids
            elapsed = time.monotonic() - cycle_started
            time.sleep(max(0.0, args.watch - elapsed))

    except KeyboardInterrupt:
        if args.watch is not None:
            print("\nMonitoring stopped.", file=sys.stderr)
        return EXIT_INTERRUPTED
    except (psutil.Error, OSError) as exc:
        print(f"{APP_NAME}: process inspection failed: {exc}", file=sys.stderr)
        return EXIT_USAGE_OR_RUNTIME_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
