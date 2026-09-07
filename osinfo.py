#!/usr/bin/env python3
"""
osinfo_advanced.py

A modern, dependency-free, cross-platform system diagnostics utility.

Original concept:
    osinfo.py (2012-2016)

Modernised goals:
    - Python 3.8+ compatible
    - No third-party dependencies
    - Windows, Linux, macOS, BSD-friendly
    - Human-readable coloured output
    - JSON output for scripts/automation
    - Optional privacy redaction
    - Stable section ordering
    - Defensive feature detection instead of blindly calling platform APIs

Examples:
    python osinfo_advanced.py
    python osinfo_advanced.py --json
    python osinfo_advanced.py --json --output osinfo.json
    python osinfo_advanced.py --section system,python,hardware
    python osinfo_advanced.py --privacy --no-color
"""

from __future__ import annotations

import argparse
import ctypes
import datetime as _dt
import getpass
import json
import locale
import os
import platform
import shutil
import socket
import struct
import subprocess
import sys
import sysconfig
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


__version__ = "2.0.0"
SCRIPT_NAME = "osinfo_advanced.py"
UNKNOWN = "Unknown"


class Ansi:
    """ANSI formatting constants."""

    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    HEADER = "\033[95m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"


class Console:
    """Small terminal renderer with automatic colour detection."""

    def __init__(self, colour: bool = True) -> None:
        self.colour = bool(colour and sys.stdout.isatty() and not os.environ.get("NO_COLOR"))

        # Windows 10+ terminals generally support VT sequences. This call enables
        # processing when Python is hosted in a console where it is not already on.
        if self.colour and os.name == "nt":
            self._enable_windows_vt_mode()

    @staticmethod
    def _enable_windows_vt_mode() -> None:
        try:
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
            mode = ctypes.c_uint32()
            if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                kernel32.SetConsoleMode(handle, mode.value | 0x0004)
        except Exception:
            pass

    def style(self, text: str, *codes: str) -> str:
        if not self.colour:
            return text
        return "".join(codes) + text + Ansi.RESET


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------


def safe_call(func: Callable[..., Any], *args: Any, default: Any = UNKNOWN, **kwargs: Any) -> Any:
    """Call *func* and return *default* instead of propagating ordinary probe errors."""
    try:
        value = func(*args, **kwargs)
        if value is None or value == "" or value == () or value == [] or value == {}:
            return default
        return value
    except (OSError, AttributeError, ValueError, RuntimeError, TypeError, PermissionError):
        return default


def human_bytes(value: Optional[int]) -> str:
    if value is None or value < 0:
        return UNKNOWN
    units = ("B", "KiB", "MiB", "GiB", "TiB", "PiB")
    size = float(value)
    for unit in units:
        if abs(size) < 1024.0 or unit == units[-1]:
            return f"{size:.2f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024.0
    return f"{value} B"


def human_duration(seconds: Optional[float]) -> str:
    if seconds is None or seconds < 0:
        return UNKNOWN
    total = int(seconds)
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    parts: List[str] = []
    if days:
        parts.append(f"{days}d")
    if hours or days:
        parts.append(f"{hours}h")
    if minutes or hours or days:
        parts.append(f"{minutes}m")
    parts.append(f"{secs}s")
    return " ".join(parts)


def iso_local_now() -> str:
    return _dt.datetime.now().astimezone().isoformat(timespec="seconds")


