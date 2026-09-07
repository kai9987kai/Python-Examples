#!/usr/bin/env python3
"""
serial_port_scanner.py
======================

Modern, cross-platform serial-port discovery and diagnostics using PySerial.

Features
--------
- Windows, Linux, macOS and other platforms supported by PySerial.
- Uses OS-native discovery via serial.tools.list_ports instead of guessing ports.
- Shows USB VID/PID, serial number, manufacturer, product, interface and HWID.
- Optional regex, VID and PID filtering.
- Optional active open/close probe to test whether a port can be opened.
- JSON output for scripts and APIs.
- Watch mode for hot-plug / unplug monitoring.
- Zero third-party dependencies beyond PySerial.
- Includes a compatibility ListAvailablePorts() function.

Install
-------
    python -m pip install --upgrade pyserial

Examples
--------
    python serial_port_scanner.py
    python serial_port_scanner.py --verbose
    python serial_port_scanner.py --json
    python serial_port_scanner.py --match "Arduino|CH340|CP210"
    python serial_port_scanner.py --vid 0x2341
    python serial_port_scanner.py --vid 2341 --pid 0043
    python serial_port_scanner.py --probe
    python serial_port_scanner.py --watch 1
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import asdict, dataclass
from typing import Iterable, Optional, Pattern, Sequence

try:
    import serial
    from serial import SerialException
    from serial.tools import list_ports
except ImportError as exc:
    raise SystemExit(
        "PySerial is not installed.\n"
        "Install it with:\n"
        "    python -m pip install --upgrade pyserial"
    ) from exc


@dataclass(frozen=True)
class PortRecord:
    """Normalized information about one serial port."""

    device: str
    name: Optional[str]
    description: Optional[str]
    hwid: Optional[str]

    vid: Optional[int]
    pid: Optional[int]
    serial_number: Optional[str]
    location: Optional[str]
    manufacturer: Optional[str]
    product: Optional[str]
    interface: Optional[str]

    transport: str
    accessible: Optional[bool] = None
    probe_error: Optional[str] = None

    @property
    def vid_hex(self) -> Optional[str]:
        return f"{self.vid:04X}" if self.vid is not None else None

    @property
    def pid_hex(self) -> Optional[str]:
        return f"{self.pid:04X}" if self.pid is not None else None

    @property
    def usb_id(self) -> Optional[str]:
        if self.vid is None or self.pid is None:
            return None
        return f"{self.vid:04X}:{self.pid:04X}"

    def to_dict(self) -> dict:
        data = asdict(self)
        data["vid_hex"] = self.vid_hex
        data["pid_hex"] = self.pid_hex
        data["usb_id"] = self.usb_id
        return data


def _clean(value: object) -> Optional[str]:
    """Convert a PySerial metadata value to a useful optional string."""
    if value is None:
        return None

    text = str(value).strip()
    if not text or text.lower() in {"n/a", "none", "unknown"}:
        return None

    return text


def _classify_transport(
    *,
    device: str,
    description: Optional[str],
    hwid: Optional[str],
    vid: Optional[int],
    pid: Optional[int],
) -> str:
    """
    Give a conservative transport/category hint.

    This is intentionally heuristic; it does not claim to identify the exact
    attached hardware.
    """
    blob = " ".join(
        part
        for part in (device, description or "", hwid or "")
        if part
    ).lower()

    if vid is not None or pid is not None or "usb" in blob:
        return "USB"

    if "bluetooth" in blob or "bth" in blob or "rfcomm" in blob:
        return "Bluetooth"

    if (
        "virtual" in blob
        or "com0com" in blob
        or "pty" in blob
        or "pseudo" in blob
    ):
        return "Virtual"

    return "Serial"


def _probe_port(
    device: str,
    *,
    baudrate: int,
    timeout: float,
) -> tuple[bool, Optional[str]]:
    """
    Try opening and immediately closing a serial port.

    Important:
        Opening some boards can toggle DTR/RTS and reset the target. Therefore
        probing is opt-in and never performed during ordinary discovery.
    """
    try:
        with serial.Serial(
            port=device,
            baudrate=baudrate,
            timeout=timeout,
            write_timeout=timeout,
        ):
            pass
        return True, None
    except (SerialException, OSError, ValueError) as exc:
        return False, f"{type(exc).__name__}: {exc}"


def _searchable_text(record: PortRecord) -> str:
    fields = (
        record.device,
        record.name,
        record.description,
        record.hwid,
        record.serial_number,
        record.location,
        record.manufacturer,
        record.product,
        record.interface,
        record.transport,
        record.usb_id,
    )
    return "\n".join(str(value) for value in fields if value is not None)


def discover_ports(
    *,
    include_links: bool = False,
    match: Optional[str] = None,
    vid: Optional[int] = None,
    pid: Optional[int] = None,
    probe: bool = False,
    baudrate: int = 115200,
    timeout: float = 0.20,
) -> list[PortRecord]:
    """
    Discover serial ports and return normalized PortRecord objects.

    Parameters
    ----------
    include_links:
        On supported POSIX systems, include symlinks that point to known ports.
    match:
        Optional case-insensitive regular expression applied across device
        name and metadata.
    vid / pid:
        Optional USB vendor/product ID filters.
    probe:
        If True, actively open and close each matched port.
    baudrate:
        Baud rate used only by the optional probe.
    timeout:
        Read/write timeout used only by the optional probe.
    """
    if baudrate <= 0:
        raise ValueError("baudrate must be greater than zero")

    if timeout < 0:
        raise ValueError("timeout cannot be negative")

    regex: Optional[Pattern[str]] = None
    if match:
        try:
            regex = re.compile(match, re.IGNORECASE)
        except re.error as exc:
            raise ValueError(f"invalid regular expression {match!r}: {exc}") from exc

    records: list[PortRecord] = []

    # PySerial ListPortInfo objects implement natural device ordering.
    for info in sorted(list_ports.comports(include_links=include_links)):
        device = _clean(getattr(info, "device", None))
        if not device:
            continue

        name = _clean(getattr(info, "name", None))
        description = _clean(getattr(info, "description", None))
        hwid = _clean(getattr(info, "hwid", None))

        info_vid = getattr(info, "vid", None)
        info_pid = getattr(info, "pid", None)

        record = PortRecord(
            device=device,
            name=name,
            description=description,
            hwid=hwid,
            vid=info_vid,
            pid=info_pid,
            serial_number=_clean(getattr(info, "serial_number", None)),
            location=_clean(getattr(info, "location", None)),
            manufacturer=_clean(getattr(info, "manufacturer", None)),
            product=_clean(getattr(info, "product", None)),
            interface=_clean(getattr(info, "interface", None)),
            transport=_classify_transport(
                device=device,
                description=description,
                hwid=hwid,
                vid=info_vid,
                pid=info_pid,
            ),
        )

        if vid is not None and record.vid != vid:
            continue

        if pid is not None and record.pid != pid:
            continue

        if regex is not None and regex.search(_searchable_text(record)) is None:
            continue

        if probe:
            accessible, probe_error = _probe_port(
                record.device,
                baudrate=baudrate,
                timeout=timeout,
            )
            record = PortRecord(
                **{
                    **asdict(record),
                    "accessible": accessible,
                    "probe_error": probe_error,
                }
            )

        records.append(record)

    return records


def list_available_ports(**kwargs) -> list[str]:
    """Return only device names/paths, e.g. ['COM3'] or ['/dev/ttyACM0']."""
    return [record.device for record in discover_ports(**kwargs)]


def ListAvailablePorts() -> list[str]:
    """
    Backwards-compatible replacement for the original function name.

    Unlike the old implementation, an empty result is represented as [] rather
    than integer 0 so the return type is always consistent.
    """
    return list_available_ports()


def _format_access(record: PortRecord) -> str:
    if record.accessible is True:
        return "yes"
    if record.accessible is False:
        return "no"
    return "-"


def _print_table(records: Sequence[PortRecord], *, verbose: bool) -> None:
    if not records:
        print("No serial ports detected.")
        return

    rows = []
    for record in records:
        rows.append(
            (
                record.device,
                record.transport,
                record.usb_id or "-",
                record.description or "-",
                _format_access(record),
            )
        )

    headers = ("DEVICE", "TYPE", "VID:PID", "DESCRIPTION", "OPENABLE")
    widths = [
        max(len(headers[index]), *(len(row[index]) for row in rows))
        for index in range(len(headers))
    ]

    def render_row(row: Iterable[str]) -> str:
        return "  ".join(
            value.ljust(widths[index])
            for index, value in enumerate(row)
        )

    print(render_row(headers))
    print(render_row(tuple("-" * width for width in widths)))

    for row in rows:
        print(render_row(row))

    if verbose:
        print()
        for index, record in enumerate(records, start=1):
            print(f"[{index}] {record.device}")
            details = (
                ("Name", record.name),
                ("Description", record.description),
                ("Transport", record.transport),
                ("VID", record.vid_hex),
                ("PID", record.pid_hex),
                ("Serial number", record.serial_number),
                ("Manufacturer", record.manufacturer),
                ("Product", record.product),
                ("Interface", record.interface),
                ("Location", record.location),
                ("HWID", record.hwid),
                ("Openable", _format_access(record)),
                ("Probe error", record.probe_error),
            )

            for label, value in details:
                if value is not None and value != "-":
                    print(f"    {label:14}: {value}")

            if index != len(records):
                print()


def _print_json(records: Sequence[PortRecord]) -> None:
    payload = {
        "count": len(records),
        "ports": [record.to_dict() for record in records],
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def _parse_usb_id(value: str) -> int:
    """
    Parse USB IDs flexibly.

    Accepted examples:
        0x2341
        2341
        9025

    Four-character strings are treated as hexadecimal because USB VID/PID
    values are conventionally written in hex. Other all-digit values are
    interpreted as decimal.
    """
    text = value.strip().lower()

    try:
        if text.startswith("0x"):
            number = int(text, 16)
        elif len(text) == 4:
            number = int(text, 16)
        else:
            number = int(text, 10)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"{value!r} is not a valid USB identifier"
        ) from exc

    if not 0 <= number <= 0xFFFF:
        raise argparse.ArgumentTypeError(
            "USB VID/PID must be between 0x0000 and 0xFFFF"
        )

    return number


def _snapshot(records: Sequence[PortRecord]) -> tuple:
    """Build a stable snapshot for watch-mode change detection."""
    return tuple(
        (
            record.device,
            record.description,
            record.hwid,
            record.vid,
            record.pid,
            record.serial_number,
            record.location,
            record.manufacturer,
            record.product,
            record.interface,
            record.accessible,
            record.probe_error,
        )
        for record in records
    )


def _scan_from_args(args: argparse.Namespace) -> list[PortRecord]:
    return discover_ports(
        include_links=args.include_links,
        match=args.match,
        vid=args.vid,
        pid=args.pid,
        probe=args.probe,
        baudrate=args.baud,
        timeout=args.timeout,
    )


def _display(records: Sequence[PortRecord], args: argparse.Namespace) -> None:
    if args.json:
        _print_json(records)
    else:
        _print_table(records, verbose=args.verbose)


def _watch(args: argparse.Namespace) -> int:
    previous: Optional[tuple] = None

    if args.probe:
        print(
            "Warning: --probe in watch mode repeatedly opens ports; some "
            "microcontroller boards may reset when a port is opened.",
            file=sys.stderr,
        )

    try:
        while True:
            records = _scan_from_args(args)
            current = _snapshot(records)

            if current != previous:
                timestamp = time.strftime("%Y-%m-%d %H:%M:%S")

                if args.json:
                    event = {
                        "timestamp": timestamp,
                        "count": len(records),
                        "ports": [record.to_dict() for record in records],
                    }
                    print(json.dumps(event, ensure_ascii=False), flush=True)
                else:
                    if previous is not None:
                        print()
                    print(f"=== {timestamp} ===")
                    _print_table(records, verbose=args.verbose)
                    sys.stdout.flush()

                previous = current

            time.sleep(args.watch)

    except KeyboardInterrupt:
        return 130


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Discover and inspect serial ports using PySerial's native "
            "cross-platform port enumeration."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument(
        "-m",
        "--match",
        metavar="REGEX",
        help=(
            "case-insensitive regex matched against device, description, HWID "
            "and other metadata"
        ),
    )
    parser.add_argument(
        "--vid",
        type=_parse_usb_id,
        help="filter by USB Vendor ID, e.g. 0x2341 or 2341",
    )
    parser.add_argument(
        "--pid",
        type=_parse_usb_id,
        help="filter by USB Product ID, e.g. 0x0043 or 0043",
    )
    parser.add_argument(
        "--include-links",
        action="store_true",
        help="include known /dev symlinks where supported",
    )
    parser.add_argument(
        "-p",
        "--probe",
        action="store_true",
        help=(
            "actively open/close matching ports to test accessibility; may "
            "reset some microcontroller boards"
        ),
    )
    parser.add_argument(
        "-b",
        "--baud",
        type=int,
        default=115200,
        help="baud rate used only by --probe",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=0.20,
        help="serial timeout in seconds used only by --probe",
    )
    parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="emit machine-readable JSON",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="show extended metadata",
    )
    parser.add_argument(
        "-w",
        "--watch",
        type=float,
        metavar="SECONDS",
        help="continuously rescan and print only when the port set changes",
    )
    parser.add_argument(
        "--require",
        action="store_true",
        help="return exit status 1 when no matching serial ports are found",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s 2.0 | PySerial {getattr(serial, '__version__', 'unknown')}",
    )

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.baud <= 0:
        parser.error("--baud must be greater than zero")

    if args.timeout < 0:
        parser.error("--timeout cannot be negative")

    if args.watch is not None:
        if args.watch <= 0:
            parser.error("--watch must be greater than zero seconds")
        return _watch(args)

    try:
        records = _scan_from_args(args)
    except ValueError as exc:
        parser.error(str(exc))

    _display(records, args)

    if args.require and not records:
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
