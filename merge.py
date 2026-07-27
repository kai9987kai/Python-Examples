#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Robustly merge multiple CSV files into one output file.

Original concept/author: zhangshuyx@gmail.com
Modernized implementation: safe, schema-aware, atomic CSV merger.

Features:
- deterministic file ordering
- recursive discovery
- automatic delimiter detection
- strict or union schema handling
- optional duplicate-row removal
- optional source-file column
- atomic output replacement
- dry-run and verbose reporting
- standard-library only
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence, TextIO


SUPPORTED_SNIFF_DELIMITERS = ",;\t|"


class MergeError(RuntimeError):
    """Raised when CSV files cannot be merged safely."""


@dataclass(frozen=True)
class InputCsv:
    """Metadata collected for one input CSV file."""

    path: Path
    dialect: type[csv.Dialect] | csv.Dialect
    header: tuple[str, ...] | None


@dataclass
class MergeStats:
    """Counters reported after a merge operation."""

    files_discovered: int = 0
    files_processed: int = 0
    empty_files: int = 0
    rows_read: int = 0
    rows_written: int = 0
    duplicates_skipped: int = 0


def eprint(*values: object) -> None:
    """Print a message to stderr."""

    print(*values, file=sys.stderr)


def decode_delimiter(value: str) -> str | None:
    """Convert a CLI delimiter value into one character or auto-detection."""

    aliases = {
        "auto": None,
        "comma": ",",
        "semicolon": ";",
        "tab": "\t",
        "pipe": "|",
    }
    lowered = value.lower()
    if lowered in aliases:
        return aliases[lowered]

    decoded = bytes(value, "utf-8").decode("unicode_escape")
    if len(decoded) != 1:
        raise argparse.ArgumentTypeError(
            "delimiter must be one character or one of: auto, comma, "
            "semicolon, tab, pipe"
        )
    return decoded


def is_hidden(path: Path, root: Path) -> bool:
    """Return True when any component below root begins with a dot."""

    try:
        relative = path.relative_to(root)
    except ValueError:
        relative = path
    return any(part.startswith(".") for part in relative.parts)


def matches_any_glob(path: Path, root: Path, patterns: Sequence[str]) -> bool:
    """Return True if a relative path matches any supplied glob pattern."""

    relative = path.relative_to(root)
    return any(relative.match(pattern) or path.match(pattern) for pattern in patterns)


def discover_csv_files(
    root: Path,
    output_path: Path,
    recursive: bool,
    include_hidden: bool,
    exclude_patterns: Sequence[str],
) -> list[Path]:
    """Find input CSV files in a stable, case-insensitive order."""

    iterator: Iterable[Path] = root.rglob("*") if recursive else root.iterdir()
    output_resolved = output_path.resolve()
    files: list[Path] = []

    for path in iterator:
        if not path.is_file() or path.suffix.casefold() != ".csv":
            continue
        if path.resolve() == output_resolved:
            continue
        if not include_hidden and is_hidden(path, root):
            continue
        if matches_any_glob(path, root, exclude_patterns):
            continue
        files.append(path)

    return sorted(
        files,
        key=lambda item: item.relative_to(root).as_posix().casefold(),
    )


def sniff_dialect(
    path: Path,
    encoding: str,
    errors: str,
    forced_delimiter: str | None,
) -> type[csv.Dialect] | csv.Dialect:
    """Determine how an input CSV is delimited."""

    if forced_delimiter is not None:
        class ForcedDialect(csv.excel):
            delimiter = forced_delimiter

        return ForcedDialect

    with path.open("r", encoding=encoding, errors=errors, newline="") as handle:
        sample = handle.read(64 * 1024)

    if not sample:
        return csv.excel

    try:
        return csv.Sniffer().sniff(sample, delimiters=SUPPORTED_SNIFF_DELIMITERS)
    except csv.Error:
        return csv.excel


def open_reader(
    path: Path,
    dialect: type[csv.Dialect] | csv.Dialect,
    encoding: str,
    errors: str,
) -> tuple[TextIO, csv._reader]:
    """Open a CSV file and construct its reader."""

    handle = path.open("r", encoding=encoding, errors=errors, newline="")
    return handle, csv.reader(handle, dialect)


