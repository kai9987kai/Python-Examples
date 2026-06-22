#!/usr/bin/env python3
"""
Modern media downloader wrapper.

Requirements:
    - Python 3.9+
    - yt-dlp
    - ffmpeg (recommended; required for merging/extracting audio)
    - aria2c (optional; used for HTTP/HTTPS acceleration)

Use only for media you own or have permission to download.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


DEFAULT_FORMAT = "bv*+ba/b"
DEFAULT_TEMPLATE = "%(uploader|Unknown)s/%(title)s [%(id)s].%(ext)s"


def executable_exists(name: str) -> bool:
    """Return True when an executable is available on PATH."""
    return shutil.which(name) is not None


def require_tool(name: str, required: bool = True) -> bool:
    """Check that a command-line dependency is installed."""
    if executable_exists(name):
        return True

    message = f"'{name}' was not found on PATH."
    if required:
        print(f"Error: {message}", file=sys.stderr)
        sys.exit(2)

    print(f"Warning: {message} Continuing without it.", file=sys.stderr)
    return False


def positive_int(value: str) -> int:
    """Argparse validator for positive integer options."""
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a whole number") from exc

    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")

    return number


def build_command(args: argparse.Namespace, aria2_available: bool) -> list[str]:
    """Build a safe yt-dlp command without shell interpolation."""
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    command = [
        "yt-dlp",
        args.url,
        "--paths", str(output_dir),
        "--output", args.output_template,
        "--windows-filenames",
        "--no-overwrites",
        "--continue",
        "--retries", str(args.retries),
        "--fragment-retries", str(args.retries),
        "--file-access-retries", "3",
        "--retry-sleep", "http:exp=1:60",
        "--concurrent-fragments", str(args.fragments),
        "--newline",
        "--progress",
        "--progress-delta", "1",
    ]

    # Avoid downloading the same item more than once across separate runs.
    if args.archive:
        archive_path = output_dir / ".downloaded-archive.txt"
        command += ["--download-archive", str(archive_path)]

    if args.playlist:
        command.append("--yes-playlist")
    else:
        command.append("--no-playlist")

    if args.audio_only:
        command += [
            "--extract-audio",
            "--audio-format", args.audio_format,
            "--audio-quality", args.audio_quality,
        ]
    else:
        command += [
            "--format", args.format,
            "--merge-output-format", args.merge_format,
        ]

    if args.embed_metadata:
        command += [
            "--embed-metadata",
            "--embed-thumbnail",
            "--convert-thumbnails", "jpg",
        ]

    if args.subtitles:
        command += [
            "--write-subs",
            "--write-auto-subs",
            "--sub-langs", args.subtitle_languages,
            "--embed-subs",
        ]

    # aria2c is useful for direct HTTP/HTTPS downloads. Fragmented streams
    # still use yt-dlp's native downloader and --concurrent-fragments.
    if args.use_aria2 and aria2_available:
        connections = str(args.connections)
        aria_args = (
            f"aria2c:-c "
            f"--file-allocation=none "
            f"-x {connections} "
            f"-s {connections} "
            f"-k 1M"
        )
        command += [
            "--downloader", "http,https:aria2c",
            "--downloader-args", aria_args,
        ]

    if args.cookies_from_browser:
        command += ["--cookies-from-browser", args.cookies_from_browser]

    if args.verbose:
        command.append("--verbose")

    return command


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download media using yt-dlp with optional aria2c acceleration."
    )

    parser.add_argument("url", help="Video, playlist, or supported media URL")

    parser.add_argument(
        "-o", "--output-dir",
        default="downloads",
        help="Folder for downloaded files. Default: downloads",
    )
    parser.add_argument(
        "--output-template",
        default=DEFAULT_TEMPLATE,
        help=f"yt-dlp filename template. Default: {DEFAULT_TEMPLATE}",
    )

    parser.add_argument(
        "-f", "--format",
        default=DEFAULT_FORMAT,
        help=f"yt-dlp format selector. Default: {DEFAULT_FORMAT}",
    )
    parser.add_argument(
        "--merge-format",
        default="mp4",
        choices=["mp4", "mkv", "webm"],
        help="Container used when video and audio are merged. Default: mp4",
    )

    parser.add_argument(
        "--playlist",
        action="store_true",
        help="Download every item in a playlist instead of only one item.",
    )
    parser.add_argument(
        "--no-archive",
        dest="archive",
        action="store_false",
        help="Allow files to be downloaded again.",
    )
    parser.set_defaults(archive=True)

    parser.add_argument(
        "--audio-only",
        action="store_true",
        help="Extract audio instead of downloading video.",
    )
    parser.add_argument(
        "--audio-format",
        default="mp3",
        choices=["best", "aac", "alac", "flac", "m4a", "mp3", "opus", "vorbis", "wav"],
        help="Audio format when using --audio-only. Default: mp3",
    )
    parser.add_argument(
        "--audio-quality",
        default="192K",
        help="Audio bitrate/quality for extraction. Default: 192K",
    )

    parser.add_argument(
        "--connections",
        type=positive_int,
        default=8,
        help="aria2c connections per server. Default: 8",
    )
    parser.add_argument(
        "--fragments",
        type=positive_int,
        default=8,
        help="Native concurrent fragment downloads. Default: 8",
    )
    parser.add_argument(
        "--retries",
        type=positive_int,
        default=10,
        help="Network and fragment retry count. Default: 10",
    )
    parser.add_argument(
        "--no-aria2",
        dest="use_aria2",
        action="store_false",
        help="Disable aria2c even when installed.",
    )
    parser.set_defaults(use_aria2=True)

    parser.add_argument(
        "--embed-metadata",
        action="store_true",
        help="Embed title, thumbnail, and available metadata into final files.",
    )
    parser.add_argument(
        "--subtitles",
        action="store_true",
        help="Download and embed subtitles where possible.",
    )
    parser.add_argument(
        "--subtitle-languages",
        default="en.*,en",
        help="Subtitle language selector. Default: en.*,en",
    )
    parser.add_argument(
        "--cookies-from-browser",
        choices=["chrome", "chromium", "firefox", "edge", "brave", "opera", "safari"],
        help="Read cookies from a local browser for content you are authorised to access.",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Show detailed yt-dlp diagnostics.",
    )

    return parser.parse_args()


def main() -> int:
    args = parse_args()

    require_tool("yt-dlp")
    ffmpeg_available = require_tool("ffmpeg", required=False)
    aria2_available = require_tool("aria2c", required=False)

    if (args.audio_only or args.embed_metadata) and not ffmpeg_available:
        print(
            "Error: ffmpeg is required for audio extraction, merging, "
            "thumbnail conversion, and metadata embedding.",
            file=sys.stderr,
        )
        return 2

    command = build_command(args, aria2_available)

    print("\nStarting download...\n")
    try:
        result = subprocess.run(command, check=False)
    except KeyboardInterrupt:
        print("\nDownload cancelled by user.", file=sys.stderr)
        return 130
    except OSError as error:
        print(f"\nCould not start yt-dlp: {error}", file=sys.stderr)
        return 1

    if result.returncode == 0:
        print("\nDownload complete.")
    else:
        print(
            f"\nyt-dlp exited with code {result.returncode}. "
            "Try --verbose for diagnostic output.",
            file=sys.stderr,
        )

    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