def command_output(args: Sequence[str], timeout: float = 1.5) -> Optional[str]:
    """Run a small local OS query without invoking a shell."""
    try:
        completed = subprocess.run(
            list(args),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
        if completed.returncode == 0:
            value = completed.stdout.strip()
            return value or None
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def read_text(path: str, limit: int = 1_000_000) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read(limit)
    except (OSError, PermissionError):
        return None


def first_nonempty(values: Iterable[Any], default: Any = UNKNOWN) -> Any:
    for value in values:
        if value not in (None, "", (), [], {}, UNKNOWN):
            return value
    return default


def redact(value: Any, enabled: bool, replacement: str = "<redacted>") -> Any:
    return replacement if enabled and value not in (None, "", UNKNOWN) else value


def percent(used: int, total: int) -> float:
    return round((used / total) * 100.0, 2) if total else 0.0


# ---------------------------------------------------------------------------
# OS/platform probes
# ---------------------------------------------------------------------------


def parse_os_release_file() -> Dict[str, str]:
    """Fallback parser for Python versions lacking freedesktop_os_release()."""
    for filename in ("/etc/os-release", "/usr/lib/os-release"):
        text = read_text(filename)
        if not text:
            continue
        result: Dict[str, str] = {}
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, raw_value = line.split("=", 1)
            value = raw_value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                value = value[1:-1]
            value = value.replace(r"\$", "$").replace(r'\"', '"').replace(r"\\", "\\")
            result[key] = value
        if result:
            return result
    return {}


def linux_distribution_info() -> Dict[str, str]:
    if platform.system() != "Linux":
        return {}

    if hasattr(platform, "freedesktop_os_release"):
        try:
            return dict(platform.freedesktop_os_release())
        except OSError:
            pass
    return parse_os_release_file()


def detect_environment() -> List[str]:
    """Best-effort runtime environment identification."""
    tags: List[str] = []
    release = platform.release().lower()
    version = platform.version().lower()

    if "microsoft" in release or "microsoft" in version or os.environ.get("WSL_INTEROP"):
        tags.append("WSL")

    if os.path.exists("/.dockerenv"):
        tags.append("Docker/container")

    cgroup = read_text("/proc/1/cgroup") or ""
    cgroup_lower = cgroup.lower()
    container_markers = {
        "docker": "Docker/container",
        "kubepods": "Kubernetes/container",
        "containerd": "containerd/container",
        "lxc": "LXC/container",
        "podman": "Podman/container",
    }
    for marker, label in container_markers.items():
        if marker in cgroup_lower and label not in tags:
            tags.append(label)

    if os.environ.get("container") and "Container" not in tags:
        tags.append(f"Container ({os.environ['container']})")

    if os.environ.get("CI", "").lower() in {"1", "true", "yes"}:
        tags.append("CI")

    if sys.prefix != getattr(sys, "base_prefix", sys.prefix):
        tags.append("Python virtual environment")

    return tags or ["Native/undetected"]


def system_section(privacy: bool) -> OrderedDict[str, Any]:
    u = platform.uname()
    distro = linux_distribution_info()
    system = u.system or platform.system() or UNKNOWN

    data: OrderedDict[str, Any] = OrderedDict()
    data["os"] = system
    data["platform"] = safe_call(platform.platform, aliased=True, terse=False)
    data["hostname"] = redact(first_nonempty((u.node, socket.gethostname())), privacy)
    data["kernel_release"] = u.release or UNKNOWN
    data["kernel_version"] = u.version or UNKNOWN
    data["machine"] = u.machine or UNKNOWN
    data["environment"] = detect_environment()

    if system == "Linux":
        data["distribution"] = distro.get("PRETTY_NAME", UNKNOWN)
        data["distribution_id"] = distro.get("ID", UNKNOWN)
        data["distribution_version"] = distro.get("VERSION_ID", distro.get("VERSION", UNKNOWN))
        data["distribution_like"] = distro.get("ID_LIKE", UNKNOWN)
        libc = safe_call(platform.libc_ver, default=(UNKNOWN, UNKNOWN))
        if isinstance(libc, tuple):
            data["libc"] = " ".join(part for part in libc if part) or UNKNOWN

    elif system == "Windows":
        win = safe_call(platform.win32_ver, default=(UNKNOWN, UNKNOWN, UNKNOWN, UNKNOWN))
        if isinstance(win, tuple) and len(win) >= 4:
            data["windows_release"] = win[0] or UNKNOWN
            data["windows_version"] = win[1] or UNKNOWN
            data["service_pack"] = win[2] or "None"
            data["processor_type"] = win[3] or UNKNOWN
        if hasattr(platform, "win32_edition"):
            data["windows_edition"] = safe_call(platform.win32_edition)
        if hasattr(platform, "win32_is_iot"):
            data["windows_iot"] = safe_call(platform.win32_is_iot, default=False)

    elif system == "Darwin":
        mac = safe_call(platform.mac_ver, default=(UNKNOWN, (UNKNOWN, UNKNOWN, UNKNOWN), UNKNOWN))
        if isinstance(mac, tuple) and len(mac) >= 3:
            data["macos_release"] = mac[0] or UNKNOWN
            data["macos_machine"] = mac[2] or UNKNOWN

    return data


# ---------------------------------------------------------------------------
# Hardware probes
# ---------------------------------------------------------------------------


def cpu_model() -> str:
    system = platform.system()

    if system == "Windows":
        return first_nonempty(
            (
                os.environ.get("PROCESSOR_IDENTIFIER"),
                platform.processor(),
                platform.machine(),
            )
        )

    if system == "Darwin":
        return first_nonempty(
            (
                command_output(("sysctl", "-n", "machdep.cpu.brand_string")),
                command_output(("sysctl", "-n", "hw.model")),
                platform.processor(),
                platform.machine(),
            )
        )

    if system == "Linux":
        text = read_text("/proc/cpuinfo") or ""
        candidates = ("model name", "hardware", "processor")
        for candidate in candidates:
            for line in text.splitlines():
                if ":" in line:
                    key, value = line.split(":", 1)
                    if key.strip().lower() == candidate and value.strip():
                        return value.strip()

    return first_nonempty((platform.processor(), platform.machine()))


def memory_info() -> Tuple[Optional[int], Optional[int]]:
    """Return (total_bytes, available_bytes) without third-party packages."""
    # Linux exposes MemAvailable, which is a better estimate than simply counting
    # completely free physical pages because it includes reclaimable caches.
    if platform.system() == "Linux":
        meminfo = read_text("/proc/meminfo")
        if meminfo:
            parsed: Dict[str, int] = {}
            for line in meminfo.splitlines():
                if ":" not in line:
                    continue
                key, value = line.split(":", 1)
                pieces = value.strip().split()
                if pieces and pieces[0].isdigit():
                    parsed[key] = int(pieces[0]) * 1024
            total = parsed.get("MemTotal")
            available = parsed.get("MemAvailable", parsed.get("MemFree"))
            if total is not None:
                return total, available

    if os.name == "nt":
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_uint32),
                ("dwMemoryLoad", ctypes.c_uint32),
                ("ullTotalPhys", ctypes.c_uint64),
                ("ullAvailPhys", ctypes.c_uint64),
                ("ullTotalPageFile", ctypes.c_uint64),
                ("ullAvailPageFile", ctypes.c_uint64),
                ("ullTotalVirtual", ctypes.c_uint64),
                ("ullAvailVirtual", ctypes.c_uint64),
                ("ullAvailExtendedVirtual", ctypes.c_uint64),
            ]

        try:
            status = MEMORYSTATUSEX()
            status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return int(status.ullTotalPhys), int(status.ullAvailPhys)
        except Exception:
            return None, None

    # POSIX fast path via sysconf.
    try:
        page_size = os.sysconf("SC_PAGE_SIZE")
        phys_pages = os.sysconf("SC_PHYS_PAGES")
        total = int(page_size * phys_pages)
        available: Optional[int] = None
        try:
            avail_pages = os.sysconf("SC_AVPHYS_PAGES")
            available = int(page_size * avail_pages)
        except (ValueError, OSError, AttributeError):
            pass
        return total, available
    except (ValueError, OSError, AttributeError):
        pass

    return None, None


