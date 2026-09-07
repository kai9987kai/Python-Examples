#!/usr/bin/env python3
"""
Windows Spotlight Collector
===========================

Collects cached Windows Spotlight lock-screen and desktop images on Windows
10/11, validates them with Pillow, classifies them by orientation, de-duplicates
by SHA-256, and copies them into a clean destination hierarchy.

Python: 3.10+
Dependency: Pillow
    py -m pip install --upgrade Pillow

Examples:
    py spotlight_collector.py
    py spotlight_collector.py "D:\\Wallpapers\\Spotlight"
    py spotlight_collector.py --dry-run -v
    py spotlight_collector.py --min-bytes 51200 --min-long-edge 1080
    py spotlight_collector.py --source "D:\\ExtraSpotlightCache"

The script is read-only with respect to Windows Spotlight caches. It never
modifies or deletes source assets.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import platform
import re
import shutil
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable, Iterator, Sequence

try:
    from PIL import Image, UnidentifiedImageError
except ImportError as exc:  # pragma: no cover - friendly startup failure
    raise SystemExit(
        "Pillow is required. Install it with:\n"
        "  py -m pip install --upgrade Pillow"
    ) from exc


APP_NAME = "Windows Spotlight Collector"
VERSION = "3.0.0"

# Pillow's canonical format names mapped to conventional filename extensions.
FORMAT_EXTENSIONS: dict[str, str] = {
    "JPEG": ".jpg",
    "PNG": ".png",
    "WEBP": ".webp",
    "BMP": ".bmp",
    "GIF": ".gif",
    "TIFF": ".tif",
}

HASH_IN_FILENAME = re.compile(r"_([0-9a-f]{64})(?:\.[^.]+)$", re.IGNORECASE)
SPOTLIGHT_PATH_MARKERS = (
    "contentdeliverymanager",
    "desktopspotlight",
    "irisservice",
)

LOG = logging.getLogger("spotlight_collector")


@dataclass(frozen=True)
class Source:
    path: Path
    kind: str


@dataclass(frozen=True)
class ImageCandidate:
    source: Path
    source_kind: str
    size_bytes: int
    width: int
    height: int
    image_format: str
    extension: str
    sha256: str
    orientation: str
    modified_at: str


@dataclass
class Stats:
    sources_found: int = 0
    files_seen: int = 0
    files_under_size_limit: int = 0
    images_too_small: int = 0
    invalid_or_unsupported_images: int = 0
    duplicates: int = 0
    copied: int = 0
    would_copy: int = 0
    errors: int = 0


@dataclass
class RunReport:
    application: str
    version: str
    generated_at: str
    destination: str
    dry_run: bool
    sources: list[dict[str, str]] = field(default_factory=list)
    settings: dict[str, int | bool] = field(default_factory=dict)
    stats: dict[str, int] = field(default_factory=dict)
    images: list[dict[str, object]] = field(default_factory=list)


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """Return the SHA-256 digest of *path* without loading it all into RAM."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_resolve(path: Path) -> Path:
    """Resolve a path when possible without failing on inaccessible files."""
    try:
        return path.resolve(strict=False)
    except (OSError, RuntimeError):
        return path.absolute()


def path_key(path: Path) -> str:
    """Produce a case-normalized path key suitable for Windows de-duplication."""
    return os.path.normcase(str(safe_resolve(path)))


def is_within(path: Path, parent: Path) -> bool:
    """Return True when *path* is inside *parent*."""
    try:
        safe_resolve(path).relative_to(safe_resolve(parent))
        return True
    except ValueError:
        return False


def read_current_wallpaper_from_registry() -> Path | None:
    """
    Read HKCU\\Control Panel\\Desktop\\Wallpaper.

    The value is only returned when its path itself looks Spotlight-related,
    preventing this collector from accidentally importing an ordinary personal
    wallpaper.
    """
    if os.name != "nt":
        return None

    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Control Panel\Desktop") as key:
            value, _ = winreg.QueryValueEx(key, "Wallpaper")
    except (ImportError, OSError):
        return None

    if not isinstance(value, str) or not value.strip():
        return None

    expanded = os.path.expandvars(value.strip())
    candidate = Path(expanded)
    lowered = str(candidate).lower()
    if candidate.is_file() and any(marker in lowered for marker in SPOTLIGHT_PATH_MARKERS):
        return candidate
    return None


