from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from PIL import Image, ImageOps, UnidentifiedImageError


APP_NAME = "Spotlight Wallpaper Manager"
VERSION = "2.0.0"
PACKAGE_NAME = "Microsoft.Windows.ContentDeliveryManager_cw5n1h2txyewy"
LOGGER = logging.getLogger("spotlight")

FORMAT_EXTENSIONS = {
    "JPEG": ".jpg",
    "PNG": ".png",
    "WEBP": ".webp",
    "BMP": ".bmp",
    "TIFF": ".tif",
    "GIF": ".gif",
    "AVIF": ".avif",
}


@dataclass(frozen=True)
class AssetInfo:
    source: str
    sha256: str
    width: int
    height: int
    image_format: str
    extension: str
    category: str
    bytes: int

    @property
    def filename(self) -> str:
        return (
            f"spotlight_{self.width}x{self.height}_"
            f"{self.sha256[:16]}{self.extension}"
        )


@dataclass
class RunStats:
    scanned: int = 0
    valid_images: int = 0
    copied: int = 0
    duplicates: int = 0
    too_small: int = 0
    unsupported: int = 0
    errors: int = 0


class SpotlightManager:
    """Safely extract, classify, deduplicate and archive Windows Spotlight images."""

    def __init__(
        self,
        source: Path,
        output: Path,
        *,
        min_long_edge: int = 1000,
        min_short_edge: int = 600,
        workers: int = 4,
        dry_run: bool = False,
    ) -> None:
        self.source = source.expanduser().resolve()
        self.output = output.expanduser().resolve()
        self.min_long_edge = min_long_edge
        self.min_short_edge = min_short_edge
        self.workers = max(1, workers)
        self.dry_run = dry_run
        self.manifest_path = self.output / "manifest.json"

    @staticmethod
    def default_source() -> Path:
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            return (
                Path(local_app_data)
                / "Packages"
                / PACKAGE_NAME
                / "LocalState"
                / "Assets"
            )

        user_profile = os.environ.get("USERPROFILE")
        if user_profile:
            return (
                Path(user_profile)
                / "AppData"
                / "Local"
                / "Packages"
                / PACKAGE_NAME
                / "LocalState"
                / "Assets"
            )

        return Path.home() / "AppData" / "Local" / "Packages" / PACKAGE_NAME / "LocalState" / "Assets"

    @staticmethod
    def default_output() -> Path:
        try:
            base = Path(__file__).resolve().parent
        except NameError:
            base = Path.cwd()
        return base / "Wallpapers"

    def validate(self) -> None:
        if os.name != "nt":
            LOGGER.warning(
                "This utility targets Windows Spotlight. Current OS is %s.",
                sys.platform,
            )

        if not self.source.exists():
            raise FileNotFoundError(
                f"Spotlight asset folder was not found:\n  {self.source}\n\n"
                "Enable Windows Spotlight first, or pass a custom folder with --source."
            )
        if not self.source.is_dir():
            raise NotADirectoryError(f"Source is not a directory: {self.source}")

        if self.min_long_edge < 1 or self.min_short_edge < 1:
            raise ValueError("Minimum dimensions must be positive integers.")

        if not self.dry_run:
            for name in ("desktop", "mobile", "square"):
                (self.output / name).mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _sha256(path: Path, chunk_size: int = 1024 * 1024) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(chunk_size), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _classify(width: int, height: int) -> str:
        if width > height:
            return "desktop"
        if height > width:
            return "mobile"
        return "square"

    @staticmethod
    def _extension_for(image_format: str | None) -> str | None:
        if not image_format:
            return None
        fmt = image_format.upper()
        if fmt in FORMAT_EXTENSIONS:
            return FORMAT_EXTENSIONS[fmt]
        if fmt.isalnum():
            return "." + fmt.lower()
        return None

    def _inspect_asset(self, path: Path) -> tuple[str, AssetInfo | None, str | None]:
        """Return (status, metadata, detail) without modifying the source asset."""
        try:
            if not path.is_file():
                return "unsupported", None, "not a regular file"

            # First pass verifies file integrity without relying on a filename suffix.
            with Image.open(path) as probe:
                probe.verify()

            # Re-open after verify(); Pillow requires this before reading image data again.
            with Image.open(path) as raw:
                image_format = (raw.format or "").upper()
                extension = self._extension_for(image_format)
                if extension is None:
                    return "unsupported", None, f"unsupported image format: {image_format or 'unknown'}"

                # Respect EXIF Orientation when determining portrait/landscape dimensions.
                oriented = ImageOps.exif_transpose(raw)
                try:
                    width, height = oriented.size
                finally:
                    if oriented is not raw:
                        oriented.close()

            long_edge = max(width, height)
            short_edge = min(width, height)
            if long_edge < self.min_long_edge or short_edge < self.min_short_edge:
                return (
                    "too_small",
                    None,
                    f"{width}x{height} below minimum "
                    f"{self.min_long_edge}x{self.min_short_edge} (long/short edge)",
                )

            checksum = self._sha256(path)
            info = AssetInfo(
                source=str(path),
                sha256=checksum,
                width=width,
                height=height,
                image_format=image_format,
                extension=extension,
                category=self._classify(width, height),
                bytes=path.stat().st_size,
            )
            return "ok", info, None

        except (UnidentifiedImageError, OSError, ValueError) as exc:
            return "unsupported", None, str(exc)
        except Exception as exc:  # keep one bad cache entry from killing the full scan
            return "error", None, f"{type(exc).__name__}: {exc}"

    def _load_manifest(self) -> dict[str, Any]:
        if not self.manifest_path.exists():
            return {
                "schema": 1,
                "app": APP_NAME,
                "version": VERSION,
                "updated_utc": None,
                "images": {},
            }

        try:
            with self.manifest_path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
            if not isinstance(data, dict) or not isinstance(data.get("images", {}), dict):
                raise ValueError("invalid manifest structure")
            data.setdefault("images", {})
            return data
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            LOGGER.warning("Ignoring unreadable manifest %s: %s", self.manifest_path, exc)
            return {
                "schema": 1,
                "app": APP_NAME,
                "version": VERSION,
                "updated_utc": None,
                "images": {},
            }

    def _write_manifest(self, manifest: dict[str, Any]) -> None:
        if self.dry_run:
            return

        manifest["schema"] = 1
        manifest["app"] = APP_NAME
        manifest["version"] = VERSION
        manifest["updated_utc"] = datetime.now(timezone.utc).isoformat()

        self.output.mkdir(parents=True, exist_ok=True)
        temp_path = self.manifest_path.with_suffix(".json.tmp")
        with temp_path.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(manifest, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temp_path, self.manifest_path)

    @staticmethod
    def _same_file_hash(path: Path, expected_sha256: str) -> bool:
        if not path.exists() or not path.is_file():
            return False
        return SpotlightManager._sha256(path) == expected_sha256

    def _destination_for(self, info: AssetInfo) -> Path:
        return self.output / info.category / info.filename

    def _copy_atomic(self, source: Path, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temp = destination.with_name(destination.name + ".part")
        try:
            shutil.copy2(source, temp)
            os.replace(temp, destination)
        finally:
            if temp.exists():
                try:
                    temp.unlink()
                except OSError:
                    pass

    def _iter_source_files(self) -> list[Path]:
        try:
            return sorted((p for p in self.source.iterdir() if p.is_file()), key=lambda p: p.name)
        except PermissionError as exc:
            raise PermissionError(f"Cannot read Spotlight asset folder: {self.source}") from exc

    def scan_once(self) -> RunStats:
        self.validate()
        files = self._iter_source_files()
        stats = RunStats(scanned=len(files))
        manifest = self._load_manifest()
        images: dict[str, Any] = manifest.setdefault("images", {})

        LOGGER.info("Scanning %d cached asset(s) from %s", len(files), self.source)

        inspected: list[tuple[Path, str, AssetInfo | None, str | None]] = []
        with ThreadPoolExecutor(max_workers=self.workers) as executor:
            future_map = {executor.submit(self._inspect_asset, path): path for path in files}
            for future in as_completed(future_map):
                path = future_map[future]
                try:
                    status, info, detail = future.result()
                except Exception as exc:
                    status, info, detail = "error", None, f"{type(exc).__name__}: {exc}"
                inspected.append((path, status, info, detail))

        # Stable output makes logs/tests deterministic despite concurrent inspection.
        inspected.sort(key=lambda item: item[0].name)

        for source, status, info, detail in inspected:
            if status == "too_small":
                stats.too_small += 1
                LOGGER.debug("Skip small asset %s: %s", source.name, detail)
                continue
            if status == "unsupported":
                stats.unsupported += 1
                LOGGER.debug("Skip non-wallpaper asset %s: %s", source.name, detail)
                continue
            if status == "error" or info is None:
                stats.errors += 1
                LOGGER.warning("Failed to inspect %s: %s", source, detail or "unknown error")
                continue

            stats.valid_images += 1
            destination = self._destination_for(info)
            manifest_record = images.get(info.sha256)

            if manifest_record:
                recorded_path = Path(manifest_record.get("destination", destination))
                if self._same_file_hash(recorded_path, info.sha256):
                    stats.duplicates += 1
                    LOGGER.debug("Already archived: %s", recorded_path.name)
                    continue

            if destination.exists() and self._same_file_hash(destination, info.sha256):
                stats.duplicates += 1
                images[info.sha256] = {
                    **asdict(info),
                    "destination": str(destination),
                    "archived_utc": datetime.now(timezone.utc).isoformat(),
                }
                continue

            LOGGER.info(
                "%s %dx%d -> %s",
                "Would copy" if self.dry_run else "Copying",
                info.width,
                info.height,
                destination,
            )

            if not self.dry_run:
                self._copy_atomic(source, destination)
                if not self._same_file_hash(destination, info.sha256):
                    try:
                        destination.unlink(missing_ok=True)
                    except OSError:
                        pass
                    raise IOError(f"Checksum verification failed after copying {source}")

            images[info.sha256] = {
                **asdict(info),
                "destination": str(destination),
                "archived_utc": datetime.now(timezone.utc).isoformat(),
            }
            stats.copied += 1

        self._write_manifest(manifest)
        return stats

    def watch(self, interval_seconds: float) -> None:
        if interval_seconds < 1:
            raise ValueError("Watch interval must be at least 1 second.")

        LOGGER.info("Watch mode active; rescanning every %.1f seconds. Press Ctrl+C to stop.", interval_seconds)
        try:
            while True:
                stats = self.scan_once()
                print_summary(stats)
                time.sleep(interval_seconds)
        except KeyboardInterrupt:
            LOGGER.info("Watch mode stopped.")


def configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%H:%M:%S",
    )
    # Keep --verbose focused on this application rather than Pillow's plugin loader.
    logging.getLogger("PIL").setLevel(logging.WARNING)


