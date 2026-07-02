#!/usr/bin/env python3
"""
Multiplication Table Generator
------------------------------
Examples:
    python multiplication_table.py 12 12
    python multiplication_table.py 10 15 --format markdown
    python multiplication_table.py 20 20 --start 3 --output table.csv --format csv
    python multiplication_table.py --gui
"""

from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


MAX_SIZE = 200  # Prevent accidentally generating enormous tables.


@dataclass(frozen=True)
class TableSettings:
    rows: int = 12
    columns: int = 12
    start: int = 1

    def validate(self) -> None:
        if not (1 <= self.rows <= MAX_SIZE):
            raise ValueError(f"rows must be between 1 and {MAX_SIZE}.")
        if not (1 <= self.columns <= MAX_SIZE):
            raise ValueError(f"columns must be between 1 and {MAX_SIZE}.")
        if self.start < 0:
            raise ValueError("start must be 0 or greater.")

    @property
    def row_values(self) -> range:
        return range(self.start, self.start + self.rows)

    @property
    def column_values(self) -> range:
        return range(self.start, self.start + self.columns)


def make_matrix(settings: TableSettings) -> list[list[int | str]]:
    """Create a matrix with header labels and multiplication results."""
    settings.validate()
    matrix: list[list[int | str]] = [["×", *settings.column_values]]

    for row_number in settings.row_values:
        matrix.append([row_number, *(row_number * column_number
                                     for column_number in settings.column_values)])
    return matrix


def matrix_to_plain_text(matrix: list[list[int | str]]) -> str:
    """Format a matrix as an aligned terminal-friendly table."""
    string_matrix = [[str(cell) for cell in row] for row in matrix]
    widths = [
        max(len(row[column]) for row in string_matrix)
        for column in range(len(string_matrix[0]))
    ]

    def separator(fill: str = "-") -> str:
        return "+" + "+".join(fill * (width + 2) for width in widths) + "+"

    lines = [separator()]
    for index, row in enumerate(string_matrix):
        line = "| " + " | ".join(
            cell.rjust(widths[column]) for column, cell in enumerate(row)
        ) + " |"
        lines.append(line)
        if index == 0:
            lines.append(separator("="))
    lines.append(separator())
    return "\n".join(lines)


def matrix_to_markdown(matrix: list[list[int | str]]) -> str:
    """Format a matrix as a Markdown table."""
    string_matrix = [[str(cell) for cell in row] for row in matrix]
    header = "| " + " | ".join(string_matrix[0]) + " |"
    divider = "| " + " | ".join("---" for _ in string_matrix[0]) + " |"
    body = ["| " + " | ".join(row) + " |" for row in string_matrix[1:]]
    return "\n".join([header, divider, *body])


def save_csv(matrix: list[list[int | str]], output_path: Path) -> None:
    """Save the table as a UTF-8 CSV file."""
    with output_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerows(matrix)


def save_text(text: str, output_path: Path) -> None:
    """Save plain text or Markdown safely."""
    output_path.write_text(text + "\n", encoding="utf-8")


def generate_output(settings: TableSettings, output_format: str) -> str:
    matrix = make_matrix(settings)
    if output_format == "markdown":
        return matrix_to_markdown(matrix)
    return matrix_to_plain_text(matrix)


