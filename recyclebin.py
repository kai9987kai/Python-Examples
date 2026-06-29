"""
Recycle Bin Explorer
--------------------
A modern, read-only-by-default Windows Recycle Bin viewer with optional
restore, search, metadata parsing, CSV export, and folder-opening tools.

Requires: Python 3.10+ on Windows. Uses only the standard library.
"""
from __future__ import annotations

import csv
import ctypes
import os
import queue
import shutil
import struct
import threading
import traceback
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

try:
    import winreg  # Windows only
except ImportError:  # Lets the script display a helpful error on non-Windows systems.
    winreg = None


APP_NAME = "Recycle Bin Explorer"
FILETIME_EPOCH = datetime(1601, 1, 1, tzinfo=timezone.utc)


@dataclass(slots=True)
class RecycleItem:
    user: str
    sid: str
    original_name: str
    original_path: str
    size_bytes: int | None
    deleted_at: datetime | None
    status: str
    metadata_path: str | None
    data_path: str | None
    recycle_root: str
    error: str = ""

    @property
    def display_size(self) -> str:
        return format_size(self.size_bytes)

    @property
    def display_deleted_at(self) -> str:
        if self.deleted_at is None:
            return "Unknown"
        return self.deleted_at.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


@dataclass(slots=True)
class ScanResult:
    items: list[RecycleItem]
    scanned_roots: list[str]
    warnings: list[str]


def format_size(value: int | None) -> str:
    if value is None:
        return "Unknown"
    units = ("B", "KB", "MB", "GB", "TB", "PB")
    amount = float(value)
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(amount):,} {unit}"
            return f"{amount:,.2f} {unit}"
        amount /= 1024
    return "Unknown"


def safe_basename(path_text: str, fallback: str = "Unknown") -> str:
    # pathlib on a non-Windows test host may not recognise Windows separators,
    # so normalise manually first.
    candidate = path_text.replace("/", "\\").rstrip("\\")
    return candidate.rsplit("\\", 1)[-1] or fallback


def windows_filetime_to_datetime(value: int) -> datetime | None:
    if value <= 0:
        return None
    try:
        return FILETIME_EPOCH + timedelta(microseconds=value / 10)
    except (OverflowError, OSError, ValueError):
        return None


def decode_utf16_path(data: bytes) -> str:
    """Decode a Recycle Bin original-path field without crashing on bad data."""
    if not data:
        return ""
    text = data.decode("utf-16-le", errors="replace").split("\x00", 1)[0].strip()
    return text


def parse_i_file(metadata_path: Path) -> tuple[int | None, datetime | None, str, str]:
    """
    Parse a Windows $I recycle-bin metadata file.

    Returns: (original_size, deletion_datetime, original_path, parse_note)
    Supports the commonly used version 1 and version 2 formats. Unknown
    versions still receive a best-effort path decode when possible.
    """
    try:
        raw = metadata_path.read_bytes()
    except OSError as exc:
        return None, None, "", f"Could not read metadata: {exc}"

    if len(raw) < 24:
        return None, None, "", "Metadata file is too small"

    try:
        version, size_bytes, filetime = struct.unpack_from("<QQQ", raw, 0)
    except struct.error as exc:
        return None, None, "", f"Invalid metadata header: {exc}"

    deleted_at = windows_filetime_to_datetime(filetime)
    path_text = ""
    note = ""

    # Version 1 stores a fixed-size 520-byte UTF-16LE path after the header.
    if version == 1:
        path_text = decode_utf16_path(raw[24:])
    # Version 2 adds a 4-byte path character count at offset 24.
    elif version == 2:
        if len(raw) >= 28:
            path_chars = struct.unpack_from("<I", raw, 24)[0]
            if 0 < path_chars <= 32767:
                path_text = decode_utf16_path(raw[28:28 + (path_chars * 2)])
            else:
                path_text = decode_utf16_path(raw[28:])
                note = "Version 2 path length was invalid; used best-effort decode"
        else:
            note = "Incomplete version 2 metadata"
    else:
        path_text = decode_utf16_path(raw[24:])
        note = f"Unknown metadata version {version}; used best-effort decode"

    if not path_text:
        note = (note + "; " if note else "") + "Original path unavailable"

    return size_bytes, deleted_at, path_text, note