def print_summary(stats: RunStats) -> None:
    print("\n" + "=" * 72)
    print(f"{APP_NAME} {VERSION} - scan complete")
    print("=" * 72)
    print(f"Scanned assets : {stats.scanned}")
    print(f"Valid images   : {stats.valid_images}")
    print(f"New copies     : {stats.copied}")
    print(f"Duplicates     : {stats.duplicates}")
    print(f"Too small      : {stats.too_small}")
    print(f"Non-images     : {stats.unsupported}")
    print(f"Errors         : {stats.errors}")
    print("=" * 72)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Safely extract Windows Spotlight images, verify them with Pillow, "
            "deduplicate them, and sort them by orientation."
        )
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=SpotlightManager.default_source(),
        help="Spotlight Assets directory (auto-detected by default).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=SpotlightManager.default_output(),
        help="Archive directory (default: ./Wallpapers beside this script).",
    )
    parser.add_argument(
        "--min-long-edge",
        type=int,
        default=1000,
        help="Minimum size of the image's longest edge in pixels (default: 1000).",
    )
    parser.add_argument(
        "--min-short-edge",
        type=int,
        default=600,
        help="Minimum size of the image's shortest edge in pixels (default: 600).",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=min(8, max(2, os.cpu_count() or 2)),
        help="Concurrent inspection workers (default: based on CPU count, max 8).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Inspect and report without creating or copying files.",
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Keep monitoring the Spotlight cache for newly downloaded images.",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=60.0,
        help="Seconds between scans in --watch mode (default: 60).",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show skipped assets and diagnostic details.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {VERSION}",
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    configure_logging(args.verbose)

    manager = SpotlightManager(
        source=args.source,
        output=args.output,
        min_long_edge=args.min_long_edge,
        min_short_edge=args.min_short_edge,
        workers=args.workers,
        dry_run=args.dry_run,
    )

    try:
        if args.watch:
            manager.watch(args.interval)
        else:
            stats = manager.scan_once()
            print_summary(stats)
        return 0
    except (FileNotFoundError, NotADirectoryError, PermissionError, ValueError, OSError) as exc:
        LOGGER.error("%s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