def launch_gui() -> None:
    """Launch a dependency-free Tkinter interface."""
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    root = tk.Tk()
    root.title("Multiplication Table Generator")
    root.minsize(760, 520)

    frame = ttk.Frame(root, padding=16)
    frame.pack(fill="both", expand=True)

    rows_var = tk.StringVar(value="12")
    columns_var = tk.StringVar(value="12")
    start_var = tk.StringVar(value="1")
    format_var = tk.StringVar(value="Plain text")

    controls = ttk.LabelFrame(frame, text="Table settings", padding=12)
    controls.pack(fill="x")

    fields = [
        ("Rows", rows_var),
        ("Columns", columns_var),
        ("Start value", start_var),
    ]
    for column, (label, variable) in enumerate(fields):
        ttk.Label(controls, text=label).grid(row=0, column=column * 2, sticky="w", padx=(0, 6))
        ttk.Spinbox(
            controls,
            from_=0 if label == "Start value" else 1,
            to=MAX_SIZE,
            textvariable=variable,
            width=8,
        ).grid(row=0, column=column * 2 + 1, sticky="w", padx=(0, 18))

    ttk.Label(controls, text="Display format").grid(row=1, column=0, sticky="w", pady=(12, 0))
    format_dropdown = ttk.Combobox(
        controls,
        values=("Plain text", "Markdown"),
        textvariable=format_var,
        state="readonly",
        width=14,
    )
    format_dropdown.grid(row=1, column=1, sticky="w", pady=(12, 0))

    output = tk.Text(frame, wrap="none", font=("Courier New", 10))
    output.pack(fill="both", expand=True, pady=(16, 8))

    status_var = tk.StringVar(value="Choose table settings, then select Generate.")
    ttk.Label(frame, textvariable=status_var).pack(anchor="w")

    def current_settings() -> TableSettings:
        try:
            settings = TableSettings(
                rows=int(rows_var.get()),
                columns=int(columns_var.get()),
                start=int(start_var.get()),
            )
            settings.validate()
            return settings
        except ValueError as error:
            raise ValueError("Rows, columns, and start value must be valid whole numbers. "
                             + str(error)) from error

    def get_format() -> str:
        return "markdown" if format_var.get() == "Markdown" else "plain"

    def generate() -> None:
        try:
            rendered = generate_output(current_settings(), get_format())
        except ValueError as error:
            messagebox.showerror("Invalid settings", str(error), parent=root)
            return

        output.delete("1.0", "end")
        output.insert("1.0", rendered)
        status_var.set("Table generated.")

    def copy_to_clipboard() -> None:
        rendered = output.get("1.0", "end-1c")
        if not rendered:
            generate()
            rendered = output.get("1.0", "end-1c")
        root.clipboard_clear()
        root.clipboard_append(rendered)
        status_var.set("Copied to clipboard.")

    def export() -> None:
        try:
            settings = current_settings()
            output_format = get_format()
            matrix = make_matrix(settings)
        except ValueError as error:
            messagebox.showerror("Invalid settings", str(error), parent=root)
            return

        default_extension = ".md" if output_format == "markdown" else ".txt"
        file_types = (
            [("Markdown file", "*.md"), ("Text file", "*.txt")]
            if output_format == "markdown"
            else [("Text file", "*.txt"), ("CSV file", "*.csv")]
        )
        destination = filedialog.asksaveasfilename(
            parent=root,
            title="Export multiplication table",
            defaultextension=default_extension,
            filetypes=file_types,
        )
        if not destination:
            return

        path = Path(destination)
        try:
            if path.suffix.lower() == ".csv":
                save_csv(matrix, path)
            else:
                save_text(generate_output(settings, output_format), path)
        except OSError as error:
            messagebox.showerror("Could not save file", str(error), parent=root)
            return

        status_var.set(f"Saved to {path.name}")

    actions = ttk.Frame(frame)
    actions.pack(fill="x", pady=(8, 0))
    ttk.Button(actions, text="Generate", command=generate).pack(side="left")
    ttk.Button(actions, text="Copy", command=copy_to_clipboard).pack(side="left", padx=8)
    ttk.Button(actions, text="Export", command=export).pack(side="left")

    generate()
    root.mainloop()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate a formatted multiplication table.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "rows",
        nargs="?",
        type=int,
        default=12,
        help="How many horizontal multiplier values to show.",
    )
    parser.add_argument(
        "columns",
        nargs="?",
        type=int,
        default=12,
        help="How many vertical multiplier values to show.",
    )
    parser.add_argument(
        "--start",
        type=int,
        default=1,
        help="The first value for both axes.",
    )
    parser.add_argument(
        "--format",
        choices=("plain", "markdown", "csv"),
        default="plain",
        help="Output format.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional destination file. Prints to the terminal when omitted.",
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        help="Open the desktop interface instead of printing a table.",
    )
    return parser


def main(arguments: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(arguments)

    if args.gui:
        launch_gui()
        return 0

    settings = TableSettings(rows=args.rows, columns=args.columns, start=args.start)
    try:
        settings.validate()
        matrix = make_matrix(settings)
    except ValueError as error:
        parser.error(str(error))

    if args.format == "csv":
        if args.output:
            save_csv(matrix, args.output)
            print(f"Saved CSV table to: {args.output}")
        else:
            writer = csv.writer(sys.stdout)
            writer.writerows(matrix)
        return 0

    rendered = generate_output(settings, args.format)
    if args.output:
        save_text(rendered, args.output)
        print(f"Saved {args.format} table to: {args.output}")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
