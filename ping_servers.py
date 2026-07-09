#!/usr/bin/env python3
"""
Advanced Ping Server Tool
-------------------------

A safer, modern rewrite of the old ping_servers.py script.

Features:
- GUI mode with Tkinter: choose app group/site or browse a server file
- CLI mode for automation
- Cross-platform ping on Windows/Linux/macOS
- No shell=True for ping commands
- Concurrent scanning for speed
- DNS lookup
- Optional TCP port checks, e.g. 22,80,443
- TXT, CSV, and HTML reports
- Reads legacy config files named: <appgroup>_servers_<site>.txt
- Uses environment variables if available:
    my_config = default config directory
    logs      = default log/output directory
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import html
import os
import platform
import queue
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
except Exception:  # Tkinter may not exist on minimal servers.
    tk = None
    filedialog = None
    messagebox = None
    ttk = None


DEFAULT_COUNT = 2
DEFAULT_TIMEOUT = 2.0
DEFAULT_WORKERS = 20


@dataclass
class ScanResult:
    host: str
    ip_addresses: list[str] = field(default_factory=list)
    ping_ok: bool = False
    ping_ms: float | None = None
    ports: dict[int, bool] = field(default_factory=dict)
    error: str = ""

    @property
    def status(self) -> str:
        if self.ping_ok:
            return "ALIVE"
        if any(self.ports.values()):
            return "PORT OPEN"
        return "DOWN"

    @property
    def ip_text(self) -> str:
        return ", ".join(self.ip_addresses) if self.ip_addresses else "N/A"

    @property
    def ping_text(self) -> str:
        if self.ping_ok and self.ping_ms is not None:
            return f"OK ({self.ping_ms:.0f} ms)"
        if self.ping_ok:
            return "OK"
        return "No response"

    @property
    def ports_text(self) -> str:
        if not self.ports:
            return "Not checked"
        parts = []
        for port, is_open in sorted(self.ports.items()):
            parts.append(f"{port}:{'open' if is_open else 'closed'}")
        return ", ".join(parts)


def default_config_dir() -> Path:
    return Path(os.getenv("my_config") or "config").expanduser().resolve()


def default_log_dir() -> Path:
    return Path(os.getenv("logs") or "logs").expanduser().resolve()


def legacy_config_path(appgroup: str, site: str, config_dir: Path | None = None) -> Path:
    config_dir = config_dir or default_config_dir()
    return config_dir / f"{appgroup}_servers_{site}.txt"


def read_servers(config_file: Path) -> list[str]:
    if not config_file.exists():
        raise FileNotFoundError(f"Server file not found: {config_file}")

    servers: list[str] = []
    seen: set[str] = set()

    with config_file.open("r", encoding="utf-8") as fh:
        for line in fh:
            clean = line.strip()
            if not clean or clean.startswith("#"):
                continue
            # Allow inline comments: server01 # production host
            clean = clean.split("#", 1)[0].strip()
            if clean and clean not in seen:
                seen.add(clean)
                servers.append(clean)

    if not servers:
        raise ValueError(f"No servers found in: {config_file}")

    return servers


def parse_ports(raw: str | None) -> list[int]:
    if not raw:
        return []

    ports: list[int] = []
    for item in raw.replace(" ", "").split(","):
        if not item:
            continue
        if "-" in item:
            start_s, end_s = item.split("-", 1)
            start, end = int(start_s), int(end_s)
            if start > end:
                start, end = end, start
            ports.extend(range(start, end + 1))
        else:
            ports.append(int(item))

    unique_ports = sorted(set(ports))
    for port in unique_ports:
        if port < 1 or port > 65535:
            raise ValueError(f"Invalid port: {port}. Ports must be 1-65535.")
    return unique_ports


def ping_command(host: str, count: int, timeout: float) -> list[str]:
    system = platform.system().lower()

    if "windows" in system:
        # -n count, -w timeout in milliseconds
        return ["ping", "-n", str(count), "-w", str(int(timeout * 1000)), host]

    if "darwin" in system:
        # macOS: -c count, -W timeout in milliseconds
        return ["ping", "-c", str(count), "-W", str(int(timeout * 1000)), host]

    # Linux and most POSIX: -c count, -W timeout in seconds
    return ["ping", "-c", str(count), "-W", str(max(1, int(timeout))), host]


def resolve_host(host: str) -> tuple[list[str], str]:
    try:
        _name, _aliases, addresses = socket.gethostbyname_ex(host)
        return sorted(set(addresses)), ""
    except socket.gaierror as exc:
        return [], f"DNS failed: {exc}"


def ping_host(host: str, count: int = DEFAULT_COUNT, timeout: float = DEFAULT_TIMEOUT) -> tuple[bool, float | None, str]:
    command = ping_command(host, count, timeout)
    started = time.perf_counter()

    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=max(timeout * count + 2, 3),
            check=False,
        )
    except FileNotFoundError:
        return False, None, "Ping command not found on this system."
    except subprocess.TimeoutExpired:
        elapsed_ms = (time.perf_counter() - started) * 1000
        return False, elapsed_ms, "Ping timed out."
    except Exception as exc:
        return False, None, f"Ping error: {exc}"

    elapsed_ms = (time.perf_counter() - started) * 1000
    output = f"{completed.stdout}\n{completed.stderr}".strip()

    if completed.returncode == 0:
        return True, elapsed_ms, ""

    useful_error = "No ping response."
    if output:
        useful_error = output.splitlines()[-1][:250]
    return False, elapsed_ms, useful_error


def check_tcp_port(host: str, port: int, timeout: float = DEFAULT_TIMEOUT) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def scan_one_server(host: str, ports: Iterable[int], count: int, timeout: float) -> ScanResult:
    result = ScanResult(host=host)

    addresses, dns_error = resolve_host(host)
    result.ip_addresses = addresses

    ping_ok, ping_ms, ping_error = ping_host(host, count=count, timeout=timeout)
    result.ping_ok = ping_ok
    result.ping_ms = ping_ms

    for port in ports:
        result.ports[port] = check_tcp_port(host, port, timeout=timeout)

    errors = [err for err in (dns_error, ping_error) if err]
    result.error = " | ".join(errors)
    return result


def scan_servers(
    servers: list[str],
    ports: Iterable[int],
    count: int = DEFAULT_COUNT,
    timeout: float = DEFAULT_TIMEOUT,
    workers: int = DEFAULT_WORKERS,
    progress_callback: Callable[[int, int, ScanResult], None] | None = None,
) -> list[ScanResult]:
    results: list[ScanResult] = []
    total = len(servers)
    done = 0

    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        future_map = {
            executor.submit(scan_one_server, server, ports, count, timeout): server
            for server in servers
        }

        for future in as_completed(future_map):
            done += 1
            try:
                result = future.result()
            except Exception as exc:
                result = ScanResult(host=future_map[future], error=str(exc))
            results.append(result)

            if progress_callback:
                progress_callback(done, total, result)

    results.sort(key=lambda r: (r.status != "DOWN", r.host.lower()), reverse=True)
    return results


def make_report_base(appgroup: str, site: str, log_dir: Path) -> Path:
    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_app = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in appgroup)
    safe_site = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in site)
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / f"ping_{safe_app}_{safe_site}_{timestamp}"


def write_txt_report(results: list[ScanResult], path: Path) -> None:
    with path.open("w", encoding="utf-8") as fh:
        fh.write("Advanced Ping Server Report\n")
        fh.write("=" * 80 + "\n")
        fh.write(f"Created: {dt.datetime.now().isoformat(timespec='seconds')}\n")
        fh.write(f"Total servers: {len(results)}\n\n")

        for result in results:
            fh.write(f"{result.host}\n")
            fh.write(f"  Status : {result.status}\n")
            fh.write(f"  IPs    : {result.ip_text}\n")
            fh.write(f"  Ping   : {result.ping_text}\n")
            fh.write(f"  Ports  : {result.ports_text}\n")
            if result.error:
                fh.write(f"  Notes  : {result.error}\n")
            fh.write("\n")


def write_csv_report(results: list[ScanResult], path: Path) -> None:
    all_ports = sorted({port for result in results for port in result.ports})

    with path.open("w", encoding="utf-8", newline="") as fh:
        fieldnames = ["host", "status", "ip_addresses", "ping_ok", "ping_ms", "ports", "error"]
        fieldnames.extend(f"port_{port}" for port in all_ports)

        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()

        for result in results:
            row = {
                "host": result.host,
                "status": result.status,
                "ip_addresses": result.ip_text,
                "ping_ok": result.ping_ok,
                "ping_ms": "" if result.ping_ms is None else f"{result.ping_ms:.2f}",
                "ports": result.ports_text,
                "error": result.error,
            }
            for port in all_ports:
                state = result.ports.get(port)
                row[f"port_{port}"] = "" if state is None else ("open" if state else "closed")
            writer.writerow(row)


def write_html_report(results: list[ScanResult], path: Path) -> None:
    rows = []
    for result in results:
        css_class = {
            "ALIVE": "alive",
            "PORT OPEN": "port-open",
            "DOWN": "down",
        }.get(result.status, "")
        rows.append(
            "<tr class='{css}'>"
            "<td>{host}</td>"
            "<td>{status}</td>"
            "<td>{ips}</td>"
            "<td>{ping}</td>"
            "<td>{ports}</td>"
            "<td>{error}</td>"
            "</tr>".format(
                css=css_class,
                host=html.escape(result.host),
                status=html.escape(result.status),
                ips=html.escape(result.ip_text),
                ping=html.escape(result.ping_text),
                ports=html.escape(result.ports_text),
                error=html.escape(result.error),
            )
        )

    created = dt.datetime.now().isoformat(timespec="seconds")
    total = len(results)
    alive = sum(1 for r in results if r.ping_ok)
    down = sum(1 for r in results if r.status == "DOWN")

    document = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Advanced Ping Server Report</title>
<style>
body {{
    font-family: Arial, sans-serif;
    margin: 24px;
    background: #f7f7f7;
}}
h1 {{ margin-bottom: 4px; }}
.summary {{
    display: flex;
    gap: 12px;
    margin: 18px 0;
}}
.card {{
    background: white;
    border-radius: 12px;
    padding: 14px 18px;
    box-shadow: 0 1px 8px rgba(0,0,0,0.08);
}}
table {{
    border-collapse: collapse;
    width: 100%;
    background: white;
    box-shadow: 0 1px 8px rgba(0,0,0,0.08);
}}
th, td {{
    padding: 10px;
    border-bottom: 1px solid #ddd;
    text-align: left;
    vertical-align: top;
}}
th {{ background: #222; color: white; }}
tr.alive td:first-child {{ border-left: 6px solid #2e7d32; }}
tr.port-open td:first-child {{ border-left: 6px solid #f9a825; }}
tr.down td:first-child {{ border-left: 6px solid #c62828; }}
</style>
</head>
<body>
<h1>Advanced Ping Server Report</h1>
<p>Created: {html.escape(created)}</p>
<div class="summary">
  <div class="card"><strong>Total</strong><br>{total}</div>
  <div class="card"><strong>Ping Alive</strong><br>{alive}</div>
  <div class="card"><strong>Down</strong><br>{down}</div>
</div>
<table>
<thead>
<tr>
<th>Host</th>
<th>Status</th>
<th>IP Address</th>
<th>Ping</th>
<th>Ports</th>
<th>Notes</th>
</tr>
</thead>
<tbody>
{''.join(rows)}
</tbody>
</table>
</body>
</html>
"""
    path.write_text(document, encoding="utf-8")