def inspect_inputs(
    paths: Sequence[Path],
    encoding: str,
    errors: str,
    input_delimiter: str | None,
    has_header: bool,
    schema: str,
) -> tuple[list[InputCsv], list[str], int]:
    """Inspect input dialects and headers before creating output."""

    inspected: list[InputCsv] = []
    union_header: list[str] = []
    union_seen: set[str] = set()
    strict_header: tuple[str, ...] | None = None
    empty_files = 0

    for path in paths:
        dialect = sniff_dialect(path, encoding, errors, input_delimiter)
        header: tuple[str, ...] | None = None

        handle, reader = open_reader(path, dialect, encoding, errors)
        try:
            first_row = next(reader, None)
        finally:
            handle.close()

        if first_row is None:
            empty_files += 1
            inspected.append(InputCsv(path=path, dialect=dialect, header=None))
            continue

        if has_header:
            header = tuple(first_row)
            if not header:
                raise MergeError(f"{path}: header row is empty")
            if len(set(header)) != len(header):
                duplicates = sorted({name for name in header if header.count(name) > 1})
                raise MergeError(
                    f"{path}: duplicate header name(s): {', '.join(repr(x) for x in duplicates)}"
                )

            if schema == "strict":
                if strict_header is None:
                    strict_header = header
                elif header != strict_header:
                    raise MergeError(
                        f"Header mismatch in {path}.\n"
                        f"Expected: {list(strict_header)!r}\n"
                        f"Found:    {list(header)!r}\n"
                        "Use --schema union to merge differing columns."
                    )
            else:
                for column in header:
                    if column not in union_seen:
                        union_seen.add(column)
                        union_header.append(column)

        inspected.append(InputCsv(path=path, dialect=dialect, header=header))

    if has_header:
        final_header = list(strict_header or ()) if schema == "strict" else union_header
    else:
        final_header = []

    return inspected, final_header, empty_files


def source_label(path: Path, root: Path) -> str:
    """Return a portable source path relative to the merge root."""

    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.name


def merge_csv_files(
    inputs: Sequence[InputCsv],
    root: Path,
    output_path: Path,
    encoding: str,
    errors: str,
    output_delimiter: str,
    lineterminator: str,
    has_header: bool,
    schema: str,
    deduplicate: bool,
    include_source: bool,
    source_column_name: str,
    verbose: bool,
    initial_empty_files: int,
) -> MergeStats:
    """Merge inspected CSV files and atomically replace the destination."""

    stats = MergeStats(
        files_discovered=len(inputs),
        empty_files=initial_empty_files,
    )

    final_header: list[str] = []
    if has_header:
        if schema == "strict":
            first_header = next((item.header for item in inputs if item.header is not None), None)
            final_header = list(first_header or ())
        else:
            seen: set[str] = set()
            for item in inputs:
                for column in item.header or ():
                    if column not in seen:
                        seen.add(column)
                        final_header.append(column)

        if include_source:
            if source_column_name in final_header:
                raise MergeError(
                    f"source column {source_column_name!r} already exists; "
                    "choose another name with --source-column-name"
                )
            final_header.insert(0, source_column_name)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    seen_rows: set[tuple[str, ...]] | None = set() if deduplicate else None

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding=encoding,
            errors=errors,
            newline="",
            prefix=f".{output_path.name}.",
            suffix=".tmp",
            dir=output_path.parent,
            delete=False,
        ) as temporary:
            temporary_name = temporary.name
            writer = csv.writer(
                temporary,
                delimiter=output_delimiter,
                quoting=csv.QUOTE_MINIMAL,
                lineterminator=lineterminator,
            )

            if has_header and final_header:
                writer.writerow(final_header)

            for item in inputs:
                if item.header is None and has_header:
                    if verbose:
                        eprint(f"Skipping empty file: {item.path}")
                    continue

                if verbose:
                    eprint(f"Reading: {item.path}")

                handle, reader = open_reader(item.path, item.dialect, encoding, errors)
                try:
                    if has_header:
                        next(reader, None)

                    file_had_row = False
                    for line_number, row in enumerate(reader, start=2 if has_header else 1):
                        if not row:
                            continue

                        file_had_row = True
                        stats.rows_read += 1

                        if has_header:
                            source_header = list(item.header or ())
                            if len(row) != len(source_header):
                                raise MergeError(
                                    f"{item.path}:{line_number}: expected {len(source_header)} "
                                    f"fields but found {len(row)}"
                                )

                            if schema == "union":
                                row_map = dict(zip(source_header, row))
                                output_columns = final_header[1:] if include_source else final_header
                                output_row = [row_map.get(column, "") for column in output_columns]
                            else:
                                output_row = list(row)
                        else:
                            output_row = list(row)

                        if include_source:
                            output_row.insert(0, source_label(item.path, root))

                        row_key = tuple(output_row)
                        if seen_rows is not None:
                            if row_key in seen_rows:
                                stats.duplicates_skipped += 1
                                continue
                            seen_rows.add(row_key)

                        writer.writerow(output_row)
                        stats.rows_written += 1

                    if file_had_row or (has_header and item.header is not None):
                        stats.files_processed += 1
                finally:
                    handle.close()

            temporary.flush()
            os.fsync(temporary.fileno())

        os.replace(temporary_name, output_path)
        temporary_name = None
        return stats
    finally:
        if temporary_name is not None:
            try:
                Path(temporary_name).unlink(missing_ok=True)
            except OSError:
                pass