def hardware_section() -> OrderedDict[str, Any]:
    total_memory, available_memory = memory_info()
    logical_cpus = os.cpu_count()
    pointer_bits = struct.calcsize("P") * 8
    arch = safe_call(platform.architecture, default=(f"{pointer_bits}bit", UNKNOWN))

    data: OrderedDict[str, Any] = OrderedDict()
    data["cpu_model"] = cpu_model()
    data["logical_cpu_count"] = logical_cpus if logical_cpus is not None else UNKNOWN
    data["machine_architecture"] = platform.machine() or UNKNOWN
    data["interpreter_pointer_bits"] = pointer_bits
    data["executable_architecture"] = arch
    data["byte_order"] = sys.byteorder
    data["memory_total_bytes"] = total_memory if total_memory is not None else UNKNOWN
    data["memory_total"] = human_bytes(total_memory)
    data["memory_available_bytes"] = available_memory if available_memory is not None else UNKNOWN
    data["memory_available"] = human_bytes(available_memory)
    if total_memory is not None and available_memory is not None and total_memory > 0:
        data["memory_used_percent_estimate"] = round((1.0 - available_memory / total_memory) * 100.0, 2)

    if hasattr(os, "getloadavg"):
        try:
            one, five, fifteen = os.getloadavg()
            data["load_average_1m"] = round(one, 3)
            data["load_average_5m"] = round(five, 3)
            data["load_average_15m"] = round(fifteen, 3)
        except OSError:
            pass

    return data