def save_reports(results: list[ScanResult], appgroup: str, site: str, log_dir: Path) -> dict[str, Path]:
    base = make_report_base(appgroup, site, log_dir)

    paths = {
        "txt": base.with_suffix(".log"),
        "csv": base.with_suffix(".csv"),
        "html": base.with_suffix(".html"),
    }

    write_txt_report(results, paths["txt"])
    write_csv_report(results, paths["csv"])
    write_html_report(results, paths["html"])

    return paths


def run_cli(args: argparse.Namespace) -> int:
    config_dir = Path(args.config_dir).expanduser().resolve() if args.config_dir else default_config_dir()
    log_dir = Path(args.log_dir).expanduser().resolve() if args.log_dir else default_log_dir()
    config_file = Path(args.server_file).expanduser().resolve() if args.server_file else legacy_config_path(args.appgroup, args.site, config_dir)

    ports = parse_ports(args.ports)
    servers = read_servers(config_file)

    print(f"Loaded {len(servers)} server(s) from: {config_file}")
    if ports:
        print(f"Checking TCP ports: {', '.join(map(str, ports))}")
    print("Scanning...\n")

    def progress(done: int, total: int, result: ScanResult) -> None:
        print(f"[{done:>3}/{total:<3}] {result.host:<35} {result.status:<10} {result.ping_text}")

    results = scan_servers(
        servers=servers,
        ports=ports,
        count=args.count,
        timeout=args.timeout,
        workers=args.workers,
        progress_callback=progress,
    )

    paths = save_reports(results, args.appgroup, args.site, log_dir)

    print("\nReports created:")
    for kind, path in paths.items():
        print(f"  {kind.upper():<4} {path}")

    if args.open_html:
        webbrowser.open(paths["html"].as_uri())

    return 0


