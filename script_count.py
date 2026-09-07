#!/usr/bin/env python3
"""
script_count_advanced.py
========================

Modern replacement for Craig Richards' 2012 script_count.py.

Purpose
-------
Recursively inventory a scripts/source-code directory, report language counts,
line counts and disk usage, inspect a development backlog, inspect a GitHub
staging directory, optionally inspect Git repositories, and export the results
to JSON and CSV.

Requirements
------------
Python 3.10+.
No third-party packages are required.

Examples
--------
    python script_count_advanced.py
    python script_count_advanced.py --path "D:\\Scripts"
    python script_count_advanced.py --path ~/scripts --top 20
    python script_count_advanced.py --json report.json --csv report.csv
    python script_count_advanced.py --no-git
    python script_count_advanced.py --list-languages
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable, Sequence


APP_NAME = "Script Inventory"
VERSION = "4.0.0"

DEFAULT_EXCLUDED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "dist",
    "build",
    "coverage",
    ".idea",
    ".vscode",
}

LANGUAGES: dict[str, tuple[str, ...]] = {
    "AutoIt": (".au3",),
    "Batch": (".bat", ".cmd"),
    "C": (".c", ".h"),
    "C++": (".cc", ".cpp", ".cxx", ".hpp", ".hh", ".hxx"),
    "C#": (".cs",),
    "CSS": (".css", ".scss", ".sass", ".less"),
    "Go": (".go",),
    "HTML": (".html", ".htm"),
    "Java": (".java",),
    "JavaScript": (".js", ".mjs", ".cjs", ".jsx"),
    "JSON": (".json",),
    "Kotlin": (".kt", ".kts"),
    "Lua": (".lua",),
    "Perl": (".pl", ".pm"),
    "PHP": (".php", ".phtml"),
    "PowerShell": (".ps1", ".psm1", ".psd1"),
    "Python": (".py", ".pyw"),
    "R": (".r",),
    "Ruby": (".rb",),
    "Rust": (".rs",),
    "Shell": (".sh", ".bash", ".zsh", ".ksh", ".fish"),
    "SQL": (".sql",),
    "Swift": (".swift",),
    "TypeScript": (".ts", ".tsx", ".mts", ".cts"),
    "VBScript": (".vbs",),
    "XML": (".xml",),
    "YAML": (".yaml", ".yml"),
}


@dataclass(slots=True)
class LanguageStats:
    files: int = 0
    lines: int = 0
    bytes: int = 0


@dataclass(slots=True)
class FileRecord:
    path: str
    language: str
    bytes: int
    lines: int
    modified_epoch: float


@dataclass(slots=True)
class GitRepositoryStatus:
    path: str
    branch: str = "unknown"
    dirty_files: int = 0
    untracked_files: int = 0
    ahead: int = 0
    behind: int = 0
    error: str | None = None


@dataclass(slots=True)
class ScanResult:
    root: str
    started_at: str
    duration_seconds: float
    total_files: int
    total_bytes: int
    classified_files: int
    classified_lines: int
    classified_bytes: int
    languages: dict[str, LanguageStats] = field(default_factory=dict)
    largest_files: list[FileRecord] = field(default_factory=list)
    newest_files: list[FileRecord] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="script_count_advanced.py",
        description=(
            "Inventory scripts/source files, show language statistics and "
            "optionally inspect Git repositories and export reports."
        ),
    )

    parser.add_argument(
        "-p",
        "--path",
        type=Path,
        help=(
            "Directory to scan. Defaults to the 'scripts'/'SCRIPTS' environment "
            "variable, otherwise the current directory."
        ),
    )

    parser.add_argument(
        "--dropbox",
        type=Path,
        help="Dropbox root. Defaults to 'dropbox'/'DROPBOX' environment variable.",
    )

    parser.add_argument(
        "--github-dir",
        type=Path,
        help="GitHub staging/repository directory. Defaults to <dropbox>/github.",
    )

    parser.add_argument(
        "--development-dir",
        type=Path,
        help="Development backlog directory. Defaults to <path>/development.",
    )

    parser.add_argument(
        "--development-warning",
        type=int,
        default=10,
        help="Warn when development backlog exceeds this file count. Default: 10.",
    )

    parser.add_argument(
        "--github-warning",
        type=int,
        default=5,
        help="Warn when GitHub staging file count exceeds this value. Default: 5.",
    )

    parser.add_argument(
        "--top",
        type=int,
        default=10,
        help="Number of largest/newest files to show. Default: 10.",
    )

    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="DIR",
        help="Additional directory name to exclude. Repeatable.",
    )

    parser.add_argument(
        "--no-default-excludes",
        action="store_true",
        help="Do not exclude the built-in cache/build/dependency directories.",
    )

    parser.add_argument(
        "--no-git",
        action="store_true",
        help="Skip Git repository discovery/status checks.",
    )

    parser.add_argument(
        "--max-git-repos",
        type=int,
        default=100,
        help="Maximum number of Git repositories to inspect. Default: 100.",
    )

    parser.add_argument(
        "--json",
        dest="json_output",
        type=Path,
        help="Write the full report to a JSON file.",
    )

    parser.add_argument(
        "--csv",
        dest="csv_output",
        type=Path,
        help="Write per-language statistics to a CSV file.",
    )

    parser.add_argument(
        "--clear",
        action="store_true",
        help="Clear the terminal before printing the report.",
    )

    parser.add_argument(
        "--list-languages",
        action="store_true",
        help="List recognized languages/extensions and exit.",
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {VERSION}",
    )

    args = parser.parse_args(argv)

    if args.top < 0:
        parser.error("--top must be 0 or greater.")

    if args.max_git_repos < 0:
        parser.error("--max-git-repos must be 0 or greater.")

    if args.development_warning < 0 or args.github_warning < 0:
        parser.error("Warning thresholds must be 0 or greater.")

    return args


def env_path(*names: str) -> Path | None:
    for name in names:
        value = os.getenv(name)

        if value:
            return Path(
                os.path.expandvars(
                    os.path.expanduser(value)
                )
            )

    return None


def normalize_path(path: Path) -> Path:
    return Path(
        os.path.expandvars(
            os.path.expanduser(str(path))
        )
    ).resolve()


def clear_screen() -> None:
    if not sys.stdout.isatty():
        return

    command = "cls" if os.name == "nt" else "clear"
    os.system(command)


def extension_map() -> dict[str, str]:
    result: dict[str, str] = {}

    for language, extensions in LANGUAGES.items():
        for extension in extensions:
            normalized = extension.lower()

            if not normalized.startswith("."):
                raise ValueError(
                    f"Invalid extension configured: {extension!r}"
                )

            if normalized in result:
                raise ValueError(
                    f"Duplicate extension {normalized!r}: "
                    f"{result[normalized]!r} and {language!r}"
                )

            result[normalized] = language

    return result


def count_binary_lines(
    path: Path,
    chunk_size: int = 1024 * 1024,
) -> int:
    """
    Count physical lines without needing to know the text encoding.

    This counts b'\\n' bytes in chunks and accounts for a final line that does
    not end with a newline. It therefore works for ordinary UTF-8/ASCII source
    files and avoids decode failures on mixed source trees.
    """

    newline_count = 0
    total_read = 0
    last_byte = b""

    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)

            if not chunk:
                break

            total_read += len(chunk)
            newline_count += chunk.count(b"\n")
            last_byte = chunk[-1:]

    if total_read == 0:
        return 0

    if last_byte != b"\n":
        newline_count += 1

    return newline_count


def walk_files(
    root: Path,
    excluded_dirs: set[str],
) -> Iterable[Path]:
    """
    Yield files below root while pruning excluded directory names.

    os.walk is used instead of rglob so excluded trees can be pruned before
    descending into large dependency/build/cache directories.
    """

    for current_root, dirnames, filenames in os.walk(
        root,
        topdown=True,
        followlinks=False,
    ):
        dirnames[:] = [
            name
            for name in dirnames
            if name not in excluded_dirs
        ]

        base = Path(current_root)

        for filename in filenames:
            yield base / filename


def scan_scripts(
    root: Path,
    excluded_dirs: set[str],
    top_n: int,
) -> ScanResult:

    ext_to_language = extension_map()

    started_wall = datetime.now().astimezone().isoformat(
        timespec="seconds"
    )

    started_perf = time.perf_counter()

    language_stats = {
        language: LanguageStats()
        for language in LANGUAGES
    }

    total_files = 0
    total_bytes = 0

    classified_files = 0
    classified_lines = 0
    classified_bytes = 0

    records: list[FileRecord] = []
    errors: list[str] = []

    for file_path in walk_files(
        root,
        excluded_dirs,
    ):
        try:
            stat = file_path.stat()

            if not file_path.is_file():
                continue

        except OSError as exc:
            errors.append(
                f"{file_path}: {exc}"
            )
            continue

        total_files += 1
        total_bytes += stat.st_size

        language = ext_to_language.get(
            file_path.suffix.lower()
        )

        if language is None:
            continue

        try:
            lines = count_binary_lines(
                file_path
            )

        except OSError as exc:
            lines = 0
            errors.append(
                f"{file_path}: line count failed: {exc}"
            )

        stats = language_stats[language]

        stats.files += 1
        stats.lines += lines
        stats.bytes += stat.st_size

        classified_files += 1
        classified_lines += lines
        classified_bytes += stat.st_size

        records.append(
            FileRecord(
                path=str(file_path),
                language=language,
                bytes=stat.st_size,
                lines=lines,
                modified_epoch=stat.st_mtime,
            )
        )

    active_languages = {
        language: stats
        for language, stats in language_stats.items()
        if stats.files > 0
    }

    if top_n:
        largest = sorted(
            records,
            key=lambda item: (
                item.bytes,
                item.path,
            ),
            reverse=True,
        )[:top_n]

        newest = sorted(
            records,
            key=lambda item: (
                item.modified_epoch,
                item.path,
            ),
            reverse=True,
        )[:top_n]

    else:
        largest = []
        newest = []

    return ScanResult(
        root=str(root),
        started_at=started_wall,
        duration_seconds=(
            time.perf_counter() - started_perf
        ),
        total_files=total_files,
        total_bytes=total_bytes,
        classified_files=classified_files,
        classified_lines=classified_lines,
        classified_bytes=classified_bytes,
        languages=active_languages,
        largest_files=largest,
        newest_files=newest,
        errors=errors,
    )


def count_directory_files(
    root: Path | None,
    excluded_dirs: set[str],
) -> tuple[int | None, str | None]:

    if root is None:
        return None, None

    if not root.exists():
        return (
            None,
            f"Directory does not exist: {root}",
        )

    if not root.is_dir():
        return (
            None,
            f"Not a directory: {root}",
        )

    count = 0

    try:
        for _ in walk_files(
            root,
            excluded_dirs,
        ):
            count += 1

    except OSError as exc:
        return None, str(exc)

    return count, None


def find_git_repositories(
    root: Path,
    excluded_dirs: set[str],
    limit: int,
) -> list[Path]:

    if (
        limit == 0
        or not root.exists()
        or not root.is_dir()
    ):
        return []

    repos: list[Path] = []

    for current_root, dirnames, filenames in os.walk(
        root,
        topdown=True,
        followlinks=False,
    ):
        current = Path(current_root)

        is_repo = (
            ".git" in dirnames
            or ".git" in filenames
        )

        if is_repo:
            repos.append(current)

            if len(repos) >= limit:
                break

            # Treat the parent repository as the main status unit.
            dirnames[:] = []

            continue

        dirnames[:] = [
            name
            for name in dirnames
            if (
                name not in excluded_dirs
                and name != ".git"
            )
        ]

    return repos


def run_git(
    repo: Path,
    *args: str,
) -> subprocess.CompletedProcess[str]:

    return subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            *args,
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=15,
        encoding="utf-8",
        errors="replace",
    )


def inspect_git_repository(
    repo: Path,
) -> GitRepositoryStatus:

    status = GitRepositoryStatus(
        path=str(repo)
    )

    try:
        process = run_git(
            repo,
            "status",
            "--porcelain=v2",
            "--branch",
        )

    except (
        OSError,
        subprocess.TimeoutExpired,
    ) as exc:
        status.error = str(exc)
        return status

    if process.returncode != 0:
        status.error = (
            process.stderr.strip()
            or f"git exited {process.returncode}"
        )

        return status

    dirty = 0
    untracked = 0

    for raw_line in process.stdout.splitlines():
        line = raw_line.rstrip()

        if line.startswith(
            "# branch.head "
        ):
            status.branch = line.removeprefix(
                "# branch.head "
            ).strip()

        elif line.startswith(
            "# branch.ab "
        ):
            # Example:
            # # branch.ab +2 -1

            fields = line.split()

            for field in fields:
                if (
                    field.startswith("+")
                    and field[1:].isdigit()
                ):
                    status.ahead = int(
                        field[1:]
                    )

                elif (
                    field.startswith("-")
                    and field[1:].isdigit()
                ):
                    status.behind = int(
                        field[1:]
                    )

        elif line.startswith("? "):
            dirty += 1
            untracked += 1

        elif line.startswith(
            (
                "1 ",
                "2 ",
                "u ",
            )
        ):
            dirty += 1

    status.dirty_files = dirty
    status.untracked_files = untracked

    return status


def inspect_git_tree(
    root: Path | None,
    excluded_dirs: set[str],
    limit: int,
) -> tuple[
    list[GitRepositoryStatus],
    str | None,
]:

    if (
        root is None
        or not root.exists()
        or not root.is_dir()
    ):
        return [], None

    if shutil.which("git") is None:
        return (
            [],
            "Git executable was not found on PATH.",
        )

    repos = find_git_repositories(
        root,
        excluded_dirs,
        limit,
    )

    return (
        [
            inspect_git_repository(repo)
            for repo in repos
        ],
        None,
    )


def human_bytes(
    value: int,
) -> str:

    units = (
        "B",
        "KiB",
        "MiB",
        "GiB",
        "TiB",
    )

    amount = float(value)

    for unit in units:
        if (
            abs(amount) < 1024.0
            or unit == units[-1]
        ):
            if unit == "B":
                return (
                    f"{int(amount)} {unit}"
                )

            return (
                f"{amount:.2f} {unit}"
            )

        amount /= 1024.0

    return f"{value} B"


def human_int(
    value: int,
) -> str:
    return f"{value:,}"


def format_timestamp(
    epoch: float,
) -> str:

    return (
        datetime
        .fromtimestamp(epoch)
        .astimezone()
        .strftime(
            "%Y-%m-%d %H:%M"
        )
    )


def shorten_path(
    path: str,
    root: Path,
    width: int = 72,
) -> str:

    candidate = Path(path)

    try:
        text = str(
            candidate.relative_to(root)
        )

    except ValueError:
        text = str(candidate)

    if len(text) <= width:
        return text

    return (
        "…"
        + text[-(width - 1):]
    )


def print_rule(
    character: str = "─",
    width: int = 78,
) -> None:

    print(
        character * width
    )


def print_languages() -> None:

    print(
        f"{APP_NAME} {VERSION} "
        "— recognized file types"
    )

    print_rule()

    for language in sorted(
        LANGUAGES
    ):
        print(
            f"{language:<16} "
            f"{' '.join(LANGUAGES[language])}"
        )


def print_language_table(
    result: ScanResult,
) -> None:

    print(
        f"{'Language':<16} "
        f"{'Files':>8} "
        f"{'Lines':>12} "
        f"{'Size':>12} "
        f"{'File %':>9}"
    )

    print_rule()

    rows = sorted(
        result.languages.items(),
        key=lambda pair: (
            pair[1].files,
            pair[1].lines,
        ),
        reverse=True,
    )

    for language, stats in rows:

        share = (
            (
                stats.files
                / result.classified_files
            )
            * 100
            if result.classified_files
            else 0.0
        )

        print(
            f"{language:<16} "
            f"{human_int(stats.files):>8} "
            f"{human_int(stats.lines):>12} "
            f"{human_bytes(stats.bytes):>12} "
            f"{share:>8.1f}%"
        )


def print_backlog(
    name: str,
    directory: Path | None,
    count: int | None,
    error: str | None,
    warning_threshold: int,
    high_message: str,
    clear_message: str,
    normal_message: str,
) -> None:

    print(f"{name}:")

    if directory is None:
        print("  Not configured.")
        return

    print(
        f"  Path: {directory}"
    )

    if error:
        print(
            f"  Status: unavailable "
            f"({error})"
        )
        return

    if count is None:
        print(
            "  Status: unavailable"
        )
        return

    print(
        f"  Files: "
        f"{human_int(count)}"
    )

    if count == 0:
        print(
            f"  Status: "
            f"{clear_message}"
        )

    elif count > warning_threshold:
        print(
            f"  Status: WARNING — "
            f"{high_message}"
        )

    else:
        print(
            f"  Status: "
            f"{normal_message}"
        )


def print_git_statuses(
    repos: list[GitRepositoryStatus],
    git_error: str | None,
    root: Path | None,
) -> None:

    print(
        "Git repository status:"
    )

    if root is None:
        print(
            "  Not configured."
        )
        return

    if git_error:
        print(
            f"  Unavailable: "
            f"{git_error}"
        )
        return

    if not repos:
        print(
            "  No Git repositories "
            "discovered."
        )
        return

    for repo in repos:
        repo_name = (
            Path(repo.path).name
            or repo.path
        )

        if repo.error:
            print(
                f"  ! {repo_name}: "
                f"{repo.error}"
            )
            continue

        state = (
            "clean"
            if repo.dirty_files == 0
            else (
                f"{repo.dirty_files} "
                f"changed"
            )
        )

        sync_bits = []

        if repo.ahead:
            sync_bits.append(
                f"ahead {repo.ahead}"
            )

        if repo.behind:
            sync_bits.append(
                f"behind {repo.behind}"
            )

        sync = (
            ", ".join(sync_bits)
            if sync_bits
            else "no reported divergence"
        )

        untracked = (
            (
                f", {repo.untracked_files} "
                f"untracked"
            )
            if repo.untracked_files
            else ""
        )

        print(
            f"  • {repo_name} "
            f"[{repo.branch}] — "
            f"{state}"
            f"{untracked}; "
            f"{sync}"
        )


def print_file_list(
    title: str,
    records: list[FileRecord],
    root: Path,
    mode: str,
) -> None:

    print(title + ":")

    if not records:
        print("  None.")
        return

    for index, record in enumerate(
        records,
        1,
    ):
        path = shorten_path(
            record.path,
            root,
        )

        if mode == "size":
            detail = (
                f"{human_bytes(record.bytes)}, "
                f"{human_int(record.lines)} lines, "
                f"{record.language}"
            )

        elif mode == "date":
            detail = (
                f"{format_timestamp(record.modified_epoch)}, "
                f"{human_int(record.lines)} lines, "
                f"{record.language}"
            )

        else:
            detail = record.language

        print(
            f"  {index:>2}. "
            f"{path} — {detail}"
        )


def print_report(
    result: ScanResult,
    root: Path,
    development_dir: Path | None,
    development_count: int | None,
    development_error: str | None,
    github_dir: Path | None,
    github_count: int | None,
    github_error: str | None,
    git_repos: list[GitRepositoryStatus],
    git_error: str | None,
    args: argparse.Namespace,
) -> None:

    print(
        f"{APP_NAME} {VERSION}"
    )

    print_rule("═")

    print(
        f"Root:              "
        f"{result.root}"
    )

    print(
        f"Started:           "
        f"{result.started_at}"
    )

    print(
        f"Scan time:         "
        f"{result.duration_seconds:.3f} s"
    )

    print(
        f"All files:         "
        f"{human_int(result.total_files)}"
    )

    print(
        f"All-file size:     "
        f"{human_bytes(result.total_bytes)}"
    )

    print(
        f"Recognized source: "
        f"{human_int(result.classified_files)} files"
    )

    print(
        f"Source lines:      "
        f"{human_int(result.classified_lines)}"
    )

    print(
        f"Source size:       "
        f"{human_bytes(result.classified_bytes)}"
    )

    print(
        f"Scan errors:       "
        f"{human_int(len(result.errors))}"
    )

    print()

    print_language_table(
        result
    )

    print()
    print_rule()
    print()

    print_backlog(
        name="Development backlog",
        directory=development_dir,
        count=development_count,
        error=development_error,
        warning_threshold=(
            args.development_warning
        ),
        high_message=(
            "too many files are waiting "
            "to be finished or reviewed."
        ),
        clear_message="all clear.",
        normal_message=(
            "backlog is within the "
            "configured threshold."
        ),
    )

    print()

    print_backlog(
        name="GitHub staging area",
        directory=github_dir,
        count=github_count,
        error=github_error,
        warning_threshold=(
            args.github_warning
        ),
        high_message=(
            "many files are waiting in "
            "the staging area."
        ),
        clear_message="all clear.",
        normal_message=(
            "staging count is within "
            "the configured threshold."
        ),
    )

    print()

    if not args.no_git:
        print_git_statuses(
            git_repos,
            git_error,
            github_dir,
        )

        print()

    print_rule()
    print()

    print_file_list(
        (
            "Largest recognized files "
            f"(top {len(result.largest_files)})"
        ),
        result.largest_files,
        root,
        "size",
    )

    print()

    print_file_list(
        (
            "Most recently modified "
            f"(top {len(result.newest_files)})"
        ),
        result.newest_files,
        root,
        "date",
    )

    if result.errors:
        print()
        print_rule()
        print()

        print(
            "Scan warnings/errors:"
        )

        for message in result.errors[:20]:
            print(
                f"  ! {message}"
            )

        if len(result.errors) > 20:
            print(
                f"  … plus "
                f"{len(result.errors) - 20} "
                f"more."
            )


def report_to_dict(
    result: ScanResult,
    development_dir: Path | None,
    development_count: int | None,
    development_error: str | None,
    github_dir: Path | None,
    github_count: int | None,
    github_error: str | None,
    git_repos: list[GitRepositoryStatus],
    git_error: str | None,
    excluded_dirs: set[str],
) -> dict:

    return {
        "application": {
            "name": APP_NAME,
            "version": VERSION,
        },

        "scan": {
            "root": result.root,
            "started_at": result.started_at,
            "duration_seconds": (
                result.duration_seconds
            ),
            "total_files": (
                result.total_files
            ),
            "total_bytes": (
                result.total_bytes
            ),
            "classified_files": (
                result.classified_files
            ),
            "classified_lines": (
                result.classified_lines
            ),
            "classified_bytes": (
                result.classified_bytes
            ),
            "excluded_directories": sorted(
                excluded_dirs
            ),
            "languages": {
                language: asdict(stats)
                for language, stats
                in result.languages.items()
            },
            "largest_files": [
                asdict(item)
                for item
                in result.largest_files
            ],
            "newest_files": [
                asdict(item)
                for item
                in result.newest_files
            ],
            "errors": result.errors,
        },

        "development": {
            "path": (
                str(development_dir)
                if development_dir
                else None
            ),
            "file_count": (
                development_count
            ),
            "error": (
                development_error
            ),
        },

        "github": {
            "path": (
                str(github_dir)
                if github_dir
                else None
            ),
            "staging_file_count": (
                github_count
            ),
            "staging_error": (
                github_error
            ),
            "git_error": (
                git_error
            ),
            "repositories": [
                asdict(repo)
                for repo
                in git_repos
            ],
        },
    }


def write_json(
    path: Path,
    payload: dict,
) -> None:

    output = normalize_path(
        path
    )

    output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with output.open(
        "w",
        encoding="utf-8",
        newline="\n",
    ) as handle:

        json.dump(
            payload,
            handle,
            indent=2,
            ensure_ascii=False,
        )

        handle.write("\n")


def write_csv(
    path: Path,
    result: ScanResult,
) -> None:

    output = normalize_path(
        path
    )

    output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with output.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as handle:

        writer = csv.writer(
            handle
        )

        writer.writerow(
            [
                "language",
                "files",
                "lines",
                "bytes",
            ]
        )

        for language, stats in sorted(
            result.languages.items()
        ):
            writer.writerow(
                [
                    language,
                    stats.files,
                    stats.lines,
                    stats.bytes,
                ]
            )

        writer.writerow(
            [
                "TOTAL_RECOGNIZED",
                result.classified_files,
                result.classified_lines,
                result.classified_bytes,
            ]
        )


def main(
    argv: Sequence[str] | None = None,
) -> int:

    args = parse_args(
        argv
    )

    if args.list_languages:
        print_languages()
        return 0

    scripts_env = env_path(
        "scripts",
        "SCRIPTS",
    )

    dropbox_env = env_path(
        "dropbox",
        "DROPBOX",
    )

    root = normalize_path(
        args.path
        or scripts_env
        or Path.cwd()
    )

    dropbox = (
        normalize_path(
            args.dropbox
            or dropbox_env
        )
        if (
            args.dropbox
            or dropbox_env
        )
        else None
    )

    if not root.exists():
        print(
            f"ERROR: scan path "
            f"does not exist: {root}",
            file=sys.stderr,
        )

        return 2

    if not root.is_dir():
        print(
            f"ERROR: scan path "
            f"is not a directory: {root}",
            file=sys.stderr,
        )

        return 2

    if args.development_dir:
        development_dir = (
            normalize_path(
                args.development_dir
            )
        )
    else:
        development_dir = (
            root
            / "development"
        )

    if args.github_dir:
        github_dir = (
            normalize_path(
                args.github_dir
            )
        )

    elif dropbox is not None:
        github_dir = (
            dropbox
            / "github"
        )

    elif (
        root / "github"
    ).exists():
        github_dir = (
            root
            / "github"
        )

    else:
        github_dir = None

    excluded_dirs = set(
        args.exclude
    )

    if not args.no_default_excludes:
        excluded_dirs.update(
            DEFAULT_EXCLUDED_DIRS
        )

    if args.clear:
        clear_screen()

    result = scan_scripts(
        root=root,
        excluded_dirs=excluded_dirs,
        top_n=args.top,
    )

    (
        development_count,
        development_error,
    ) = count_directory_files(
        development_dir,
        excluded_dirs,
    )

    (
        github_count,
        github_error,
    ) = count_directory_files(
        github_dir,
        excluded_dirs,
    )

    git_repos: list[
        GitRepositoryStatus
    ] = []

    git_error: str | None = None

    if not args.no_git:
        (
            git_repos,
            git_error,
        ) = inspect_git_tree(
            github_dir,
            excluded_dirs,
            args.max_git_repos,
        )

    print_report(
        result=result,
        root=root,
        development_dir=(
            development_dir
        ),
        development_count=(
            development_count
        ),
        development_error=(
            development_error
        ),
        github_dir=(
            github_dir
        ),
        github_count=(
            github_count
        ),
        github_error=(
            github_error
        ),
        git_repos=(
            git_repos
        ),
        git_error=(
            git_error
        ),
        args=args,
    )

    payload = report_to_dict(
        result=result,
        development_dir=(
            development_dir
        ),
        development_count=(
            development_count
        ),
        development_error=(
            development_error
        ),
        github_dir=(
            github_dir
        ),
        github_count=(
            github_count
        ),
        github_error=(
            github_error
        ),
        git_repos=(
            git_repos
        ),
        git_error=(
            git_error
        ),
        excluded_dirs=(
            excluded_dirs
        ),
    )

    if args.json_output:
        write_json(
            args.json_output,
            payload,
        )

        print(
            "\nJSON report written to: "
            f"{normalize_path(args.json_output)}"
        )

    if args.csv_output:
        write_csv(
            args.csv_output,
            result,
        )

        print(
            "CSV report written to:  "
            f"{normalize_path(args.csv_output)}"
        )

    # A successful scan can still contain individual unreadable files.
    # They are reported but do not make the entire inventory fail.
    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