# ---------------------------------------------------------------------------
# Python/runtime probes
# ---------------------------------------------------------------------------


def python_section(privacy: bool) -> OrderedDict[str, Any]:
    build = safe_call(platform.python_build, default=(UNKNOWN, UNKNOWN))
    compiler = safe_call(platform.python_compiler)
    implementation = platform.python_implementation()

    try:
        preferred_encoding = locale.getencoding()  # Python 3.11+
    except AttributeError:
        preferred_encoding = locale.getpreferredencoding(False)

    data: OrderedDict[str, Any] = OrderedDict()
    data["version"] = platform.python_version()
    data["implementation"] = implementation
    data["compiler"] = compiler
    data["build"] = build
    data["executable"] = redact(sys.executable or UNKNOWN, privacy)
    data["sys_platform"] = sys.platform
    data["sysconfig_platform"] = safe_call(sysconfig.get_platform)
    data["cache_tag"] = getattr(sys.implementation, "cache_tag", UNKNOWN) or UNKNOWN
    data["filesystem_encoding"] = sys.getfilesystemencoding()
    data["default_encoding"] = sys.getdefaultencoding()
    data["preferred_locale_encoding"] = preferred_encoding
    data["utf8_mode"] = bool(getattr(sys.flags, "utf8_mode", 0))
    data["optimization_level"] = getattr(sys.flags, "optimize", 0)
    data["debug_build"] = bool(getattr(sys, "gettotalrefcount", None))
    data["virtual_environment"] = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    data["prefix"] = redact(sys.prefix, privacy)
    data["base_prefix"] = redact(getattr(sys, "base_prefix", sys.prefix), privacy)
    return data


def uptime_seconds() -> Optional[float]:
    system = platform.system()

    if system == "Linux":
        text = read_text("/proc/uptime", limit=256)
        if text:
            try:
                return float(text.split()[0])
            except (ValueError, IndexError):
                pass

    if system == "Windows":
        try:
            ctypes.windll.kernel32.GetTickCount64.restype = ctypes.c_ulonglong
            return ctypes.windll.kernel32.GetTickCount64() / 1000.0
        except Exception:
            pass

    if system in {"Darwin", "FreeBSD", "OpenBSD", "NetBSD"}:
        raw = command_output(("sysctl", "-n", "kern.boottime"))
        if raw:
            # Common formats include: { sec = 1234567890, usec = 0 } ...
            import re

            match = re.search(r"sec\s*=\s*(\d+)", raw)
            if not match:
                match = re.search(r"^(\d+)", raw)
            if match:
                try:
                    boot_epoch = int(match.group(1))
                    return max(0.0, time.time() - boot_epoch)
                except ValueError:
                    pass

    return None