class PingServerGUI:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Advanced Ping Server Tool")
        self.root.geometry("1050x680")

        self.event_queue: queue.Queue = queue.Queue()
        self.scan_thread: threading.Thread | None = None
        self.latest_results: list[ScanResult] = []
        self.latest_report_paths: dict[str, Path] = {}

        self.appgroup_var = tk.StringVar(value="dms")
        self.site_var = tk.StringVar(value="155")
        self.config_dir_var = tk.StringVar(value=str(default_config_dir()))
        self.server_file_var = tk.StringVar(value="")
        self.log_dir_var = tk.StringVar(value=str(default_log_dir()))
        self.ports_var = tk.StringVar(value="22,80,443")
        self.count_var = tk.IntVar(value=DEFAULT_COUNT)
        self.timeout_var = tk.DoubleVar(value=DEFAULT_TIMEOUT)
        self.workers_var = tk.IntVar(value=DEFAULT_WORKERS)
        self.status_var = tk.StringVar(value="Ready.")

        self._build_layout()
        self._poll_queue()

    def _build_layout(self) -> None:
        padding = {"padx": 8, "pady": 5}

        frame = ttk.Frame(self.root, padding=10)
        frame.pack(fill="both", expand=True)

        input_frame = ttk.LabelFrame(frame, text="Scan settings", padding=10)
        input_frame.pack(fill="x", pady=(0, 10))

        ttk.Label(input_frame, text="App group").grid(row=0, column=0, sticky="w", **padding)
        ttk.Entry(input_frame, textvariable=self.appgroup_var, width=16).grid(row=0, column=1, sticky="w", **padding)

        ttk.Label(input_frame, text="Site").grid(row=0, column=2, sticky="w", **padding)
        ttk.Entry(input_frame, textvariable=self.site_var, width=16).grid(row=0, column=3, sticky="w", **padding)

        ttk.Label(input_frame, text="Ports").grid(row=0, column=4, sticky="w", **padding)
        ttk.Entry(input_frame, textvariable=self.ports_var, width=22).grid(row=0, column=5, sticky="w", **padding)

        ttk.Label(input_frame, text="Ping count").grid(row=1, column=0, sticky="w", **padding)
        ttk.Spinbox(input_frame, from_=1, to=10, textvariable=self.count_var, width=8).grid(row=1, column=1, sticky="w", **padding)

        ttk.Label(input_frame, text="Timeout seconds").grid(row=1, column=2, sticky="w", **padding)
        ttk.Spinbox(input_frame, from_=0.5, to=20.0, increment=0.5, textvariable=self.timeout_var, width=8).grid(row=1, column=3, sticky="w", **padding)

        ttk.Label(input_frame, text="Workers").grid(row=1, column=4, sticky="w", **padding)
        ttk.Spinbox(input_frame, from_=1, to=100, textvariable=self.workers_var, width=8).grid(row=1, column=5, sticky="w", **padding)

        ttk.Label(input_frame, text="Config dir").grid(row=2, column=0, sticky="w", **padding)
        ttk.Entry(input_frame, textvariable=self.config_dir_var, width=50).grid(row=2, column=1, columnspan=4, sticky="we", **padding)
        ttk.Button(input_frame, text="Browse", command=self._browse_config_dir).grid(row=2, column=5, sticky="w", **padding)

        ttk.Label(input_frame, text="Server file override").grid(row=3, column=0, sticky="w", **padding)
        ttk.Entry(input_frame, textvariable=self.server_file_var, width=50).grid(row=3, column=1, columnspan=4, sticky="we", **padding)
        ttk.Button(input_frame, text="Browse", command=self._browse_server_file).grid(row=3, column=5, sticky="w", **padding)

        ttk.Label(input_frame, text="Log dir").grid(row=4, column=0, sticky="w", **padding)
        ttk.Entry(input_frame, textvariable=self.log_dir_var, width=50).grid(row=4, column=1, columnspan=4, sticky="we", **padding)
        ttk.Button(input_frame, text="Browse", command=self._browse_log_dir).grid(row=4, column=5, sticky="w", **padding)

        input_frame.columnconfigure(4, weight=1)

        button_frame = ttk.Frame(frame)
        button_frame.pack(fill="x", pady=(0, 8))

        self.start_button = ttk.Button(button_frame, text="Start scan", command=self.start_scan)
        self.start_button.pack(side="left", padx=(0, 8))

        ttk.Button(button_frame, text="Open HTML report", command=self.open_html_report).pack(side="left", padx=(0, 8))
        ttk.Button(button_frame, text="Open log folder", command=self.open_log_folder).pack(side="left", padx=(0, 8))
        ttk.Button(button_frame, text="Clear results", command=self.clear_results).pack(side="left", padx=(0, 8))

        self.progress = ttk.Progressbar(frame, mode="determinate")
        self.progress.pack(fill="x", pady=(0, 8))

        columns = ("host", "status", "ips", "ping", "ports", "notes")
        self.tree = ttk.Treeview(frame, columns=columns, show="headings", height=20)
        self.tree.heading("host", text="Host")
        self.tree.heading("status", text="Status")
        self.tree.heading("ips", text="IP Address")
        self.tree.heading("ping", text="Ping")
        self.tree.heading("ports", text="Ports")
        self.tree.heading("notes", text="Notes")

        self.tree.column("host", width=180)
        self.tree.column("status", width=90)
        self.tree.column("ips", width=170)
        self.tree.column("ping", width=120)
        self.tree.column("ports", width=180)
        self.tree.column("notes", width=280)

        yscroll = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=yscroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        yscroll.pack(side="right", fill="y")

        status_bar = ttk.Label(self.root, textvariable=self.status_var, relief="sunken", anchor="w", padding=5)
        status_bar.pack(fill="x", side="bottom")

    def _browse_config_dir(self) -> None:
        selected = filedialog.askdirectory(title="Choose config directory")
        if selected:
            self.config_dir_var.set(selected)

    def _browse_server_file(self) -> None:
        selected = filedialog.askopenfilename(
            title="Choose server list",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        )
        if selected:
            self.server_file_var.set(selected)

    def _browse_log_dir(self) -> None:
        selected = filedialog.askdirectory(title="Choose log directory")
        if selected:
            self.log_dir_var.set(selected)

    def _selected_config_file(self) -> Path:
        if self.server_file_var.get().strip():
            return Path(self.server_file_var.get()).expanduser().resolve()
        return legacy_config_path(
            self.appgroup_var.get().strip(),
            self.site_var.get().strip(),
            Path(self.config_dir_var.get()).expanduser().resolve(),
        )

    def clear_results(self) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.progress["value"] = 0
        self.latest_results = []
        self.latest_report_paths = {}
        self.status_var.set("Ready.")

    def start_scan(self) -> None:
        if self.scan_thread and self.scan_thread.is_alive():
            messagebox.showinfo("Scan already running", "A scan is already running.")
            return

        self.clear_results()

        try:
            appgroup = self.appgroup_var.get().strip() or "servers"
            site = self.site_var.get().strip() or "default"
            config_file = self._selected_config_file()
            log_dir = Path(self.log_dir_var.get()).expanduser().resolve()
            ports = parse_ports(self.ports_var.get().strip())
            count = int(self.count_var.get())
            timeout = float(self.timeout_var.get())
            workers = int(self.workers_var.get())
            servers = read_servers(config_file)
        except Exception as exc:
            messagebox.showerror("Cannot start scan", str(exc))
            return

        self.progress["maximum"] = len(servers)
        self.progress["value"] = 0
        self.start_button.config(state="disabled")
        self.status_var.set(f"Scanning {len(servers)} server(s)...")

        def worker() -> None:
            try:
                def progress_callback(done: int, total: int, result: ScanResult) -> None:
                    self.event_queue.put(("result", done, total, result))

                results = scan_servers(
                    servers=servers,
                    ports=ports,
                    count=count,
                    timeout=timeout,
                    workers=workers,
                    progress_callback=progress_callback,
                )
                paths = save_reports(results, appgroup, site, log_dir)
                self.event_queue.put(("done", results, paths))
            except Exception as exc:
                self.event_queue.put(("error", str(exc)))

        self.scan_thread = threading.Thread(target=worker, daemon=True)
        self.scan_thread.start()

    def _poll_queue(self) -> None:
        try:
            while True:
                event = self.event_queue.get_nowait()
                kind = event[0]

                if kind == "result":
                    _kind, done, total, result = event
                    self.progress["value"] = done
                    self.tree.insert(
                        "",
                        "end",
                        values=(
                            result.host,
                            result.status,
                            result.ip_text,
                            result.ping_text,
                            result.ports_text,
                            result.error,
                        ),
                    )
                    self.status_var.set(f"Scanned {done}/{total}: {result.host} = {result.status}")

                elif kind == "done":
                    _kind, results, paths = event
                    self.latest_results = results
                    self.latest_report_paths = paths
                    self.start_button.config(state="normal")
                    self.status_var.set(f"Done. Reports saved to: {paths['html'].parent}")
                    messagebox.showinfo(
                        "Scan complete",
                        "Reports created:\n"
                        + "\n".join(f"{key.upper()}: {path}" for key, path in paths.items()),
                    )

                elif kind == "error":
                    _kind, error = event
                    self.start_button.config(state="normal")
                    self.status_var.set("Error.")
                    messagebox.showerror("Scan failed", error)

        except queue.Empty:
            pass

        self.root.after(150, self._poll_queue)

    def open_html_report(self) -> None:
        html_path = self.latest_report_paths.get("html")
        if not html_path:
            messagebox.showinfo("No report yet", "Run a scan first.")
            return
        webbrowser.open(html_path.as_uri())

    def open_log_folder(self) -> None:
        folder = Path(self.log_dir_var.get()).expanduser().resolve()
        folder.mkdir(parents=True, exist_ok=True)
        webbrowser.open(folder.as_uri())