def sid_to_user(sid: str) -> str:
    """Resolve a local profile SID via the registry, returning the SID on failure."""
    if not sid or not sid.startswith("S-") or winreg is None:
        return sid or "Unknown user"

    try:
        registry_path = (
            r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\ProfileList\\" + sid
        )
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, registry_path) as key:
            profile_path, _ = winreg.QueryValueEx(key, "ProfileImagePath")
        return os.path.basename(os.path.expandvars(profile_path)) or sid
    except OSError:
        return sid


def list_windows_drives() -> list[Path]:
    """Return available drive roots without requiring third-party packages."""
    if os.name != "nt":
        return []

    drives: list[Path] = []
    try:
        bitmask = ctypes.windll.kernel32.GetLogicalDrives()
        for index in range(26):
            if bitmask & (1 << index):
                root = Path(f"{chr(65 + index)}:\\")
                if root.exists():
                    drives.append(root)
    except Exception:
        # Conservative fallback: only probe conventional drive letters.
        for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            root = Path(f"{letter}:\\")
            if root.exists():
                drives.append(root)
    return drives


def discover_recycle_bin_roots() -> list[Path]:
    """Find modern and legacy recycle-bin roots on each accessible drive."""
    roots: list[Path] = []
    seen: set[str] = set()
    for drive in list_windows_drives():
        for name in ("$Recycle.Bin", "Recycler", "Recycled"):
            candidate = drive / name
            try:
                if candidate.is_dir():
                    key = str(candidate).lower()
                    if key not in seen:
                        roots.append(candidate)
                        seen.add(key)
            except OSError:
                continue
    return roots


def child_directories(path: Path) -> list[Path]:
    try:
        return [entry for entry in path.iterdir() if entry.is_dir()]
    except OSError:
        return []


def iter_recycle_containers(root: Path) -> Iterable[tuple[str, Path]]:
    """Yield SID/user folder and its folder, including direct-file legacy roots."""
    try:
        root_entries = list(root.iterdir())
    except OSError:
        return

    direct_i_files = any(entry.is_file() and entry.name.upper().startswith("$I") for entry in root_entries)
    if direct_i_files:
        yield "Unknown user", root

    for entry in root_entries:
        if entry.is_dir():
            # Modern format uses S-1-... directories. Including other folders
            # keeps the viewer useful for unusual legacy/custom layouts.
            yield entry.name, entry


def item_from_metadata(sid: str, container: Path, metadata: Path, recycle_root: Path) -> RecycleItem:
    size_bytes, deleted_at, original_path, note = parse_i_file(metadata)
    data_name = "$R" + metadata.name[2:] if metadata.name.upper().startswith("$I") else ""
    data_path = container / data_name
    data_present = data_path.exists()
    status = "Data file present" if data_present else "Metadata only"
    if note:
        status += " — metadata warning"

    original_name = safe_basename(original_path, fallback=data_name or metadata.name)
    return RecycleItem(
        user=sid_to_user(sid),
        sid=sid,
        original_name=original_name,
        original_path=original_path or "Unknown",
        size_bytes=size_bytes,
        deleted_at=deleted_at,
        status=status,
        metadata_path=str(metadata),
        data_path=str(data_path) if data_present else None,
        recycle_root=str(recycle_root),
        error=note,
    )


def orphan_item(sid: str, container: Path, data_file: Path, recycle_root: Path) -> RecycleItem:
    return RecycleItem(
        user=sid_to_user(sid),
        sid=sid,
        original_name=data_file.name,
        original_path="Unknown (matching $I metadata not found)",
        size_bytes=_safe_file_size(data_file),
        deleted_at=None,
        status="Orphaned data file",
        metadata_path=None,
        data_path=str(data_file),
        recycle_root=str(recycle_root),
        error="Matching metadata file was not found",
    )