def runtime_section(privacy: bool) -> OrderedDict[str, Any]:
    uptime = uptime_seconds()
    username = safe_call(getpass.getuser)
    home = safe_call(lambda: str(Path.home()))

    data: OrderedDict[str, Any] = OrderedDict()
    data["collected_at"] = iso_local_now()
    data["process_id"] = os.getpid()
    data["parent_process_id"] = safe_call(os.getppid) if hasattr(os, "getppid") else UNKNOWN
    data["user"] = redact(username, privacy)
    data["home"] = redact(home, privacy)
    data["current_working_directory"] = redact(safe_call(os.getcwd), privacy)
    data["uptime_seconds"] = round(uptime, 2) if uptime is not None else UNKNOWN
    data["uptime"] = human_duration(uptime)
    data["timezone"] = _dt.datetime.now().astimezone().tzname() or UNKNOWN
    data["timezone_offset"] = _dt.datetime.now().astimezone().strftime("%z") or UNKNOWN
    return data


# ---------------------------------------------------------------------------
# Storage/network probes
# ---------------------------------------------------------------------------


def storage_section() -> OrderedDict[str, Any]:
    anchor = Path.cwd().anchor or os.path.sep
    try:
        usage = shutil.disk_usage(anchor)
        used = usage.total - usage.free
        return OrderedDict(
            (
                ("path", anchor),
                ("total_bytes", usage.total),
                ("total", human_bytes(usage.total)),
                ("used_bytes", used),
                ("used", human_bytes(used)),
                ("free_bytes", usage.free),
                ("free", human_bytes(usage.free)),
                ("used_percent", percent(used, usage.total)),
            )
        )
    except OSError:
        return OrderedDict((("path", anchor), ("status", "Unavailable")))


def local_addresses() -> List[str]:
    addresses: set[str] = set()
    hostnames = {socket.gethostname(), platform.node()}
    for hostname in filter(None, hostnames):
        try:
            for result in socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP):
                address = result[4][0]
                if address:
                    addresses.add(address)
        except socket.gaierror:
            continue
    return sorted(addresses, key=lambda value: (":" in value, value))


def network_section(privacy: bool) -> OrderedDict[str, Any]:
    hostname = safe_call(socket.gethostname)
    fqdn = safe_call(socket.getfqdn)
    addresses = local_addresses()

    data: OrderedDict[str, Any] = OrderedDict()
    data["hostname"] = redact(hostname, privacy)
    data["fqdn"] = redact(fqdn, privacy)
    data["local_addresses"] = ["<redacted>"] if privacy and addresses else addresses
    data["ipv4_count"] = sum(1 for addr in addresses if ":" not in addr)
    data["ipv6_count"] = sum(1 for addr in addresses if ":" in addr)
    data["has_ipv6_support"] = bool(socket.has_ipv6)
    return data


# ---------------------------------------------------------------------------
# Report assembly/rendering
# ---------------------------------------------------------------------------


SECTION_BUILDERS: "OrderedDict[str, Callable[[bool], OrderedDict[str, Any]]]" = OrderedDict(
    (
        ("system", system_section),
        ("hardware", lambda privacy: hardware_section()),
        ("python", python_section),
        ("storage", lambda privacy: storage_section()),
        ("network", network_section),
        ("runtime", runtime_section),
    )
)


def build_report(sections: Sequence[str], privacy: bool) -> OrderedDict[str, Any]:
    report: OrderedDict[str, Any] = OrderedDict()
    report["schema_version"] = 1
    report["tool"] = OrderedDict((("name", SCRIPT_NAME), ("version", __version__)))

    for section in sections:
        builder = SECTION_BUILDERS[section]
        report[section] = builder(privacy)
    return report