def run_gui() -> int:
    if tk is None:
        print("Tkinter is not available on this system. Run in CLI mode instead.", file=sys.stderr)
        return 2

    root = tk.Tk()
    PingServerGUI(root)
    root.mainloop()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Ping server groups from legacy config files, with GUI and reports.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument("appgroup", nargs="?", default="dms", help="Application group, e.g. dms or swaps")
    parser.add_argument("site", nargs="?", default="155", help="Site, e.g. 155 or bromley")
    parser.add_argument("--gui", action="store_true", help="Open the Tkinter GUI")
    parser.add_argument("--server-file", help="Use a specific server list file instead of appgroup/site naming")
    parser.add_argument("--config-dir", help="Directory containing config files")
    parser.add_argument("--log-dir", help="Directory where reports are saved")
    parser.add_argument("--ports", default="", help="Optional TCP ports to check, e.g. 22,80,443 or 8000-8010")
    parser.add_argument("--count", type=int, default=DEFAULT_COUNT, help="Ping packets per server")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help="Timeout in seconds")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS, help="Concurrent worker threads")
    parser.add_argument("--open-html", action="store_true", help="Open the HTML report after CLI scan")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.gui:
        return run_gui()

    try:
        return run_cli(args)
    except KeyboardInterrupt:
        print("\nCancelled by user.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
