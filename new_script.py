#!/usr/bin/env python3
"""
Create a new script from a reusable template.

Examples:
    python new_script.py python my_tool
    python new_script.py bash backup_files
    python new_script.py sql monthly_report
    python new_script.py python my_tool --force
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from pathlib import Path


SCRIPT_TYPES = {
    "python": {"template": "python.cfg", "extension": ".py"},
    "bash": {"template": "bash.cfg", "extension": ".sh"},
    "ksh": {"template": "ksh.cfg", "extension": ".ksh"},
    "sql": {"template": "sql.cfg", "extension": ".sql"},
}


def parse_arguments() -> argparse.Namespace:
    """Read and validate command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Create a new script from a template.",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog="""
Examples:
  %(prog)s python monitor_logs
  %(prog)s bash daily_backup
  %(prog)s sql report_query --force

Required environment variables:
  my_config  Directory containing python.cfg, bash.cfg, etc.
  scripts    Root scripts directory
""",
    )

    parser.add_argument(
        "script_type",
        choices=SCRIPT_TYPES.keys(),
        help="Type of script to create.",
    )
    parser.add_argument(
        "name",
        help="New script name, without the file extension.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite the output file if it already exists.",
    )
    parser.add_argument(
        "--config-dir",
        type=Path,
        help="Override the my_config environment variable.",
    )
    parser.add_argument(
        "--scripts-dir",
        type=Path,
        help="Override the scripts environment variable.",
    )

    return parser.parse_args()


def get_directory(argument_value: Path | None, environment_name: str) -> Path:
    """Get a directory from an argument or environment variable."""
    if argument_value is not None:
        directory = argument_value.expanduser()
    else:
        value = os.getenv(environment_name)
        if not value:
            raise RuntimeError(
                f"Missing required environment variable: {environment_name}"
            )
        directory = Path(value).expanduser()

    if not directory.exists():
        raise RuntimeError(f"Directory does not exist: {directory}")

    if not directory.is_dir():
        raise RuntimeError(f"Path is not a directory: {directory}")

    return directory


def validate_script_name(name: str) -> str:
    """Reject paths and invalid filenames."""
    candidate = Path(name)

    if candidate.name != name:
        raise ValueError("Script name must not contain folders or path separators.")

    if not name.strip():
        raise ValueError("Script name cannot be empty.")

    if name in {".", ".."}:
        raise ValueError("Invalid script name.")

    return name.strip()


def fill_template(template_text: str, output_filename: str) -> str:
    """Update legacy header fields and optional modern placeholders."""
    today = dt.date.today()
    created_date = today.strftime("%d %B %Y")

    replacements = {
        "{script_name}": output_filename,
        "{created_date}": created_date,
        " Script Name\t: ": f" Script Name\t: {output_filename}",
        " Created\t:": f" Created\t: {created_date}",
    }

    for old, new in replacements.items():
        template_text = template_text.replace(old, new)

    return template_text


def create_script(
    script_type: str,
    name: str,
    config_dir: Path,
    scripts_dir: Path,
    force: bool,
) -> Path:
    """Create the requested script from its template."""
    details = SCRIPT_TYPES[script_type]
    output_filename = f"{name}{details['extension']}"

    template_path = config_dir / details["template"]
    output_dir = scripts_dir / "Development"
    output_path = output_dir / output_filename

    if not template_path.is_file():
        raise FileNotFoundError(f"Template file not found: {template_path}")

    output_dir.mkdir(parents=True, exist_ok=True)

    if output_path.exists() and not force:
        raise FileExistsError(
            f"Output file already exists: {output_path}\n"
            "Use --force if you really want to overwrite it."
        )

    template_text = template_path.read_text(encoding="utf-8")
    new_script_text = fill_template(template_text, output_filename)

    output_path.write_text(new_script_text, encoding="utf-8")

    return output_path


def main() -> int:
    """Run the program."""
    args = parse_arguments()

    try:
        script_name = validate_script_name(args.name)
        config_dir = get_directory(args.config_dir, "my_config")
        scripts_dir = get_directory(args.scripts_dir, "scripts")

        output_path = create_script(
            script_type=args.script_type,
            name=script_name,
            config_dir=config_dir,
            scripts_dir=scripts_dir,
            force=args.force,
        )

        print(f"Created successfully:\n  {output_path}")
        return 0

    except (RuntimeError, ValueError, FileNotFoundError, FileExistsError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