def display_value(value: Any) -> str:
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, (tuple, list)):
        return ", ".join(display_value(item) for item in value) if value else "None"
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def render_text(report: Mapping[str, Any], console: Console, compact: bool = False) -> str:
    lines: List[str] = []
    title = f"OSINFO {report['tool']['version']} — System Diagnostics"
    lines.append(console.style(title, Ansi.BOLD, Ansi.CYAN))
    lines.append(console.style("=" * len(title), Ansi.DIM))

    for section_name, section_data in report.items():
        if section_name in {"schema_version", "tool"}:
            continue
        if not isinstance(section_data, Mapping):
            continue

        if not compact:
            lines.append("")
        lines.append(console.style(f"[{section_name.upper()}]", Ansi.BOLD, Ansi.HEADER))

        max_key = max((len(str(key)) for key in section_data), default=0)
        for key, value in section_data.items():
            key_text = str(key).replace("_", " ").title()
            if compact:
                lines.append(f"{key_text}: {display_value(value)}")
            else:
                padded = key_text.ljust(max_key + 2)
                lines.append(f"  {console.style(padded, Ansi.BLUE)} {console.style(display_value(value), Ansi.BOLD)}")

    return "\n".join(lines)


def parse_sections(raw: Optional[str], parser: argparse.ArgumentParser) -> List[str]:
    if not raw:
        return list(SECTION_BUILDERS.keys())

    requested = [part.strip().lower() for part in raw.split(",") if part.strip()]
    unknown = [name for name in requested if name not in SECTION_BUILDERS]
    if unknown:
        parser.error(
            "unknown section(s): "
            + ", ".join(unknown)
            + ". Valid sections: "
            + ", ".join(SECTION_BUILDERS.keys())
        )

    # De-duplicate while preserving the user-requested order.
    return list(dict.fromkeys(requested))


def write_output(path: str, content: str) -> None:
    output_path = Path(path).expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content + ("" if content.endswith("\n") else "\n"), encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=SCRIPT_NAME,
        description="Cross-platform operating-system, hardware and Python runtime diagnostics.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python osinfo_advanced.py\n"
            "  python osinfo_advanced.py --json\n"
            "  python osinfo_advanced.py --section system,python\n"
            "  python osinfo_advanced.py --privacy --output report.txt\n"
        ),
    )
    parser.add_argument("--json", action="store_true", help="emit JSON instead of formatted text")
    parser.add_argument("--pretty", action="store_true", help="pretty-print JSON with indentation")
    parser.add_argument("--output", "-o", metavar="FILE", help="write the report to FILE as well as stdout")
    parser.add_argument(
        "--section",
        metavar="LIST",
        help="comma-separated sections: " + ",".join(SECTION_BUILDERS.keys()),
    )
    parser.add_argument("--privacy", action="store_true", help="redact hostname, username, paths and local IP addresses")
    parser.add_argument("--no-color", action="store_true", help="disable ANSI colours")
    parser.add_argument("--compact", action="store_true", help="reduce whitespace in text mode")
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="invalidate platform-module caches when supported by this Python version",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.refresh and hasattr(platform, "invalidate_caches"):
        try:
            platform.invalidate_caches()
        except Exception:
            pass

    sections = parse_sections(args.section, parser)
    report = build_report(sections, privacy=args.privacy)

    if args.json:
        indent = 2 if args.pretty else None
        content = json.dumps(report, ensure_ascii=False, indent=indent, sort_keys=False)
    else:
        console = Console(colour=not args.no_color)
        content = render_text(report, console=console, compact=args.compact)

    print(content)

    if args.output:
        try:
            # Strip ANSI sequences from file output when text mode is used.
            if not args.json:
                import re

                file_content = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", content)
            else:
                file_content = content
            write_output(args.output, file_content)
        except OSError as exc:
            print(f"{SCRIPT_NAME}: could not write {args.output!r}: {exc}", file=sys.stderr)
            return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