def discover_sources(extra_sources: Sequence[Path] = ()) -> list[Source]:
    """
    Discover known Windows Spotlight caches.

    Wildcards are deliberately used for package-family suffixes instead of
    hard-coding only ``cw5n1h2txyewy``. This makes the collector more tolerant
    of future package naming changes.
    """
    found: list[Source] = []
    seen: set[str] = set()

    def add(path: Path, kind: str) -> None:
        if not path.exists():
            return
        key = path_key(path)
        if key in seen:
            return
        seen.add(key)
        found.append(Source(path=path, kind=kind))

    local_app_data = Path(
        os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
    )
    windir = Path(os.environ.get("WINDIR", r"C:\Windows"))

    packages = local_app_data / "Packages"
    if packages.is_dir():
        # Windows 10/11 lock-screen Spotlight cache.
        for path in packages.glob(
            "Microsoft.Windows.ContentDeliveryManager_*/LocalState/Assets"
        ):
            add(path, "lock-screen-cache")

        # Windows 11 desktop Spotlight cache. IrisService is recursive and its
        # JPGs can sit below numeric child directories.
        for path in packages.glob(
            "MicrosoftWindows.Client.CBS_*/LocalCache/Microsoft/IrisService"
        ):
            add(path, "desktop-cache")

    # Windows 11 Client.CBS built-in/default Desktop Spotlight assets.
    system_apps = windir / "SystemApps"
    if system_apps.is_dir():
        try:
            matches = system_apps.glob(
                "MicrosoftWindows.Client.CBS_*/DesktopSpotlight/Assets/Images"
            )
            for path in matches:
                add(path, "desktop-system-assets")
        except OSError as exc:
            LOG.debug("Could not enumerate SystemApps: %s", exc)

    current = read_current_wallpaper_from_registry()
    if current is not None:
        add(current, "current-desktop-spotlight")

    for path in extra_sources:
        expanded = Path(os.path.expandvars(os.path.expanduser(str(path))))
        add(expanded, "custom")

    return found


def iter_source_files(source: Source, output_root: Path) -> Iterator[Path]:
    """Yield files from a source, recursively for directories."""
    if source.path.is_file():
        if not is_within(source.path, output_root):
            yield source.path
        return

    def on_walk_error(exc: OSError) -> None:
        LOG.warning("Cannot scan part of %s: %s", source.path, exc)

    for root, dirs, files in os.walk(source.path, topdown=True, onerror=on_walk_error):
        root_path = Path(root)

        # Never recursively import our own output if the user deliberately puts
        # the destination below a custom source directory.
        dirs[:] = [
            directory
            for directory in dirs
            if not is_within(root_path / directory, output_root)
        ]

        for name in files:
            candidate = root_path / name
            if not is_within(candidate, output_root):
                yield candidate


def oriented_dimensions(image: Image.Image) -> tuple[int, int]:
    """Return display dimensions, accounting for common EXIF rotation tags."""
    width, height = image.size
    try:
        orientation = image.getexif().get(274)  # EXIF Orientation
    except (AttributeError, OSError, ValueError):
        orientation = None

    if orientation in (5, 6, 7, 8):
        return height, width
    return width, height


def classify_orientation(width: int, height: int) -> str:
    if width > height:
        return "Desktop"
    if height > width:
        return "Mobile"
    return "Square"


def inspect_image(
    path: Path,
    source_kind: str,
    *,
    min_bytes: int,
    min_long_edge: int,
    min_short_edge: int,
) -> tuple[str, ImageCandidate | None]:
    """
    Validate and inspect a source asset.

    Return status in {"ok", "under-bytes", "too-small", "invalid", "error"}.
    """
    try:
        stat = path.stat()
    except OSError as exc:
        LOG.debug("Cannot stat %s: %s", path, exc)
        return "error", None

    if not path.is_file() or stat.st_size < min_bytes:
        return "under-bytes", None

    try:
        with Image.open(path) as image:
            image_format = (image.format or "").upper()
            width, height = oriented_dimensions(image)
            image.verify()
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
        LOG.debug("Not a usable image: %s (%s)", path, exc)
        return "invalid", None

    extension = FORMAT_EXTENSIONS.get(image_format)
    if extension is None:
        LOG.debug("Unsupported Pillow image format %r: %s", image_format, path)
        return "invalid", None

    long_edge = max(width, height)
    short_edge = min(width, height)
    if long_edge < min_long_edge or short_edge < min_short_edge:
        return "too-small", None

    try:
        digest = sha256_file(path)
    except OSError as exc:
        LOG.debug("Cannot hash %s: %s", path, exc)
        return "error", None

    modified_at = datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat()

    return "ok", ImageCandidate(
        source=path,
        source_kind=source_kind,
        size_bytes=stat.st_size,
        width=width,
        height=height,
        image_format=image_format,
        extension=extension,
        sha256=digest,
        orientation=classify_orientation(width, height),
        modified_at=modified_at,
    )


