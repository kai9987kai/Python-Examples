#!/usr/bin/env python3
"""
work_connect.py

Connect/disconnect a Check Point Endpoint Connect VPN session, optionally open
PuTTY Connection Manager, then launch an RDP file.

Examples:
    python work_connect.py connect --username myusername
    python work_connect.py connect --username myusername --wait-host workpc --wait-port 3389
    python work_connect.py disconnect
    python work_connect.py connect --username myusername --dry-run
"""

import argparse
import getpass
import os
import socket
import subprocess
import sys
import time
from pathlib import Path


DEFAULT_VPN_EXE = (
    Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
    / "Checkpoint"
    / "Endpoint Connect"
    / "trac.exe"
)

DEFAULT_MSTSC_EXE = (
    Path(os.environ.get("WINDIR", r"C:\Windows"))
    / "System32"
    / "mstsc.exe"
)

DROPBOX_DIR = os.environ.get("DROPBOX") or os.environ.get("dropbox")
DEFAULT_RDP_FILE = (
    Path(DROPBOX_DIR) / "remote" / "workpc.rdp"
    if DROPBOX_DIR
    else None
)

DEFAULT_PUTTYCM_EXE = Path(r"C:\geektools\puttycm.exe")


def build_parser():
    parser = argparse.ArgumentParser(
        description="Connect to work VPN and launch remote desktop.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument(
        "--vpn-exe",
        type=Path,
        default=DEFAULT_VPN_EXE,
        help="Path to Check Point trac.exe",
    )
    parser.add_argument(
        "--mstsc-exe",
        type=Path,
        default=DEFAULT_MSTSC_EXE,
        help="Path to Microsoft Remote Desktop executable",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    connect = subparsers.add_parser(
        "connect",
        help="Connect VPN and launch configured work applications.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    connect.add_argument(
        "--username",
        default=os.environ.get("WORK_VPN_USERNAME"),
        help="VPN username. Defaults to WORK_VPN_USERNAME if set.",
    )
    connect.add_argument(
        "--password-env",
        metavar="VARIABLE",
        help=(
            "Read the password from an environment variable. "
            "Without this option, the password is requested securely."
        ),
    )
    connect.add_argument(
        "--rdp-file",
        type=Path,
        default=DEFAULT_RDP_FILE,
        help="Path to the .rdp connection file.",
    )
    connect.add_argument(
        "--puttycm-exe",
        type=Path,
        default=DEFAULT_PUTTYCM_EXE,
        help="Path to PuTTY Connection Manager.",
    )
    connect.add_argument(
        "--no-putty",
        action="store_true",
        help="Do not open PuTTY Connection Manager.",
    )
    connect.add_argument(
        "--delay",
        type=float,
        default=15,
        help="Seconds to wait after starting VPN before launching applications.",
    )
    connect.add_argument(
        "--wait-host",
        help="Optional host to test before opening RDP, e.g. workpc.company.local.",
    )
    connect.add_argument(
        "--wait-port",
        type=int,
        default=3389,
        help="TCP port used with --wait-host.",
    )
    connect.add_argument(
        "--timeout",
        type=float,
        default=60,
        help="Maximum seconds to wait for --wait-host.",
    )
    connect.add_argument(
        "--dry-run",
        action="store_true",
        help="Show intended actions without starting programs.",
    )

    subparsers.add_parser(
        "disconnect",
        help="Disconnect the Check Point VPN session.",
    )

    return parser


def require_file(path, label):
    if path is None:
        raise FileNotFoundError(
            f"{label} was not supplied. Set the relevant option explicitly."
        )

    if not path.is_file():
        raise FileNotFoundError(f"{label} not found: {path}")

    return path


def get_password(args):
    if args.password_env:
        password = os.environ.get(args.password_env)
        if not password:
            raise RuntimeError(
                f"Environment variable '{args.password_env}' is empty or missing."
            )
        return password

    password = getpass.getpass("VPN password: ")
    if not password:
        raise RuntimeError("No password entered.")

    return password


def wait_for_service(host, port, timeout):
    print(f"Waiting for {host}:{port} to become reachable...")

    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=3):
                print(f"{host}:{port} is reachable.")
                return
        except OSError:
            time.sleep(2)

    raise TimeoutError(
        f"Timed out after {timeout:.0f} seconds waiting for {host}:{port}."
    )


def launch(command, label):
    try:
        subprocess.Popen(command)
        print(f"Started {label}.")
    except OSError as exc:
        raise RuntimeError(f"Could not start {label}: {exc}") from exc


def connect(args):
    vpn_exe = require_file(args.vpn_exe, "VPN executable")
    mstsc_exe = require_file(args.mstsc_exe, "Remote Desktop executable")
    rdp_file = require_file(args.rdp_file, "RDP file")

    if not args.username:
        raise RuntimeError(
            "VPN username is required. Use --username or set WORK_VPN_USERNAME."
        )

    if args.delay < 0:
        raise ValueError("--delay cannot be negative.")

    if args.timeout <= 0:
        raise ValueError("--timeout must be greater than zero.")

    putty_exe = None
    if not args.no_putty:
        putty_exe = require_file(args.puttycm_exe, "PuTTY Connection Manager")

    if args.dry_run:
        print("Dry run — no applications will be launched.")
        print(f"VPN: {vpn_exe} connect -u {args.username} -p ********")
        print(f"RDP: {mstsc_exe} {rdp_file}")

        if putty_exe:
            print(f"PuTTY CM: {putty_exe}")

        if args.wait_host:
            print(f"Readiness check: {args.wait_host}:{args.wait_port}")

        return 0

    password = get_password(args)

    # Check Point Endpoint Connect uses this legacy command format.
    vpn_command = [
        str(vpn_exe),
        "connect",
        "-u",
        args.username,
        "-p",
        password,
    ]

    print("Starting VPN connection...")
    launch(vpn_command, "VPN client")

    if args.delay:
        print(f"Waiting {args.delay:g} seconds for VPN setup...")
        time.sleep(args.delay)

    if args.wait_host:
        wait_for_service(args.wait_host, args.wait_port, args.timeout)

    if putty_exe:
        launch([str(putty_exe)], "PuTTY Connection Manager")

    launch([str(mstsc_exe), str(rdp_file)], "Remote Desktop")

    return 0


def disconnect(args):
    vpn_exe = require_file(args.vpn_exe, "VPN executable")
    command = [str(vpn_exe), "disconnect"]

    print("Disconnecting VPN...")

    try:
        result = subprocess.run(command, check=False)
    except OSError as exc:
        raise RuntimeError(f"Could not start VPN client: {exc}") from exc

    if result.returncode == 0:
        print("VPN disconnect command completed.")
    else:
        print(f"VPN disconnect returned exit code {result.returncode}.")

    return result.returncode


def main():
    parser = build_parser()
    args = parser.parse_args()

    try:
        if args.command == "connect":
            return connect(args)

        if args.command == "disconnect":
            return disconnect(args)

        parser.error("Unknown command.")

    except (FileNotFoundError, RuntimeError, TimeoutError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
