#!/usr/bin/env python3
"""
GGearing Secure Encryption Tool

Uses Fernet authenticated encryption from the cryptography package.
It protects confidentiality and detects ciphertext tampering.

Examples:
    python ggear_secure.py keygen
    python ggear_secure.py encrypt --text "Hello world"
    python ggear_secure.py decrypt --text "PASTE_TOKEN_HERE"

    python ggear_secure.py encrypt --input notes.txt --output notes.ggear
    python ggear_secure.py decrypt --input notes.ggear --output restored_notes.txt
"""

from __future__ import annotations

import argparse
import os
import secrets
import sys
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken


DEFAULT_KEY_FILE = Path("ggear.key")


def fail(message: str) -> None:
    print(f"Error: {message}", file=sys.stderr)
    raise SystemExit(1)


def atomic_write(path: Path, data: bytes, force: bool = False, private: bool = False) -> None:
    """Write data safely, avoiding partially written output files."""
    path = path.expanduser()

    if not path.parent.exists():
        fail(f"Directory does not exist: {path.parent}")

    if path.exists() and not force:
        fail(f"Output file already exists: {path}. Use --force to overwrite it.")

    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")

    try:
        temporary.write_bytes(data)

        if private:
            try:
                os.chmod(temporary, 0o600)
            except OSError:
                pass

        os.replace(temporary, path)

        if private:
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass

    finally:
        if temporary.exists():
            temporary.unlink(missing_ok=True)


def create_key(key_path: Path, force: bool) -> None:
    key = Fernet.generate_key()
    atomic_write(key_path, key + b"\n", force=force, private=True)

    print(f"Key created: {key_path}")
    print("Keep this file private. Anyone with it can decrypt your data.")


def load_cipher(key_path: Path) -> Fernet:
    key_path = key_path.expanduser()

    try:
        key = key_path.read_bytes().strip()
    except FileNotFoundError:
        fail(f"Key file not found: {key_path}")
    except OSError as exc:
        fail(f"Could not read key file: {exc}")

    try:
        return Fernet(key)
    except (ValueError, TypeError):
        fail("The key file is invalid or damaged.")


def get_input_data(args: argparse.Namespace, decrypting: bool = False) -> bytes:
    if args.text is not None:
        try:
            return args.text.encode("ascii" if decrypting else "utf-8")
        except UnicodeEncodeError:
            fail("Encrypted text tokens must contain ASCII characters only.")

    if args.input is not None:
        try:
            return args.input.expanduser().read_bytes()
        except FileNotFoundError:
            fail(f"Input file not found: {args.input}")
        except OSError as exc:
            fail(f"Could not read input file: {exc}")

    fail("Provide either --text or --input.")


def save_or_print(data: bytes, args: argparse.Namespace, encrypted: bool) -> None:
    if args.output is not None:
        atomic_write(args.output, data, force=args.force)
        print(f"{'Encrypted' if encrypted else 'Decrypted'} file saved to: {args.output}")
        return

    if args.input is not None:
        fail("When using --input, you must also provide --output.")

    try:
        print(data.decode("ascii" if encrypted else "utf-8"))
    except UnicodeDecodeError:
        fail("Decrypted data is binary. Use --output to save it to a file.")


def encrypt(args: argparse.Namespace) -> None:
    cipher = load_cipher(args.key)
    plaintext = get_input_data(args)
    token = cipher.encrypt(plaintext)
    save_or_print(token, args, encrypted=True)


def decrypt(args: argparse.Namespace) -> None:
    cipher = load_cipher(args.key)
    token = get_input_data(args, decrypting=True)

    try:
        plaintext = cipher.decrypt(token)
    except InvalidToken:
        fail("Decryption failed. The key is wrong or the encrypted data was altered.")

    save_or_print(plaintext, args, encrypted=False)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Secure text and file encryption using Fernet."
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    keygen_parser = subparsers.add_parser("keygen", help="Create a new encryption key.")
    keygen_parser.add_argument(
        "--key",
        type=Path,
        default=DEFAULT_KEY_FILE,
        help="Path for the new key file (default: ggear.key).",
    )
    keygen_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing key file.",
    )

    for command in ("encrypt", "decrypt"):
        action_parser = subparsers.add_parser(
            command,
            help=f"{command.capitalize()} text or a file.",
        )

        action_parser.add_argument(
            "--key",
            type=Path,
            default=DEFAULT_KEY_FILE,
            help="Path to the encryption key (default: ggear.key).",
        )

        source = action_parser.add_mutually_exclusive_group(required=True)
        source.add_argument(
            "--text",
            help="Text to encrypt, or encrypted token to decrypt.",
        )
        source.add_argument(
            "--input",
            type=Path,
            help="Input file to encrypt or decrypt.",
        )

        action_parser.add_argument(
            "--output",
            type=Path,
            help="Output file path. Required when using --input.",
        )
        action_parser.add_argument(
            "--force",
            action="store_true",
            help="Overwrite an existing output file.",
        )

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "keygen":
        create_key(args.key, args.force)
    elif args.command == "encrypt":
        encrypt(args)
    elif args.command == "decrypt":
        decrypt(args)


if __name__ == "__main__":
    main()