def build_parser() -> argparse.ArgumentParser:
    """Create the command-line parser."""

    parser = argparse.ArgumentParser(
        description="Merge CSV files safely using only Python's standard library.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="directory containing input CSV files",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="result.csv",
        help="output CSV path; relative paths are resolved inside DIRECTORY",
    )
    parser.add_argument(
        "-r",
        "--recursive",
        action="store_true",
        help="search subdirectories recursively",
    )
    parser.add_argument(
        "--schema",
        choices=("strict", "union"),
        default="strict",
        help="strict requires identical headers; union combines differing columns",
    )
    parser.add_argument(
        "--no-header",
        action="store_true",
        help="treat every row as data and do not write a header",
    )
    parser.add_argument(
        "--deduplicate",
        action="store_true",
        help="remove duplicate output rows while preserving first occurrence",
    )
    parser.add_argument(
        "--source-column",
        action="store_true",
        help="prepend the relative input filename to each output row",
    )
    parser.add_argument(
        "--source-column-name",
        default="source_file",
        help="header name used by --source-column",
    )
    parser.add_argument(
        "--input-delimiter",
        type=decode_delimiter,
        default=None,
        metavar="DELIMITER",
        help="auto, comma, semicolon, tab, pipe, or one literal character",
    )
    parser.add_argument(
        "--output-delimiter",
        type=decode_delimiter,
        default=",",
        metavar="DELIMITER",
        help="comma, semicolon, tab, pipe, or one literal character",
    )
    parser.add_argument(
        "--encoding",
        default="utf-8-sig",
        help="text encoding used for input and output",
    )
    parser.add_argument(
        "--encoding-errors",
        choices=("strict", "replace", "ignore"),
        default="strict",
        help="how decoding and encoding errors are handled",
    )
    parser.add_argument(
        "--line-ending",
        choices=("lf", "crlf"),
        default="lf",
        help="line ending written to the output file",
    )
    parser.add_argument(
        "--include-hidden",
        action="store_true",
        help="include dotfiles and files inside hidden directories",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="GLOB",
        help="exclude a path glob; may be supplied multiple times",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="show which files would be merged without writing output",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="show each file as it is processed",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command-line application."""

    parser = build_parser()
    args = parser.parse_args(argv)

    root = Path(args.directory).expanduser().resolve()
    if not root.exists():
        parser.error(f"directory does not exist: {root}")
    if not root.is_dir():
        parser.error(f"not a directory: {root}")

    output_path = Path(args.output).expanduser()
    if not output_path.is_absolute():
        output_path = root / output_path
    output_path = output_path.resolve()

    if args.output_delimiter is None:
        parser.error("--output-delimiter cannot be auto")

    try:
        paths = discover_csv_files(
            root=root,
            output_path=output_path,
            recursive=args.recursive,
            include_hidden=args.include_hidden,
            exclude_patterns=args.exclude,
        )

        if not paths:
            raise MergeError(f"no CSV files found in {root}")

        if args.dry_run:
            print(f"Root:   {root}")
            print(f"Output: {output_path}")
            print(f"Files:  {len(paths)}")
            for path in paths:
                print(f"  - {source_label(path, root)}")
            return 0

        inputs, _, empty_files = inspect_inputs(
            paths=paths,
            encoding=args.encoding,
            errors=args.encoding_errors,
            input_delimiter=args.input_delimiter,
            has_header=not args.no_header,
            schema=args.schema,
        )

        stats = merge_csv_files(
            inputs=inputs,
            root=root,
            output_path=output_path,
            encoding=args.encoding,
            errors=args.encoding_errors,
            output_delimiter=args.output_delimiter,
            lineterminator="\n" if args.line_ending == "lf" else "\r\n",
            has_header=not args.no_header,
            schema=args.schema,
            deduplicate=args.deduplicate,
            include_source=args.source_column,
            source_column_name=args.source_column_name,
            verbose=args.verbose,
            initial_empty_files=empty_files,
        )

        print(f"Merged CSV written to: {output_path}")
        print(f"Files discovered:      {stats.files_discovered}")
        print(f"Files processed:       {stats.files_processed}")
        print(f"Empty files skipped:   {stats.empty_files}")
        print(f"Rows read:             {stats.rows_read}")
        print(f"Rows written:          {stats.rows_written}")
        if args.deduplicate:
            print(f"Duplicates skipped:    {stats.duplicates_skipped}")
        return 0

    except (MergeError, OSError, UnicodeError, csv.Error) as exc:
        eprint(f"Error: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
