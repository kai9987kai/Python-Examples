from pathlib import Path
import py_compile, textwrap

code = r'''#!/usr/bin/env python3
"""
Script Name : get_info_remote_srv.py
Purpose     : Collect diagnostic information from remote Linux servers over SSH.
Version     : 3.0.0

Features:
- Uses OpenSSH and SSH keys (no password handling in Python)
- Parallel host collection
- Per-command timeout
- Strong batch/non-interactive SSH behaviour
- Structured command results
- Human-readable terminal output
- Optional JSON export
- Optional additional hosts and commands from the CLI
- Logging
- Exit status suitable for automation/CI
"""

from __future__ import annotations

import argparse
import concurrent.futures
import dataclasses
import datetime as dt
import json
import logging
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterable, Sequence


APP_NAME = "remote-server-inspector"
APP_VERSION = "3.0.0"

DEFAULT_HOSTS: tuple[str, ...] = ("proxy1", "proxy")

DEFAULT_COMMANDS: tuple[str, ...] = (
    "hostname -f 2>/dev/null || hostname",
    "uname -a",
    "uptime",
    "whoami",
    "id",
    "printf 'CPU cores: '; nproc 2>/dev/null || getconf _NPROCESSORS_ONLN",
    "printf 'Memory:\\n'; free -h 2>/dev/null || vm_stat 2>/dev/null || true",
    "printf 'Root filesystem:\\n'; df -h /",
    "printf 'Kernel: '; uname -r",
    "printf 'OS: '; "
    "(grep '^PRETTY_NAME=' /etc/os-release 2>/dev/null | cut -d= -f2- | tr -d '\"') "
    "|| true",
)

DEFAULT_CONNECT_TIMEOUT = 8
DEFAULT_COMMAND_TIMEOUT = 20
DEFAULT_MAX_WORKERS = 8

LOG = logging.getLogger(APP_NAME)


@dataclasses.dataclass(slots=True)
class CommandResult:
    host: str
    command: str
    returncode: int | None
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool = False
    launch_error: str | None = None

    @property
    def succeeded(self) -> bool:
        return (
            not self.timed_out
            and self.launch_error is None
            and self.returncode == 0
        )

    def as_dict(self) -> dict[str, object]:
        return dataclasses.asdict(self)


@dataclasses.dataclass(slots=True)
class HostResult:
    host: str
    started_at: str
    duration_seconds: float
    commands: list[CommandResult]

    @property
    def succeeded(self) -> bool:
        return bool(self.commands) and all(item.succeeded for item in self.commands)

    @property
    def failed_command_count(self) -> int:
        return sum(not item.succeeded for item in self.commands)

    def as_dict(self) -> dict[str, object]:
        return {
            "host": self.host,
            "started_at": self.started_at,
            "duration_seconds": self.duration_seconds,
            "succeeded": self.succeeded,
            "failed_command_count": self.failed_command_count,
            "commands": [item.as_dict() for item in self.commands],
        }


def positive_int(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("value must be greater than zero")
    return number


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=APP_NAME,
        description=(
            "Collect diagnostic data from one or more Linux servers using "
            "key-based OpenSSH connections."
        ),
    )

    parser.add_argument(
        "hosts",
        nargs="*",
        help=(
            "Remote SSH hosts. If omitted, the built-in defaults are used: "
            + ", ".join(DEFAULT_HOSTS)
        ),
    )
    parser.add_argument(
        "-c",
        "--command",
        action="append",
        dest="commands",
        help=(
            "Remote command to run. Repeat this option for multiple commands. "
            "If omitted, the built-in diagnostic command set is used."
        ),
    )
    parser.add_argument(
        "-u",
        "--user",
        help="Optional SSH username to use for every target.",
    )
    parser.add_argument(
        "-p",
        "--port",
        type=positive_int,
        default=22,
        help="SSH port. Default: 22.",
    )
    parser.add_argument(
        "-i",
        "--identity-file",
        type=Path,
        help="Private key file passed to OpenSSH with -i.",
    )
    parser.add_argument(
        "--connect-timeout",
        type=positive_int,
        default=DEFAULT_CONNECT_TIMEOUT,
        help=f"SSH connection timeout in seconds. Default: {DEFAULT_CONNECT_TIMEOUT}.",
    )
    parser.add_argument(
        "--command-timeout",
        type=positive_int,
        default=DEFAULT_COMMAND_TIMEOUT,
        help=f"Maximum time for each command. Default: {DEFAULT_COMMAND_TIMEOUT}.",
    )
    parser.add_argument(
        "-j",
        "--jobs",
        type=positive_int,
        default=DEFAULT_MAX_WORKERS,
        help=f"Maximum parallel hosts. Default: {DEFAULT_MAX_WORKERS}.",
    )
    parser.add_argument(
        "--json",
        dest="json_path",
        type=Path,
        help="Write complete structured results to this JSON file.",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable ANSI status colours.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {APP_VERSION}",
    )

    return parser


def validate_environment(identity_file: Path | None) -> None:
    if shutil.which("ssh") is None:
        raise RuntimeError(
            "OpenSSH client executable 'ssh' was not found on PATH."
        )

    if identity_file is not None:
        identity_file = identity_file.expanduser()
        if not identity_file.is_file():
            raise RuntimeError(
                f"SSH identity file does not exist or is not a file: {identity_file}"
            )


def ssh_target(host: str, user: str | None) -> str:
    return f"{user}@{host}" if user else host


def build_ssh_command(
    *,
    host: str,
    remote_command: str,
    user: str | None,
    port: int,
    identity_file: Path | None,
    connect_timeout: int,
) -> list[str]:
    argv = [
        "ssh",
        "-T",
        "-p",
        str(port),
        "-o",
        "BatchMode=yes",
        "-o",
        f"ConnectTimeout={connect_timeout}",
        "-o",
        "ConnectionAttempts=1",
        "-o",
        "ServerAliveInterval=5",
        "-o",
        "ServerAliveCountMax=2",
        "-o",
        "LogLevel=ERROR",
    ]

    if identity_file is not None:
        argv.extend(["-i", str(identity_file.expanduser())])

    argv.extend(
        [
            "--",
            ssh_target(host, user),
            remote_command,
        ]
    )
    return argv


def run_remote_command(
    *,
    host: str,
    command: str,
    user: str | None,
    port: int,
    identity_file: Path | None,
    connect_timeout: int,
    command_timeout: int,
) -> CommandResult:
    argv = build_ssh_command(
        host=host,
        remote_command=command,
        user=user,
        port=port,
        identity_file=identity_file,
        connect_timeout=connect_timeout,
    )

    LOG.debug("Executing: %s", " ".join(shlex.quote(part) for part in argv))

    started = time.monotonic()

    try:
        completed = subprocess.run(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=command_timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        duration = time.monotonic() - started

        stdout = exc.stdout or ""
        stderr = exc.stderr or ""

        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")

        return CommandResult(
            host=host,
            command=command,
            returncode=None,
            stdout=stdout.rstrip(),
            stderr=stderr.rstrip(),
            duration_seconds=duration,
            timed_out=True,
        )
    except OSError as exc:
        duration = time.monotonic() - started
        return CommandResult(
            host=host,
            command=command,
            returncode=None,
            stdout="",
            stderr="",
            duration_seconds=duration,
            launch_error=str(exc),
        )

    duration = time.monotonic() - started

    return CommandResult(
        host=host,
        command=command,
        returncode=completed.returncode,
        stdout=completed.stdout.rstrip(),
        stderr=completed.stderr.rstrip(),
        duration_seconds=duration,
    )


def inspect_host(
    *,
    host: str,
    commands: Sequence[str],
    user: str | None,
    port: int,
    identity_file: Path | None,
    connect_timeout: int,
    command_timeout: int,
) -> HostResult:
    LOG.info("Inspecting %s", host)

    wall_started = time.monotonic()
    timestamp = dt.datetime.now(dt.timezone.utc).isoformat()
    results: list[CommandResult] = []

    for command in commands:
        result = run_remote_command(
            host=host,
            command=command,
            user=user,
            port=port,
            identity_file=identity_file,
            connect_timeout=connect_timeout,
            command_timeout=command_timeout,
        )
        results.append(result)

        # SSH connection-level errors generally make all subsequent commands
        # fail too. Stop early for the most common OpenSSH fatal return code.
        if result.returncode == 255:
            LOG.warning(
                "SSH connection to %s failed; skipping remaining commands.",
                host,
            )
            break

        if result.timed_out:
            LOG.warning(
                "Command timed out on %s after %.2fs: %s",
                host,
                result.duration_seconds,
                command,
            )

    return HostResult(
        host=host,
        started_at=timestamp,
        duration_seconds=time.monotonic() - wall_started,
        commands=results,
    )


def inspect_all_hosts(
    *,
    hosts: Sequence[str],
    commands: Sequence[str],
    user: str | None,
    port: int,
    identity_file: Path | None,
    connect_timeout: int,
    command_timeout: int,
    jobs: int,
) -> list[HostResult]:
    results_by_host: dict[str, HostResult] = {}

    worker_count = min(jobs, len(hosts))

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=worker_count,
        thread_name_prefix="ssh-inspector",
    ) as executor:
        futures = {
            executor.submit(
                inspect_host,
                host=host,
                commands=commands,
                user=user,
                port=port,
                identity_file=identity_file,
                connect_timeout=connect_timeout,
                command_timeout=command_timeout,
            ): host
            for host in hosts
        }

        for future in concurrent.futures.as_completed(futures):
            host = futures[future]
            try:
                results_by_host[host] = future.result()
            except Exception as exc:
                LOG.exception("Unhandled error while inspecting %s", host)
                results_by_host[host] = HostResult(
                    host=host,
                    started_at=dt.datetime.now(dt.timezone.utc).isoformat(),
                    duration_seconds=0.0,
                    commands=[
                        CommandResult(
                            host=host,
                            command="<internal>",
                            returncode=None,
                            stdout="",
                            stderr="",
                            duration_seconds=0.0,
                            launch_error=f"{type(exc).__name__}: {exc}",
                        )
                    ],
                )

    # Preserve the same host ordering the user supplied.
    return [results_by_host[host] for host in hosts]


class Palette:
    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled

    def _paint(self, code: str, text: str) -> str:
        if not self.enabled:
            return text
        return f"\033[{code}m{text}\033[0m"

    def green(self, text: str) -> str:
        return self._paint("32", text)

    def red(self, text: str) -> str:
        return self._paint("31", text)

    def yellow(self, text: str) -> str:
        return self._paint("33", text)

    def cyan(self, text: str) -> str:
        return self._paint("36", text)

    def bold(self, text: str) -> str:
        return self._paint("1", text)


def display_results(results: Iterable[HostResult], *, color: bool) -> None:
    palette = Palette(enabled=color)

    for host_result in results:
        print()
        print(
            palette.bold(
                f"{'=' * 18} {host_result.host} {'=' * 18}"
            )
        )

        for command_result in host_result.commands:
            if command_result.succeeded:
                status = palette.green("OK")
            elif command_result.timed_out:
                status = palette.yellow("TIMEOUT")
            else:
                status = palette.red("FAILED")

            print()
            print(
                f"[{status}] {palette.cyan(command_result.command)} "
                f"({command_result.duration_seconds:.2f}s)"
            )

            if command_result.stdout:
                print(command_result.stdout)

            if command_result.stderr:
                print(palette.red(f"stderr: {command_result.stderr}"))

            if command_result.launch_error:
                print(
                    palette.red(
                        f"launch error: {command_result.launch_error}"
                    )
                )

            if command_result.returncode is not None and command_result.returncode != 0:
                print(
                    palette.red(
                        f"remote SSH process exit status: "
                        f"{command_result.returncode}"
                    )
                )

        overall = (
            palette.green("PASS")
            if host_result.succeeded
            else palette.red("FAIL")
        )

        print()
        print(
            f"Host result: {overall}; "
            f"{host_result.failed_command_count} failed command(s); "
            f"{host_result.duration_seconds:.2f}s total"
        )


def write_json_report(path: Path, results: Sequence[HostResult]) -> None:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "application": APP_NAME,
        "version": APP_VERSION,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "host_count": len(results),
        "successful_hosts": sum(item.succeeded for item in results),
        "failed_hosts": sum(not item.succeeded for item in results),
        "results": [item.as_dict() for item in results],
    }

    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    LOG.info("JSON report written to %s", path)


def configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def unique_nonempty(values: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []

    for raw in values:
        value = raw.strip()
        if value and value not in seen:
            seen.add(value)
            output.append(value)

    return output


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    configure_logging(args.verbose)

    hosts = unique_nonempty(args.hosts or list(DEFAULT_HOSTS))
    commands = unique_nonempty(args.commands or list(DEFAULT_COMMANDS))

    if not hosts:
        parser.error("at least one host is required")

    if not commands:
        parser.error("at least one command is required")

    try:
        validate_environment(args.identity_file)
    except RuntimeError as exc:
        parser.error(str(exc))

    results = inspect_all_hosts(
        hosts=hosts,
        commands=commands,
        user=args.user,
        port=args.port,
        identity_file=args.identity_file,
        connect_timeout=args.connect_timeout,
        command_timeout=args.command_timeout,
        jobs=args.jobs,
    )

    use_color = (
        not args.no_color
        and sys.stdout.isatty()
        and sys.platform != "win32"
    )

    display_results(results, color=use_color)

    if args.json_path:
        try:
            write_json_report(args.json_path, results)
        except OSError as exc:
            print(
                f"Could not write JSON report: {exc}",
                file=sys.stderr,
            )
            return 2

    total = len(results)
    passed = sum(result.succeeded for result in results)
    failed = total - passed

    print()
    print("-" * 58)
    print(f"Hosts inspected: {total} | passed: {passed} | failed: {failed}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
'''

path = Path("/mnt/data/get_info_remote_srv.py")
path.write_text(code, encoding="utf-8")
py_compile.compile(str(path), doraise=True)
print(f"Syntax check passed: {path}")