def existing_hashes(output_root: Path) -> set[str]:
    """
    Build an exact-content hash index for images already in the destination.

    New collector filenames contain the full SHA-256, so repeat runs usually
    avoid disk reads. Legacy/renamed images are hashed once for compatibility.
    """
    hashes: set[str] = set()
    if not output_root.exists():
        return hashes

    for root, _, files in os.walk(output_root):
        root_path = Path(root)
        for filename in files:
            path = root_path / filename
            if path.name == "spotlight_report.json" or path.suffix.lower() == ".tmp":
                continue

            match = HASH_IN_FILENAME.search(path.name)
            if match:
                hashes.add(match.group(1).lower())
                continue

            if path.suffix.lower() not in set(FORMAT_EXTENSIONS.values()):
                continue

            try:
                hashes.add(sha256_file(path))
            except OSError as exc:
                LOG.debug("Could not hash existing output %s: %s", path, exc)

    return hashes


def make_output_path(root: Path, image: ImageCandidate, flat: bool) -> Path:
    directory = root if flat else root / image.orientation
    filename = (
        f"spotlight_{image.orientation.lower()}_"
        f"{image.width}x{image.height}_{image.sha256}{image.extension}"
    )
    return directory / filename


def atomic_copy(source: Path, destination: Path) -> None:
    """Copy via a temporary file then atomically replace into final location."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(
        f".{destination.name}.{os.getpid()}.tmp"
    )

    try:
        shutil.copy2(source, temporary)
        os.replace(temporary, destination)
    finally:
        try:
            if temporary.exists():
                temporary.unlink()
        except OSError:
            pass


def collect_spotlight_images(
    destination: Path,
    *,
    extra_sources: Sequence[Path] = (),
    min_bytes: int = 100_000,
    min_long_edge: int = 1080,
    min_short_edge: int = 720,
    flat: bool = False,
    dry_run: bool = False,
) -> RunReport:
    destination = Path(os.path.expandvars(os.path.expanduser(str(destination))))
    destination = safe_resolve(destination)

    sources = discover_sources(extra_sources)
    stats = Stats(sources_found=len(sources))

    report = RunReport(
        application=APP_NAME,
        version=VERSION,
        generated_at=datetime.now().astimezone().isoformat(),
        destination=str(destination),
        dry_run=dry_run,
        sources=[{"kind": source.kind, "path": str(source.path)} for source in sources],
        settings={
            "min_bytes": min_bytes,
            "min_long_edge": min_long_edge,
            "min_short_edge": min_short_edge,
            "flat": flat,
        },
    )

    if not sources:
        LOG.warning("No Windows Spotlight cache locations were found.")
        report.stats = asdict(stats)
        return report

    if not dry_run:
        destination.mkdir(parents=True, exist_ok=True)

    known_hashes = existing_hashes(destination)
    seen_source_paths: set[str] = set()

    for source in sources:
        LOG.info("Scanning [%s] %s", source.kind, source.path)

        for path in iter_source_files(source, destination):
            key = path_key(path)
            if key in seen_source_paths:
                continue
            seen_source_paths.add(key)
            stats.files_seen += 1

            status, image = inspect_image(
                path,
                source.kind,
                min_bytes=min_bytes,
                min_long_edge=min_long_edge,
                min_short_edge=min_short_edge,
            )

            if status == "under-bytes":
                stats.files_under_size_limit += 1
                continue
            if status == "too-small":
                stats.images_too_small += 1
                continue
            if status == "invalid":
                stats.invalid_or_unsupported_images += 1
                continue
            if status == "error" or image is None:
                stats.errors += 1
                continue

            output = make_output_path(destination, image, flat)
            duplicate = image.sha256 in known_hashes

            item: dict[str, object] = {
                "source": str(image.source),
                "source_kind": image.source_kind,
                "output": str(output),
                "sha256": image.sha256,
                "format": image.image_format,
                "width": image.width,
                "height": image.height,
                "orientation": image.orientation,
                "size_bytes": image.size_bytes,
                "modified_at": image.modified_at,
                "duplicate": duplicate,
                "copied": False,
            }

            if duplicate:
                stats.duplicates += 1
                LOG.debug("Duplicate: %s", path)
                report.images.append(item)
                continue

            if dry_run:
                stats.would_copy += 1
                known_hashes.add(image.sha256)
                item["would_copy"] = True
                LOG.info(
                    "Would copy %s -> %s (%dx%d, %s)",
                    path,
                    output,
                    image.width,
                    image.height,
                    image.image_format,
                )
                report.images.append(item)
                continue

            try:
                atomic_copy(path, output)
            except OSError as exc:
                stats.errors += 1
                item["error"] = str(exc)
                LOG.warning("Copy failed: %s -> %s: %s", path, output, exc)
            else:
                stats.copied += 1
                known_hashes.add(image.sha256)
                item["copied"] = True
                LOG.info(
                    "Copied %s (%dx%d, %s) -> %s",
                    path.name,
                    image.width,
                    image.height,
                    image.image_format,
                    output,
                )

            report.images.append(item)

    report.stats = asdict(stats)
    return report


def write_report(report: RunReport, destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    report_path = destination / "spotlight_report.json"
    temporary = destination / f".spotlight_report.{os.getpid()}.tmp"

    payload = asdict(report)
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    os.replace(temporary, report_path)
    return report_path


def default_destination() -> Path:
    return Path.home() / "Pictures" / "Windows Spotlight"


def non_negative_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if number < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return number


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="spotlight_collector.py",
        description=(
            "Collect, validate, classify and de-duplicate Windows Spotlight "
            "lock-screen and desktop images."
        ),
    )
    parser.add_argument(
        "destination",
        nargs="?",
        type=Path,
        default=default_destination(),
        help="output folder (default: ~/Pictures/Windows Spotlight)",
    )
    parser.add_argument(
        "--source",
        action="append",
        type=Path,
        default=[],
        metavar="PATH",
        help="add an extra file/folder source; repeatable",
    )
    parser.add_argument(
        "--min-bytes",
        type=non_negative_int,
        default=100_000,
        help="ignore files smaller than this many bytes (default: 100000)",
    )
    parser.add_argument(
        "--min-long-edge",
        type=non_negative_int,
        default=1080,
        help="minimum pixels on the image's long edge (default: 1080)",
    )
    parser.add_argument(
        "--min-short-edge",
        type=non_negative_int,
        default=720,
        help="minimum pixels on the image's short edge (default: 720)",
    )
    parser.add_argument(
        "--flat",
        action="store_true",
        help="store all images in one folder instead of Desktop/Mobile/Square",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="scan and report what would be copied without writing images",
    )
    parser.add_argument(
        "--no-report",
        action="store_true",
        help="do not write spotlight_report.json",
    )
    parser.add_argument(
        "--open-folder",
        action="store_true",
        help="open the destination in File Explorer after collection",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="increase logging detail; use -vv for debug output",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="only show warnings/errors and the final summary",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {VERSION}",
    )
    return parser


def configure_logging(verbose: int, quiet: bool) -> None:
    if quiet:
        level = logging.WARNING
    elif verbose >= 2:
        level = logging.DEBUG
    elif verbose == 1:
        level = logging.INFO
    else:
        level = logging.WARNING

    logging.basicConfig(
        level=level,
        format="%(levelname)s: %(message)s",
    )


def print_summary(report: RunReport) -> None:
    stats = report.stats
    print(f"\n{APP_NAME} {VERSION}")
    print(f"Destination : {report.destination}")
    print(f"Sources     : {stats.get('sources_found', 0)}")
    print(f"Files seen  : {stats.get('files_seen', 0)}")
    print(f"Duplicates  : {stats.get('duplicates', 0)}")
    print(f"Too small   : {stats.get('images_too_small', 0)}")
    print(f"Invalid     : {stats.get('invalid_or_unsupported_images', 0)}")
    print(f"Errors      : {stats.get('errors', 0)}")
    if report.dry_run:
        print(f"Would copy  : {stats.get('would_copy', 0)}")
    else:
        print(f"Copied      : {stats.get('copied', 0)}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    configure_logging(args.verbose, args.quiet)

    if platform.system() != "Windows":
        parser.error("this utility is intended to run on Windows 10 or Windows 11")

    destination = Path(
        os.path.expandvars(os.path.expanduser(str(args.destination)))
    )

    try:
        report = collect_spotlight_images(
            destination,
            extra_sources=args.source,
            min_bytes=args.min_bytes,
            min_long_edge=args.min_long_edge,
            min_short_edge=args.min_short_edge,
            flat=args.flat,
            dry_run=args.dry_run,
        )
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        return 130

    print_summary(report)

    if not args.no_report and not args.dry_run:
        try:
            report_path = write_report(report, safe_resolve(destination))
        except OSError as exc:
            print(f"Warning: could not write JSON report: {exc}", file=sys.stderr)
        else:
            print(f"Report      : {report_path}")

    if args.open_folder and not args.dry_run:
        try:
            os.startfile(safe_resolve(destination))  # type: ignore[attr-defined]
        except OSError as exc:
            print(f"Warning: could not open destination: {exc}", file=sys.stderr)

    return 1 if report.stats.get("errors", 0) else 0


if __name__ == "__main__":
    raise SystemExit(main())
