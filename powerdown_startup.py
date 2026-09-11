from pathlib import Path

script = r'''#!/usr/bin/env python3
"""
powerdown_startup.py
====================

Modern replacement for the original 2012/2017 server-startup script.

What it does
------------
* Reads targets from startup_list.txt.
* Checks targets concurrently instead of one at a time.
* Can test the actual TCP service as well as ICMP ping.
* Distinguishes "host down" from "host up, service down".
* Opens PuTTY sessions on Windows or OpenSSH sessions on Linux/macOS.
* Uses subprocess argument lists instead of shell=True.
* Writes timestamped logs and optional JSON results.
* Supports dry-run mode and useful exit codes.
* Uses only the Python standard library.

Backward-compatible startup_list.txt
------------------------------------
A file containing one host/session per line still works:

    server01
    server02
    192.168.1.50

Extended format
---------------
You can optionally use:

    host|session|protocol|port|user

Examples:

    server01
    192.168.1.20|Core Router
    fileserver.example.com|File Server|ssh|22|kai
    10.0.0.5|Legacy Telnet|telnet|23|

The "session" field is the saved PuTTY session name on Windows.
Blank lines and lines beginning with # or ; are ignored.

Python: 3.10+
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import logging
import math
import os
import platform
import shlex
import shutil
import socket
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence


APP_NAME = "PowerDown Startup"
VERSION = "2.0.0"

DEFAULT_LIST_FILE = "startup_list.txt"
DEFAULT_ATTEMPTS = 3
DEFAULT_TIMEOUT = 1.5
DEFAULT_WORKERS = min(32, (os.cpu_count() or 1) * 4)


@dataclass(frozen=True)
class Target:
    """One target loaded from startup_list.txt."""

    host: str
    session: str
    protocol: str = "ssh"
    port: int = 22
    user: str | None = None
    source_line: int = 0

    @property
    def ssh_destination(self) -> str:
        """Return user@host when a username is configured."""
        return f"{self.user}@{self.host}" if self.user else self.host


@dataclass
class ProbeResult:
    """Result of checking one target."""

    host: str
    session: str
    protocol: str
    port: int
    user: str | None
    source_line: int

    status: str
    ready: bool

    ping_ok: bool | None
    tcp_ok: bool | None

    check_seconds: float
    detail: str

    launched: bool = False
    launch_detail: str = ""


def default_port(protocol: str) -> int:
    """Return the conventional port for a supported protocol."""
    return {
        "ssh": 22,
        "telnet": 23,
        "raw": 22,
    }.get(protocol.lower(), 22)


def parse_target_line(raw: str, line_number: int) -> Target | None:
    """
    Parse one startup-list line.

    Supported forms:
        host
        host|session
        host|session|protocol
        host|session|protocol|port
        host|session|protocol|port|user
    """
    stripped = raw.strip()

    if not stripped:
        return None

    if stripped.startswith(("#", ";")):
        return None

    parts = [part.strip() for part in stripped.split("|")]

    if len(parts) > 5:
        raise ValueError(
            f"line {line_number}: expected at most 5 pipe-separated "
            f"fields, got {len(parts)}"
        )

    parts += [""] * (5 - len(parts))

    host, session, protocol, port_text, user = parts

    if not host:
        raise ValueError(f"line {line_number}: host is empty")

    protocol = (protocol or "ssh").lower()

    if protocol not in {"ssh", "telnet", "raw"}:
        raise ValueError(
            f"line {line_number}: unsupported protocol {protocol!r}; "
            "use ssh, telnet, or raw"
        )

    if port_text:
        try:
            port = int(port_text)
        except ValueError as exc:
            raise ValueError(
                f"line {line_number}: invalid port {port_text!r}"
            ) from exc

        if not 1 <= port <= 65535:
            raise ValueError(
                f"line {line_number}: port must be between 1 and 65535"
            )
    else:
        port = default_port(protocol)

    return Target(
        host=host,
        session=session or host,
        protocol=protocol,
        port=port,
        user=user or None,
        source_line=line_number,
    )


def load_targets(path: Path) -> list[Target]:
    """Load and validate every target before doing any network work."""
    if not path.is_file():
        raise FileNotFoundError(f"server list not found: {path}")

    targets: list[Target] = []
    errors: list[str] = []

    with path.open("r", encoding="utf-8-sig") as handle:
        for line_number, raw in enumerate(handle, start=1):
            try:
                target = parse_target_line(raw, line_number)
            except ValueError as exc:
                errors.append(str(exc))
                continue

            if target is not None:
                targets.append(target)

    if errors:
        raise ValueError(
            "Invalid target list:\n  - " + "\n  - ".join(errors)
        )

    if not targets:
        raise ValueError(f"no targets found in {path}")

    return targets


def build_ping_command(
    host: str,
    attempts: int,
    timeout: float,
) -> list[str]:
    """
    Build a native ping command.

    Important platform difference:
    * Windows ping -w: milliseconds
    * macOS ping -W: milliseconds
    * Linux iputils ping -W: seconds
    """
    system = platform.system()

    if system == "Windows":
        return [
            "ping",
            "-n",
            str(attempts),
            "-w",
            str(max(1, int(timeout * 1000))),
            host,
        ]

    if system == "Darwin":
        return [
            "ping",
            "-c",
            str(attempts),
            "-W",
            str(max(1, int(timeout * 1000))),
            host,
        ]

    # Linux/iputils.
    return [
        "ping",
        "-c",
        str(attempts),
        "-W",
        str(max(1, math.ceil(timeout))),
        host,
    ]


def ping_host(
    host: str,
    attempts: int,
    timeout: float,
) -> tuple[bool, str]:
    """Check ICMP reachability using the operating system ping tool."""
    ping_exe = shutil.which("ping")

    if not ping_exe:
        return False, "ping executable not found"

    command = build_ping_command(host, attempts, timeout)
    command[0] = ping_exe

    process_timeout = max(
        2.0,
        (attempts * timeout) + 2.0,
    )

    try:
        completed = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=process_timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return False, (
            f"ping process timed out after {process_timeout:.1f}s"
        )
    except OSError as exc:
        return False, f"ping failed: {exc}"

    if completed.returncode == 0:
        return True, "ICMP reply received"

    return False, f"ping exited with code {completed.returncode}"


def tcp_probe(
    host: str,
    port: int,
    timeout: float,
) -> tuple[bool, str]:
    """
    Check whether the configured service port accepts a TCP connection.

    socket.create_connection supports DNS, IPv4 and IPv6.
    """
    try:
        with socket.create_connection(
            (host, port),
            timeout=timeout,
        ):
            return True, f"TCP {port} accepted a connection"

    except socket.gaierror as exc:
        return False, f"DNS/address resolution failed: {exc}"

    except (TimeoutError, socket.timeout):
        return False, (
            f"TCP {port} timed out after {timeout:.1f}s"
        )

    except ConnectionRefusedError:
        return False, f"TCP {port} refused the connection"

    except OSError as exc:
        return False, f"TCP {port} unavailable: {exc}"


def probe_target(
    target: Target,
    mode: str,
    attempts: int,
    timeout: float,
) -> ProbeResult:
    """
    Check one target.

    Modes:
      auto:
          Check the actual TCP service first.
          If it fails, ping the host to distinguish SERVICE_DOWN from DOWN.

      ping:
          Original-script style ICMP-only check.

      tcp:
          Check only the configured TCP service.

      both:
          Require both ICMP and TCP to succeed.
    """
    started = time.monotonic()

    ping_ok: bool | None = None
    tcp_ok: bool | None = None
    messages: list[str] = []

    try:
        if mode == "ping":
            ping_ok, ping_detail = ping_host(
                target.host,
                attempts,
                timeout,
            )
            messages.append(ping_detail)

            ready = ping_ok
            status = "READY" if ready else "DOWN"

        elif mode == "tcp":
            tcp_ok, tcp_detail = tcp_probe(
                target.host,
                target.port,
                timeout,
            )
            messages.append(tcp_detail)

            ready = tcp_ok
            status = "READY" if ready else "SERVICE_DOWN"

        elif mode == "both":
            # These checks are independent, so run them in parallel.
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=2
            ) as pool:
                ping_future = pool.submit(
                    ping_host,
                    target.host,
                    attempts,
                    timeout,
                )
                tcp_future = pool.submit(
                    tcp_probe,
                    target.host,
                    target.port,
                    timeout,
                )

                ping_ok, ping_detail = ping_future.result()
                tcp_ok, tcp_detail = tcp_future.result()

            messages.extend(
                (
                    ping_detail,
                    tcp_detail,
                )
            )

            ready = bool(ping_ok and tcp_ok)

            if ready:
                status = "READY"
            elif ping_ok:
                status = "SERVICE_DOWN"
            else:
                status = "DOWN"

        else:
            # auto:
            # Service readiness is more useful than ping alone because many
            # hosts/firewalls intentionally block ICMP.
            tcp_ok, tcp_detail = tcp_probe(
                target.host,
                target.port,
                timeout,
            )
            messages.append(tcp_detail)

            if tcp_ok:
                ready = True
                status = "READY"

            else:
                ping_ok, ping_detail = ping_host(
                    target.host,
                    attempts,
                    timeout,
                )
                messages.append(ping_detail)

                ready = False

                if ping_ok:
                    status = "SERVICE_DOWN"
                else:
                    status = "DOWN"

        return ProbeResult(
            host=target.host,
            session=target.session,
            protocol=target.protocol,
            port=target.port,
            user=target.user,
            source_line=target.source_line,
            status=status,
            ready=ready,
            ping_ok=ping_ok,
            tcp_ok=tcp_ok,
            check_seconds=time.monotonic() - started,
            detail="; ".join(messages),
        )

    except Exception as exc:
        # A failure on one server should not abort the whole run.
        return ProbeResult(
            host=target.host,
            session=target.session,
            protocol=target.protocol,
            port=target.port,
            user=target.user,
            source_line=target.source_line,
            status="ERROR",
            ready=False,
            ping_ok=ping_ok,
            tcp_ok=tcp_ok,
            check_seconds=time.monotonic() - started,
            detail=f"{type(exc).__name__}: {exc}",
        )


def find_putty() -> str | None:
    """Find PuTTY in PATH or common Windows install locations."""
    direct = (
        shutil.which("putty")
        or shutil.which("putty.exe")
    )

    if direct:
        return direct

    candidates: list[Path] = []

    for environment_name in (
        "ProgramFiles",
        "ProgramFiles(x86)",
        "LOCALAPPDATA",
    ):
        root = os.environ.get(environment_name)

        if root:
            candidates.append(
                Path(root) / "PuTTY" / "putty.exe"
            )

    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)

    return None


def build_putty_command(
    target: Target,
    putty_exe: str,
) -> list[str]:
    """
    Load the saved PuTTY session.

    This preserves the original script's behavior.
    """
    return [
        putty_exe,
        "-load",
        target.session,
    ]


def build_ssh_command(target: Target) -> list[str]:
    """Build an OpenSSH client command."""
    ssh_exe = shutil.which("ssh")

    if not ssh_exe:
        raise FileNotFoundError(
            "OpenSSH 'ssh' executable was not found"
        )

    if target.protocol != "ssh":
        raise ValueError(
            f"OpenSSH cannot launch protocol "
            f"{target.protocol!r}; use PuTTY for this target"
        )

    command = [ssh_exe]

    if target.port != 22:
        command.extend(
            [
                "-p",
                str(target.port),
            ]
        )

    command.append(target.ssh_destination)

    return command


def format_command(command: Sequence[str]) -> str:
    """Format a command for readable logging only."""
    if os.name == "nt":
        return subprocess.list2cmdline(list(command))

    return shlex.join(command)


def linux_terminal_command(
    command: Sequence[str],
) -> list[str] | None:
    """
    Find a GUI terminal so multiple SSH sessions do not fight over
    the same controlling terminal.
    """
    candidates: tuple[
        tuple[str, list[str]],
        ...
    ] = (
        ("x-terminal-emulator", ["-e"]),
        ("gnome-terminal", ["--"]),
        ("konsole", ["-e"]),
        ("xterm", ["-e"]),
        ("kitty", []),
    )

    for executable, prefix in candidates:
        terminal = shutil.which(executable)

        if terminal:
            return [
                terminal,
                *prefix,
                *command,
            ]

    return None


def launch_ssh_in_terminal(
    command: Sequence[str],
) -> subprocess.Popen:
    """
    Launch SSH interactively.

    Linux:
        Opens a new terminal where possible.

    macOS:
        Opens a new Terminal.app session via osascript.

    Other:
        Falls back to the current terminal.
    """
    system = platform.system()

    if system == "Darwin":
        osascript = shutil.which("osascript")

        if osascript:
            shell_command = shlex.join(command)

            apple_string = (
                shell_command
                .replace("\\", "\\\\")
                .replace('"', '\\"')
            )

            return subprocess.Popen(
                [
                    osascript,
                    "-e",
                    (
                        'tell application "Terminal" '
                        'to do script '
                        f'"{apple_string}"'
                    ),
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

    if system == "Linux":
        terminal_command = linux_terminal_command(
            command
        )

        if terminal_command:
            return subprocess.Popen(
                terminal_command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )

    # Fallback. Interactive SSH inherits the terminal.
    return subprocess.Popen(list(command))


def select_client(
    requested: str,
    target: Target,
) -> str:
    """Resolve --client auto into a concrete client."""
    if requested != "auto":
        return requested

    if platform.system() == "Windows":
        if find_putty():
            return "putty"

        if target.protocol == "ssh" and shutil.which("ssh"):
            return "ssh"

        return "putty"

    return "ssh"


def launch_target(
    target: Target,
    client: str,
    dry_run: bool,
    logger: logging.Logger,
) -> tuple[bool, str]:
    """Launch the configured client for one ready target."""
    selected = select_client(
        client,
        target,
    )

    if selected == "none":
        return False, "launch disabled"

    try:
        if selected == "putty":
            putty = find_putty()

            if not putty:
                raise FileNotFoundError(
                    "PuTTY was not found in PATH or "
                    "common install locations"
                )

            command = build_putty_command(
                target,
                putty,
            )

        elif selected == "ssh":
            command = build_ssh_command(target)

        else:
            raise ValueError(
                f"unsupported client: {selected}"
            )

        rendered = format_command(command)

        if dry_run:
            logger.info(
                "[DRY-RUN] Would launch: %s",
                rendered,
            )
            return False, f"dry-run: {rendered}"

        if selected == "putty":
            kwargs: dict[str, object] = {
                "stdin": subprocess.DEVNULL,
                "stdout": subprocess.DEVNULL,
                "stderr": subprocess.DEVNULL,
            }

            if os.name == "nt":
                creationflags = 0

                creationflags |= getattr(
                    subprocess,
                    "CREATE_NEW_PROCESS_GROUP",
                    0,
                )

                creationflags |= getattr(
                    subprocess,
                    "DETACHED_PROCESS",
                    0,
                )

                kwargs["creationflags"] = creationflags

            else:
                kwargs["start_new_session"] = True

            subprocess.Popen(
                command,
                **kwargs,
            )

        else:
            launch_ssh_in_terminal(command)

        return True, rendered

    except (OSError, ValueError) as exc:
        return False, (
            f"{type(exc).__name__}: {exc}"
        )


def setup_logging(
    log_dir: Path,
    verbose: bool,
) -> tuple[logging.Logger, Path]:
    """Create a dated UTF-8 logfile plus console logging."""
    log_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    log_path = (
        log_dir
        / f"server_startup_{datetime.now():%Y-%m-%d}.log"
    )

    logger = logging.getLogger(
        "powerdown_startup"
    )

    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()
    logger.propagate = False

    file_handler = logging.FileHandler(
        log_path,
        encoding="utf-8",
    )

    file_handler.setLevel(logging.DEBUG)

    file_handler.setFormatter(
        logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )

    console_handler = logging.StreamHandler()

    console_handler.setLevel(
        logging.DEBUG
        if verbose
        else logging.INFO
    )

    console_handler.setFormatter(
        logging.Formatter(
            "%(levelname)-8s %(message)s"
        )
    )

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger, log_path


def write_json_summary(
    path: Path,
    results: Iterable[ProbeResult],
) -> None:
    """Write an automation-friendly JSON result file."""
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    payload = {
        "application": APP_NAME,
        "version": VERSION,
        "generated_at_utc": (
            datetime.now(timezone.utc).isoformat()
        ),
        "results": [
            asdict(result)
            for result in results
        ],
    }

    with path.open(
        "w",
        encoding="utf-8",
    ) as handle:
        json.dump(
            payload,
            handle,
            indent=2,
            ensure_ascii=False,
        )


def build_parser() -> argparse.ArgumentParser:
    """Create the command-line interface."""
    parser = argparse.ArgumentParser(
        description=(
            "Check servers concurrently and launch "
            "PuTTY/OpenSSH sessions for targets "
            "whose configured service is ready."
        ),
        formatter_class=(
            argparse.ArgumentDefaultsHelpFormatter
        ),
    )

    parser.add_argument(
        "-l",
        "--list",
        dest="list_file",
        type=Path,
        default=Path(DEFAULT_LIST_FILE),
        help="server list file",
    )

    parser.add_argument(
        "--log-dir",
        type=Path,
        default=Path("."),
        help="directory for dated log files",
    )

    parser.add_argument(
        "--probe",
        choices=(
            "auto",
            "ping",
            "tcp",
            "both",
        ),
        default="auto",
        help=(
            "readiness test; auto checks the "
            "service port first and uses ping "
            "only to diagnose failures"
        ),
    )

    parser.add_argument(
        "--attempts",
        type=int,
        default=DEFAULT_ATTEMPTS,
        help="ICMP requests used by ping checks",
    )

    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help="per-probe timeout in seconds",
    )

    parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help="maximum concurrent target checks",
    )

    parser.add_argument(
        "--client",
        choices=(
            "auto",
            "putty",
            "ssh",
            "none",
        ),
        default="auto",
        help="session client for ready targets",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "perform checks but print launch "
            "commands instead of starting clients"
        ),
    )

    parser.add_argument(
        "--summary-json",
        type=Path,
        help=(
            "also write a JSON result summary "
            "to this path"
        ),
    )

    parser.add_argument(
        "--fail-on-down",
        action="store_true",
        help=(
            "exit with status 2 if any target "
            "is not ready"
        ),
    )

    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="show additional diagnostics",
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {VERSION}",
    )

    return parser


def validate_args(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
) -> None:
    """Validate numeric CLI arguments."""
    if args.attempts < 1:
        parser.error(
            "--attempts must be >= 1"
        )

    if args.timeout <= 0:
        parser.error(
            "--timeout must be > 0"
        )

    if args.workers < 1:
        parser.error(
            "--workers must be >= 1"
        )


def main(
    argv: Sequence[str] | None = None,
) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    validate_args(
        parser,
        args,
    )

    try:
        targets = load_targets(
            args.list_file
        )

    except (OSError, ValueError) as exc:
        print(
            f"ERROR: {exc}",
            file=sys.stderr,
        )
        return 1

    try:
        logger, log_path = setup_logging(
            args.log_dir,
            args.verbose,
        )

    except OSError as exc:
        print(
            f"ERROR: could not initialize logging: {exc}",
            file=sys.stderr,
        )
        return 1

    worker_count = min(
        args.workers,
        len(targets),
    )

    logger.info(
        "%s v%s",
        APP_NAME,
        VERSION,
    )

    logger.info(
        (
            "Loaded %d target(s) from %s | "
            "probe=%s | workers=%d | client=%s"
        ),
        len(targets),
        args.list_file,
        args.probe,
        worker_count,
        args.client,
    )

    results: list[ProbeResult] = []

    try:
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=worker_count,
            thread_name_prefix="server-probe",
        ) as pool:

            futures = [
                pool.submit(
                    probe_target,
                    target,
                    args.probe,
                    args.attempts,
                    args.timeout,
                )
                for target in targets
            ]

            # Preserve startup_list.txt order while the actual checks
            # still execute concurrently in the worker pool.
            for target, future in zip(
                targets,
                futures,
            ):
                result = future.result()

                results.append(result)

                if result.ready:
                    logger.info(
                        (
                            "%-13s %-30s "
                            "port=%-5d | %s | %.2fs"
                        ),
                        result.status,
                        result.host,
                        result.port,
                        result.detail,
                        result.check_seconds,
                    )

                    launched, launch_detail = launch_target(
                        target=target,
                        client=args.client,
                        dry_run=args.dry_run,
                        logger=logger,
                    )

                    result.launched = launched
                    result.launch_detail = launch_detail

                    if launched:
                        logger.info(
                            "LAUNCHED      %-30s | %s",
                            result.host,
                            launch_detail,
                        )

                    elif args.client != "none":
                        if args.dry_run:
                            logger.info(
                                "NOT_LAUNCHED  %-30s | %s",
                                result.host,
                                launch_detail,
                            )
                        else:
                            logger.warning(
                                "NOT_LAUNCHED  %-30s | %s",
                                result.host,
                                launch_detail,
                            )

                else:
                    logger.warning(
                        (
                            "%-13s %-30s "
                            "port=%-5d | %s | %.2fs"
                        ),
                        result.status,
                        result.host,
                        result.port,
                        result.detail,
                        result.check_seconds,
                    )

    except KeyboardInterrupt:
        logger.warning(
            "Interrupted by user"
        )
        return 130

    except Exception:
        logger.exception(
            "Unexpected failure while processing targets"
        )
        return 1

    ready_count = sum(
        result.ready
        for result in results
    )

    not_ready_count = (
        len(results)
        - ready_count
    )

    launched_count = sum(
        result.launched
        for result in results
    )

    logger.info(
        (
            "Finished | ready=%d | "
            "not-ready=%d | launched=%d | "
            "log=%s"
        ),
        ready_count,
        not_ready_count,
        launched_count,
        log_path,
    )

    if args.summary_json:
        try:
            write_json_summary(
                args.summary_json,
                results,
            )

            logger.info(
                "JSON summary written to %s",
                args.summary_json,
            )

        except OSError as exc:
            logger.error(
                "Could not write JSON summary: %s",
                exc,
            )
            return 1

    if (
        args.fail_on_down
        and not_ready_count
    ):
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''

path = Path("/mnt/data/powerdown_startup.py")
path.write_text(script, encoding="utf-8")

print(f"Created: {path}")
print(f"Lines: {len(script.splitlines())}")
print(f"Bytes: {path.stat().st_size}")