def _safe_file_size(path: Path) -> int | None:
    try:
        return path.stat().st_size
    except OSError:
        return None


def scan_recycle_bin_roots(roots: Iterable[Path]) -> ScanResult:
    items: list[RecycleItem] = []
    warnings: list[str] = []
    scanned_roots: list[str] = []

    for root in roots:
        try:
            if not root.is_dir():
                warnings.append(f"Not a directory: {root}")
                continue
            scanned_roots.append(str(root))
            for sid, container in iter_recycle_containers(root):
                try:
                    entries = list(container.iterdir())
                except OSError as exc:
                    warnings.append(f"Could not read {container}: {exc}")
                    continue

                metadata_files = [
                    entry for entry in entries
                    if entry.is_file() and entry.name.upper().startswith("$I")
                ]
                metadata_suffixes: set[str] = set()

                for metadata in metadata_files:
                    try:
                        metadata_suffixes.add(metadata.name[2:].upper())
                        items.append(item_from_metadata(sid, container, metadata, root))
                    except Exception as exc:  # An individual corrupt file must not stop the scan.
                        warnings.append(f"Could not parse {metadata}: {exc}")
                        items.append(
                            RecycleItem(
                                user=sid_to_user(sid),
                                sid=sid,
                                original_name=metadata.name,
                                original_path="Unknown",
                                size_bytes=None,
                                deleted_at=None,
                                status="Unreadable metadata",
                                metadata_path=str(metadata),
                                data_path=None,
                                recycle_root=str(root),
                                error=str(exc),
                            )
                        )

                for data_file in entries:
                    if not (data_file.is_file() and data_file.name.upper().startswith("$R")):
                        continue
                    if data_file.name[2:].upper() not in metadata_suffixes:
                        items.append(orphan_item(sid, container, data_file, root))
        except OSError as exc:
            warnings.append(f"Could not inspect {root}: {exc}")

    items.sort(key=lambda item: item.deleted_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return ScanResult(items=items, scanned_roots=scanned_roots, warnings=warnings)


class RecycleBinExplorer(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_NAME)
        self.geometry("1320x760")
        self.minsize(980, 600)

        self.items: list[RecycleItem] = []
        self.visible_items: dict[str, RecycleItem] = {}
        self.scan_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.sort_column = "deleted"
        self.sort_reverse = True
        self.custom_roots: list[Path] = []

        self.search_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Ready")
        self._configure_style()
        self._build_ui()
        self.search_var.trace_add("write", lambda *_: self.apply_filter())
        self.after(120, self.scan_all_drives)

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Treeview", rowheight=27)
        style.configure("Title.TLabel", font=("Segoe UI", 15, "bold"))

    def _build_ui(self) -> None:
        toolbar = ttk.Frame(self, padding=(12, 10, 12, 6))
        toolbar.pack(fill="x")

        ttk.Label(toolbar, text=APP_NAME, style="Title.TLabel").pack(side="left")
        ttk.Button(toolbar, text="Scan all drives", command=self.scan_all_drives).pack(side="left", padx=(20, 6))
        ttk.Button(toolbar, text="Scan folder…", command=self.choose_folder).pack(side="left", padx=6)
        ttk.Button(toolbar, text="Export CSV…", command=self.export_csv).pack(side="left", padx=6)
        ttk.Button(toolbar, text="Open recycle bin", command=self.open_selected_recycle_root).pack(side="left", padx=6)
        ttk.Button(toolbar, text="Restore selected", command=self.restore_selected).pack(side="left", padx=6)

        ttk.Label(toolbar, text="Search:").pack(side="right", padx=(8, 5))
        search = ttk.Entry(toolbar, textvariable=self.search_var, width=35)
        search.pack(side="right")
        search.bind("<Control-a>", lambda event: (event.widget.select_range(0, "end"), "break"))

        main = ttk.Panedwindow(self, orient="vertical")
        main.pack(fill="both", expand=True, padx=12, pady=(0, 8))

        table_frame = ttk.Frame(main)
        details_frame = ttk.Frame(main, padding=(0, 8, 0, 0))
        main.add(table_frame, weight=4)
        main.add(details_frame, weight=1)

        columns = ("user", "name", "path", "size", "deleted", "status")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="browse")
        headings = {
            "user": "User",
            "name": "Deleted item",
            "path": "Original path",
            "size": "Size",
            "deleted": "Deleted",
            "status": "Status",
        }
        widths = {"user": 145, "name": 210, "path": 460, "size": 110, "deleted": 185, "status": 200}
        for column in columns:
            self.tree.heading(column, text=headings[column], command=lambda col=column: self.sort_by(col))
            self.tree.column(column, width=widths[column], minwidth=85, anchor="w")

        y_scroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        x_scroll = ttk.Scrollbar(table_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)

        self.tree.bind("<<TreeviewSelect>>", self.show_selected_details)
        self.tree.bind("<Double-1>", lambda _event: self.open_selected_data_folder())
        self.tree.bind("<Button-3>", self.show_context_menu)

        self.details = ScrolledText(details_frame, wrap="word", height=9, font=("Consolas", 10))
        self.details.pack(fill="both", expand=True)
        self.details.insert("1.0", "Select an item to view its metadata and available actions.")
        self.details.configure(state="disabled")

        footer = ttk.Frame(self, padding=(12, 4, 12, 9))
        footer.pack(fill="x")
        ttk.Label(footer, textvariable=self.status_var, anchor="w").pack(side="left", fill="x", expand=True)
        ttk.Label(footer, text="Double-click an item to open its recycle-bin folder.", anchor="e").pack(side="right")

        self.context_menu = tk.Menu(self, tearoff=False)
        self.context_menu.add_command(label="Open data folder", command=self.open_selected_data_folder)
        self.context_menu.add_command(label="Copy original path", command=self.copy_original_path)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="Restore selected", command=self.restore_selected)

    def set_details(self, text: str) -> None:
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        self.details.insert("1.0", text)
        self.details.configure(state="disabled")

    def selected_item(self) -> RecycleItem | None:
        selected = self.tree.selection()
        if not selected:
            return None
        return self.visible_items.get(selected[0])

    def show_selected_details(self, _event: object | None = None) -> None:
        item = self.selected_item()
        if item is None:
            return
        detail = (
            f"Deleted item: {item.original_name}\n"
            f"User: {item.user} ({item.sid})\n"
            f"Original path: {item.original_path}\n"
            f"Original size: {item.display_size}\n"
            f"Deleted: {item.display_deleted_at}\n"
            f"Status: {item.status}\n"
            f"Metadata file: {item.metadata_path or 'Not available'}\n"
            f"Data file: {item.data_path or 'Not available'}\n"
            f"Recycle-bin root: {item.recycle_root}\n"
        )
        if item.error:
            detail += f"\nNote: {item.error}\n"
        self.set_details(detail)

    def show_context_menu(self, event: tk.Event) -> None:
        row = self.tree.identify_row(event.y)
        if row:
            self.tree.selection_set(row)
            self.tree.focus(row)
            self.context_menu.tk_popup(event.x_root, event.y_root)

    def scan_all_drives(self) -> None:
        if os.name != "nt":
            messagebox.showerror(APP_NAME, "This program is designed for Windows Recycle Bin folders.")
            return
        roots = discover_recycle_bin_roots()
        roots.extend(root for root in self.custom_roots if root not in roots)
        self.start_scan(roots, source_label="all accessible drives")

    def choose_folder(self) -> None:
        selected = filedialog.askdirectory(title="Select a Recycle Bin folder or SID folder")
        if not selected:
            return
        root = Path(selected)
        if root not in self.custom_roots:
            self.custom_roots.append(root)
        self.start_scan([root], source_label=str(root))

    def start_scan(self, roots: list[Path], source_label: str) -> None:
        if not roots:
            self.items = []
            self.apply_filter()
            self.status_var.set("No accessible Recycle Bin folders were found.")
            self.set_details(
                "No accessible Recycle Bin folders were found. Try running the app as your normal user "
                "or choose a specific folder with ‘Scan folder…’."
            )
            return

        self.status_var.set(f"Scanning {source_label}…")
        self._set_toolbar_state("disabled")
        self.set_details("Scanning in the background…")

        def worker() -> None:
            try:
                result = scan_recycle_bin_roots(roots)
                self.scan_queue.put(("result", result))
            except Exception:
                self.scan_queue.put(("error", traceback.format_exc()))

        threading.Thread(target=worker, daemon=True).start()
        self.after(80, self.poll_scan_queue)

    def poll_scan_queue(self) -> None:
        try:
            kind, payload = self.scan_queue.get_nowait()
        except queue.Empty:
            self.after(80, self.poll_scan_queue)
            return

        self._set_toolbar_state("normal")
        if kind == "error":
            messagebox.showerror(APP_NAME, f"The scan failed:\n\n{payload}")
            self.status_var.set("Scan failed")
            return

        result = payload
        assert isinstance(result, ScanResult)
        self.items = result.items
        self.apply_filter()
        warning_text = f" {len(result.warnings)} warning(s)." if result.warnings else ""
        self.status_var.set(
            f"Found {len(self.items):,} recycle-bin item(s) across {len(result.scanned_roots)} folder(s).{warning_text}"
        )
        if result.warnings:
            self.set_details("Scan finished with warnings:\n\n" + "\n".join(result.warnings[:30]))
        elif not self.items:
            self.set_details("No $I/$R Recycle Bin entries were found in the selected location(s).")
        else:
            self.set_details("Scan complete. Select an item to view metadata and actions.")

    def _set_toolbar_state(self, state: str) -> None:
        # Buttons live in the first child frame. Preserve the Search entry as usable.
        toolbar = self.winfo_children()[0]
        for child in toolbar.winfo_children():
            if isinstance(child, ttk.Button):
                child.configure(state=state)

    def matching_items(self) -> list[RecycleItem]:
        needle = self.search_var.get().strip().casefold()
        if not needle:
            return list(self.items)
        matched: list[RecycleItem] = []
        for item in self.items:
            haystack = " | ".join(
                (
                    item.user,
                    item.sid,
                    item.original_name,
                    item.original_path,
                    item.display_size,
                    item.display_deleted_at,
                    item.status,
                    item.error,
                )
            ).casefold()
            if needle in haystack:
                matched.append(item)
        return matched

    def apply_filter(self) -> None:
        selected = self.selected_item()
        selected_metadata = selected.metadata_path if selected else None
        for row in self.tree.get_children():
            self.tree.delete(row)
        self.visible_items.clear()

        for index, item in enumerate(self.matching_items()):
            row_id = f"item-{index}"
            self.visible_items[row_id] = item
            self.tree.insert(
                "",
                "end",
                iid=row_id,
                values=(
                    item.user,
                    item.original_name,
                    item.original_path,
                    item.display_size,
                    item.display_deleted_at,
                    item.status,
                ),
            )
            if selected_metadata and item.metadata_path == selected_metadata:
                self.tree.selection_set(row_id)
                self.tree.focus(row_id)

    def sort_by(self, column: str) -> None:
        if self.sort_column == column:
            self.sort_reverse = not self.sort_reverse
        else:
            self.sort_column = column
            self.sort_reverse = column in {"deleted", "size"}

        def value(item: RecycleItem):
            mapping = {
                "user": item.user.casefold(),
                "name": item.original_name.casefold(),
                "path": item.original_path.casefold(),
                "size": item.size_bytes if item.size_bytes is not None else -1,
                "deleted": item.deleted_at or datetime.min.replace(tzinfo=timezone.utc),
                "status": item.status.casefold(),
            }
            return mapping[column]

        self.items.sort(key=value, reverse=self.sort_reverse)
        self.apply_filter()

    def open_selected_data_folder(self) -> None:
        item = self.selected_item()
        if item is None:
            messagebox.showinfo(APP_NAME, "Select an item first.")
            return
        target = Path(item.data_path or item.metadata_path or item.recycle_root).parent
        self.open_folder(target)

    def open_selected_recycle_root(self) -> None:
        item = self.selected_item()
        if item is None:
            if self.items:
                item = self.items[0]
            else:
                messagebox.showinfo(APP_NAME, "No Recycle Bin location is available yet.")
                return
        self.open_folder(Path(item.recycle_root))

    def open_folder(self, path: Path) -> None:
        try:
            if not path.exists():
                raise FileNotFoundError(path)
            os.startfile(str(path))  # type: ignore[attr-defined]  # Windows-only function
        except OSError as exc:
            messagebox.showerror(APP_NAME, f"Could not open folder:\n{path}\n\n{exc}")

    def copy_original_path(self) -> None:
        item = self.selected_item()
        if item is None:
            messagebox.showinfo(APP_NAME, "Select an item first.")
            return
        self.clipboard_clear()
        self.clipboard_append(item.original_path)
        self.update()
        self.status_var.set("Original path copied to clipboard.")

    def export_csv(self) -> None:
        rows = self.matching_items()
        if not rows:
            messagebox.showinfo(APP_NAME, "There are no visible results to export.")
            return
        default_name = f"recycle_bin_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        destination = filedialog.asksaveasfilename(
            title="Export visible results to CSV",
            defaultextension=".csv",
            initialfile=default_name,
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if not destination:
            return
        try:
            with open(destination, "w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(
                    [
                        "User",
                        "SID",
                        "Deleted item",
                        "Original path",
                        "Size bytes",
                        "Deleted local time",
                        "Status",
                        "Metadata file",
                        "Data file",
                        "Recycle-bin root",
                        "Note",
                    ]
                )
                for item in rows:
                    writer.writerow(
                        [
                            item.user,
                            item.sid,
                            item.original_name,
                            item.original_path,
                            item.size_bytes if item.size_bytes is not None else "",
                            item.display_deleted_at,
                            item.status,
                            item.metadata_path or "",
                            item.data_path or "",
                            item.recycle_root,
                            item.error,
                        ]
                    )
            self.status_var.set(f"Exported {len(rows):,} visible item(s) to {destination}")
        except OSError as exc:
            messagebox.showerror(APP_NAME, f"Could not export CSV:\n\n{exc}")

    def restore_selected(self) -> None:
        item = self.selected_item()
        if item is None:
            messagebox.showinfo(APP_NAME, "Select an item first.")
            return
        if not item.data_path:
            messagebox.showwarning(APP_NAME, "This item has no available $R data file to restore.")
            return
        if not item.original_path or item.original_path.startswith("Unknown"):
            messagebox.showwarning(APP_NAME, "The original path is not available, so this item cannot be restored automatically.")
            return

        source = Path(item.data_path)
        destination = Path(item.original_path)
        if destination.exists():
            messagebox.showwarning(
                APP_NAME,
                "Restore was blocked because a file or folder already exists at the original path:\n\n"
                f"{destination}\n\nRename or move that item first; this tool never overwrites files.",
            )
            return

        confirm = messagebox.askyesno(
            APP_NAME,
            "Restore this item to its original location?\n\n"
            f"From: {source}\n\nTo: {destination}\n\n"
            "This moves the recycled data file and removes its Recycle Bin metadata. It cannot be undone by this app.",
            icon="warning",
        )
        if not confirm:
            return

        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(destination))
            if item.metadata_path:
                try:
                    Path(item.metadata_path).unlink(missing_ok=True)
                except OSError as exc:
                    messagebox.showwarning(
                        APP_NAME,
                        "The data file was restored, but its metadata could not be removed:\n\n"
                        f"{exc}\n\nYou may still see a stale entry until the next Recycle Bin cleanup.",
                    )
            self.status_var.set(f"Restored: {destination}")
            self.items = [existing for existing in self.items if existing is not item]
            self.apply_filter()
            self.set_details(f"Restored successfully:\n{destination}")
        except OSError as exc:
            messagebox.showerror(APP_NAME, f"Restore failed:\n\n{exc}")


def main() -> None:
    app = RecycleBinExplorer()
    app.mainloop()


if __name__ == "__main__":
    main()
