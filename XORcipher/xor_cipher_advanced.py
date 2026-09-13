#!/usr/bin/env python3
"""
Advanced XOR + authenticated encryption utility.

This module intentionally separates two very different concepts:

1. XORCipher
   A fast, reversible XOR transform useful for education, experiments,
   lightweight obfuscation, fixtures, and reversible byte transforms.
   XOR IS NOT cryptographically secure and should not be used to protect
   secrets against an attacker.

2. SecureCipher
   Password-based authenticated encryption using AES-256-GCM with scrypt
   key derivation. This is the appropriate layer in this module for real
   confidentiality + integrity protection.

Highlights compared with the 2017 implementation:
- Python 3 type-safe API.
- Correct integer-key normalization (low 8 bits, so 256 -> 0).
- Supports integer, text, bytes, bytearray, and memoryview XOR keys.
- Repeating multi-byte XOR keys.
- Safe Base64/hex helpers for text transport.
- UTF-8 Unicode round trips.
- Binary-safe, chunked file processing for arbitrary files.
- Key-stream continuity across chunk boundaries.
- Atomic file publishing to avoid partial/corrupt outputs.
- Source/destination collision protection.
- Authenticated AES-256-GCM secure mode.
- scrypt password KDF with per-message random salt.
- Fresh random 96-bit GCM nonce for every secure encryption.
- Authenticated container metadata.
- Tamper/wrong-password detection.
- CLI and built-in self-test.

Secure mode dependency:
    pip install cryptography

Example:
    xor = XORCipher("demo-key")
    token = xor.encrypt_text("hello 🌍")
    assert xor.decrypt_text(token) == "hello 🌍"

    secure = SecureCipher("correct horse battery staple")
    protected = secure.encrypt_text("secret")
    assert secure.decrypt_text(protected) == "secret"

Security note:
    XORCipher is deliberately retained as an educational/obfuscation
    primitive. Repeating XOR is vulnerable to known-plaintext, frequency,
    and key-recovery attacks. Use SecureCipher for confidential data.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import getpass
import os
import secrets
import struct
import sys
import tempfile
from pathlib import Path
from typing import Callable, Iterable, Sequence, TypeAlias

try:
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

    _CRYPTOGRAPHY_AVAILABLE = True
except ImportError:  # pragma: no cover - depends on external environment
    InvalidTag = Exception  # type: ignore[assignment,misc]
    Cipher = algorithms = modes = AESGCM = Scrypt = None  # type: ignore[assignment]
    _CRYPTOGRAPHY_AVAILABLE = False


BytesLike: TypeAlias = bytes | bytearray | memoryview
XORKey: TypeAlias = int | str | BytesLike
Pathish: TypeAlias = str | os.PathLike[str]
ProgressCallback: TypeAlias = Callable[[int, int], None]


class CipherError(Exception):
    """Base exception for cipher and container errors."""


class CipherFormatError(CipherError):
    """Raised when encrypted data has an invalid or unsupported format."""


class IntegrityError(CipherError):
    """Raised when authenticated decryption detects tampering/wrong credentials."""


class MissingDependencyError(CipherError):
    """Raised when secure mode is requested without ``cryptography`` installed."""


def _as_bytes(data: BytesLike, *, name: str = "data") -> bytes:
    if isinstance(data, bytes):
        return data
    if isinstance(data, (bytearray, memoryview)):
        return bytes(data)
    raise TypeError(f"{name} must be bytes, bytearray, or memoryview")


def _validate_chunk_size(chunk_size: int) -> int:
    if isinstance(chunk_size, bool) or not isinstance(chunk_size, int):
        raise TypeError("chunk_size must be an integer")
    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than zero")
    return chunk_size


def _paths_collide(source: Path, destination: Path) -> bool:
    """Return True when paths refer, or would resolve, to the same path."""
    try:
        if source.exists() and destination.exists() and os.path.samefile(source, destination):
            return True
    except OSError:
        pass

    src = os.path.normcase(os.path.abspath(os.fspath(source)))
    dst = os.path.normcase(os.path.abspath(os.fspath(destination)))
    return src == dst


def _prepare_destination(source: Path, destination: Path, *, overwrite: bool) -> None:
    if _paths_collide(source, destination):
        raise ValueError("source and destination must be different files")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and not overwrite:
        raise FileExistsError(f"destination already exists: {destination}")


def _atomic_temp_path(destination: Path) -> Path:
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=os.fspath(destination.parent),
    )
    os.close(fd)
    return Path(temp_name)


def _publish_atomic(temp_path: Path, destination: Path) -> None:
    os.replace(temp_path, destination)


def _safe_unlink(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _notify_progress(
    callback: ProgressCallback | None,
    processed: int,
    total: int,
) -> None:
    if callback is not None:
        callback(processed, total)


class XORCipher:
    """
    Repeating-key XOR transform with binary-safe and text-safe helpers.

    Parameters
    ----------
    key:
        ``int`` keys use the low 8 bits (``key & 0xFF``). A ``str`` key is
        UTF-8 encoded. Byte-like keys are used verbatim and may be multiple
        bytes long. Empty byte/text keys and negative integer keys are rejected.

    Notes
    -----
    Encryption and decryption are the same XOR operation. This class is NOT
    secure cryptography; it exists for education and reversible obfuscation.
    """

    DEFAULT_CHUNK_SIZE = 1024 * 1024

    def __init__(self, key: XORKey = 1):
        self._key = self._normalize_key(key)

    @staticmethod
    def _normalize_key(key: XORKey) -> bytes:
        if isinstance(key, bool):
            # bool is an int subclass; accepting it would be surprising.
            raise TypeError("XOR key must not be a boolean")
        if isinstance(key, int):
            if key < 0:
                raise ValueError("integer XOR key must be non-negative")
            return bytes((key & 0xFF,))
        if isinstance(key, str):
            encoded = key.encode("utf-8")
            if not encoded:
                raise ValueError("XOR key must not be empty")
            return encoded
        if isinstance(key, (bytes, bytearray, memoryview)):
            encoded = bytes(key)
            if not encoded:
                raise ValueError("XOR key must not be empty")
            return encoded
        raise TypeError("XOR key must be int, str, bytes, bytearray, or memoryview")

    @property
    def key_bytes(self) -> bytes:
        """Return an immutable copy of the normalized XOR key."""
        return bytes(self._key)

    @property
    def key_length(self) -> int:
        """Return key length in bytes."""
        return len(self._key)

    def __repr__(self) -> str:
        # Do not leak a textual key in repr; length is enough for diagnostics.
        return f"{type(self).__name__}(key_length={self.key_length})"

    def _resolve_key(self, key: XORKey | None) -> bytes:
        return self._key if key is None else self._normalize_key(key)

    def transform(
        self,
        data: BytesLike,
        key: XORKey | None = None,
        *,
        offset: int = 0,
    ) -> bytes:
        """XOR ``data`` with the repeating key starting at byte ``offset``."""
        raw = _as_bytes(data)
        if isinstance(offset, bool) or not isinstance(offset, int):
            raise TypeError("offset must be an integer")
        if offset < 0:
            raise ValueError("offset must be non-negative")

        key_bytes = self._resolve_key(key)
        key_len = len(key_bytes)
        start = offset % key_len

        # Local bindings reduce attribute/index lookup overhead in the hot loop.
        return bytes(
            value ^ key_bytes[(start + index) % key_len]
            for index, value in enumerate(raw)
        )

    def encrypt(self, data: BytesLike, key: XORKey | None = None) -> bytes:
        """Encrypt/transform byte-like data."""
        return self.transform(data, key)

    def decrypt(self, data: BytesLike, key: XORKey | None = None) -> bytes:
        """Decrypt/transform byte-like data. XOR is symmetric."""
        return self.transform(data, key)

    def encrypt_base64(self, data: BytesLike, key: XORKey | None = None) -> str:
        """XOR bytes and encode the result as URL-safe Base64 text."""
        return base64.urlsafe_b64encode(self.encrypt(data, key)).decode("ascii")

    def decrypt_base64(self, token: str, key: XORKey | None = None) -> bytes:
        """Decode URL-safe Base64 text and reverse the XOR transform."""
        if not isinstance(token, str):
            raise TypeError("token must be a string")
        try:
            encrypted = base64.b64decode(token.encode("ascii"), altchars=b"-_", validate=True)
        except (UnicodeEncodeError, binascii.Error, ValueError) as exc:
            raise CipherFormatError("invalid Base64 ciphertext") from exc
        return self.decrypt(encrypted, key)

    def encrypt_hex(self, data: BytesLike, key: XORKey | None = None) -> str:
        """XOR bytes and encode the result as lowercase hexadecimal text."""
        return self.encrypt(data, key).hex()

    def decrypt_hex(self, token: str, key: XORKey | None = None) -> bytes:
        """Decode hexadecimal text and reverse the XOR transform."""
        if not isinstance(token, str):
            raise TypeError("token must be a string")
        try:
            encrypted = bytes.fromhex(token)
        except ValueError as exc:
            raise CipherFormatError("invalid hexadecimal ciphertext") from exc
        return self.decrypt(encrypted, key)

    def encrypt_text(
        self,
        text: str,
        key: XORKey | None = None,
        *,
        encoding: str = "utf-8",
    ) -> str:
        """Encode text, XOR it, and return URL-safe Base64 ciphertext."""
        if not isinstance(text, str):
            raise TypeError("text must be a string")
        return self.encrypt_base64(text.encode(encoding), key)

    def decrypt_text(
        self,
        token: str,
        key: XORKey | None = None,
        *,
        encoding: str = "utf-8",
        errors: str = "strict",
    ) -> str:
        """Decrypt a Base64 XOR token and decode it to text."""
        return self.decrypt_base64(token, key).decode(encoding, errors)

    # Compatibility-friendly names from the original class. They now return
    # transport-safe Base64 text rather than arbitrary control characters.
    def encrypt_string(self, content: str, key: XORKey | None = None) -> str:
        return self.encrypt_text(content, key)

    def decrypt_string(self, content: str, key: XORKey | None = None) -> str:
        return self.decrypt_text(content, key)

    def encrypt_chars(self, content: str, key: XORKey | None = None) -> list[str]:
        """
        Educational character-list helper similar to the 2017 API.

        This operates on UTF-8 bytes and maps each byte through Latin-1 so every
        byte value is representable as exactly one Python character.
        """
        if not isinstance(content, str):
            raise TypeError("content must be a string")
        encrypted = self.encrypt(content.encode("utf-8"), key)
        return [chr(value) for value in encrypted]

    def decrypt_chars(
        self,
        content: Sequence[str] | Iterable[str],
        key: XORKey | None = None,
    ) -> str:
        """Reverse :meth:`encrypt_chars` and return a UTF-8 string."""
        if isinstance(content, str):
            raise TypeError("content must be an iterable of single-character strings")
        values = bytearray()
        for ch in content:
            if not isinstance(ch, str) or len(ch) != 1:
                raise TypeError("each encrypted character must be a one-character string")
            code = ord(ch)
            if code > 255:
                raise ValueError("encrypted character code must be in range 0..255")
            values.append(code)
        return self.decrypt(values, key).decode("utf-8")

    def _transform_file(
        self,
        source: Pathish,
        destination: Pathish,
        key: XORKey | None,
        *,
        chunk_size: int,
        overwrite: bool,
        progress: ProgressCallback | None,
    ) -> Path:
        chunk_size = _validate_chunk_size(chunk_size)
        source_path = Path(source)
        destination_path = Path(destination)
        if not source_path.is_file():
            raise FileNotFoundError(f"source file does not exist: {source_path}")
        _prepare_destination(source_path, destination_path, overwrite=overwrite)

        total = source_path.stat().st_size
        processed = 0
        temp_path = _atomic_temp_path(destination_path)
        try:
            with source_path.open("rb") as fin, temp_path.open("wb") as fout:
                while True:
                    chunk = fin.read(chunk_size)
                    if not chunk:
                        break
                    fout.write(self.transform(chunk, key, offset=processed))
                    processed += len(chunk)
                    _notify_progress(progress, processed, total)
                fout.flush()
                os.fsync(fout.fileno())
            _publish_atomic(temp_path, destination_path)
        except Exception:
            _safe_unlink(temp_path)
            raise
        return destination_path

    def encrypt_file(
        self,
        file: Pathish,
        output: Pathish | None = None,
        key: XORKey | None = None,
        *,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        overwrite: bool = True,
        progress: ProgressCallback | None = None,
    ) -> Path:
        """Binary-safe chunked XOR file transform with atomic output."""
        source = Path(file)
        destination = Path(output) if output is not None else Path(f"{source}.xor")
        return self._transform_file(
            source,
            destination,
            key,
            chunk_size=chunk_size,
            overwrite=overwrite,
            progress=progress,
        )

    def decrypt_file(
        self,
        file: Pathish,
        output: Pathish | None = None,
        key: XORKey | None = None,
        *,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        overwrite: bool = True,
        progress: ProgressCallback | None = None,
    ) -> Path:
        """Reverse an XOR-transformed file using the same streaming transform."""
        source = Path(file)
        if output is None:
            if source.suffix == ".xor":
                destination = source.with_suffix("")
            else:
                destination = Path(f"{source}.dec")
        else:
            destination = Path(output)
        return self._transform_file(
            source,
            destination,
            key,
            chunk_size=chunk_size,
            overwrite=overwrite,
            progress=progress,
        )


class SecureCipher:
    """
    Password-based AES-256-GCM authenticated encryption.

    Each encryption creates a fresh 16-byte salt and 12-byte GCM nonce. A
    256-bit AES key is derived from the supplied password using scrypt. Container
    metadata is supplied to GCM as Additional Authenticated Data (AAD), so
    tampering with parameters, nonce, salt, or declared size is detected.

    The secure file path uses streaming GCM and writes plaintext only to a
    temporary file until authentication succeeds. This avoids publishing partial
    unauthenticated plaintext after a wrong password or modified ciphertext.
    """

    MAGIC = b"XCSAFE01"
    HEADER = struct.Struct(">8sIIIQ16s12s")
    TAG_SIZE = 16
    SALT_SIZE = 16
    NONCE_SIZE = 12
    KEY_SIZE = 32
    DEFAULT_CHUNK_SIZE = 1024 * 1024
    DEFAULT_SCRYPT_N = 2**15
    DEFAULT_SCRYPT_R = 8
    DEFAULT_SCRYPT_P = 1
    MIN_SCRYPT_N = 2**14
    MAX_SCRYPT_N = 2**20
    MAX_SCRYPT_R = 32
    MAX_SCRYPT_P = 16

    def __init__(
        self,
        password: str | BytesLike,
        *,
        scrypt_n: int = DEFAULT_SCRYPT_N,
        scrypt_r: int = DEFAULT_SCRYPT_R,
        scrypt_p: int = DEFAULT_SCRYPT_P,
    ):
        self._require_dependency()
        self._password = self._normalize_password(password)
        self._validate_scrypt_params(scrypt_n, scrypt_r, scrypt_p)
        self._scrypt_n = scrypt_n
        self._scrypt_r = scrypt_r
        self._scrypt_p = scrypt_p

    @staticmethod
    def is_available() -> bool:
        """Return whether the optional ``cryptography`` dependency is available."""
        return _CRYPTOGRAPHY_AVAILABLE

    @staticmethod
    def _require_dependency() -> None:
        if not _CRYPTOGRAPHY_AVAILABLE:
            raise MissingDependencyError(
                "SecureCipher requires the 'cryptography' package; "
                "install it with: pip install cryptography"
            )

    @staticmethod
    def _normalize_password(password: str | BytesLike) -> bytes:
        if isinstance(password, str):
            raw = password.encode("utf-8")
        elif isinstance(password, (bytes, bytearray, memoryview)):
            raw = bytes(password)
        else:
            raise TypeError("password must be str, bytes, bytearray, or memoryview")
        if not raw:
            raise ValueError("password must not be empty")
        return raw

    @classmethod
    def _validate_scrypt_params(cls, n: int, r: int, p: int) -> None:
        for name, value in (("n", n), ("r", r), ("p", p)):
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"scrypt {name} must be an integer")
        if n < cls.MIN_SCRYPT_N or n > cls.MAX_SCRYPT_N or (n & (n - 1)) != 0:
            raise ValueError(
                f"scrypt n must be a power of two between {cls.MIN_SCRYPT_N} "
                f"and {cls.MAX_SCRYPT_N}"
            )
        if not 1 <= r <= cls.MAX_SCRYPT_R:
            raise ValueError(f"scrypt r must be between 1 and {cls.MAX_SCRYPT_R}")
        if not 1 <= p <= cls.MAX_SCRYPT_P:
            raise ValueError(f"scrypt p must be between 1 and {cls.MAX_SCRYPT_P}")

    @classmethod
    def _derive_key(cls, password: bytes, salt: bytes, n: int, r: int, p: int) -> bytes:
        cls._require_dependency()
        kdf = Scrypt(salt=salt, length=cls.KEY_SIZE, n=n, r=r, p=p)
        return kdf.derive(password)

    @classmethod
    def _build_header(
        cls,
        *,
        n: int,
        r: int,
        p: int,
        original_size: int,
        salt: bytes,
        nonce: bytes,
    ) -> bytes:
        return cls.HEADER.pack(cls.MAGIC, n, r, p, original_size, salt, nonce)

    @classmethod
    def _parse_header(cls, header: bytes) -> tuple[int, int, int, int, bytes, bytes]:
        if len(header) != cls.HEADER.size:
            raise CipherFormatError("encrypted payload has a truncated header")
        try:
            magic, n, r, p, original_size, salt, nonce = cls.HEADER.unpack(header)
        except struct.error as exc:
            raise CipherFormatError("encrypted payload header is invalid") from exc
        if magic != cls.MAGIC:
            raise CipherFormatError("not a SecureCipher v1 payload")
        cls._validate_scrypt_params(n, r, p)
        if len(salt) != cls.SALT_SIZE or len(nonce) != cls.NONCE_SIZE:
            raise CipherFormatError("invalid secure payload salt/nonce length")
        return n, r, p, original_size, salt, nonce

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(scrypt_n={self._scrypt_n}, "
            f"scrypt_r={self._scrypt_r}, scrypt_p={self._scrypt_p})"
        )

    def encrypt(self, data: BytesLike) -> bytes:
        """Encrypt bytes into an authenticated, self-describing binary payload."""
        raw = _as_bytes(data)
        salt = secrets.token_bytes(self.SALT_SIZE)
        nonce = secrets.token_bytes(self.NONCE_SIZE)
        header = self._build_header(
            n=self._scrypt_n,
            r=self._scrypt_r,
            p=self._scrypt_p,
            original_size=len(raw),
            salt=salt,
            nonce=nonce,
        )
        key = self._derive_key(
            self._password,
            salt,
            self._scrypt_n,
            self._scrypt_r,
            self._scrypt_p,
        )
        encrypted = AESGCM(key).encrypt(nonce, raw, header)
        return header + encrypted

    def decrypt(self, payload: BytesLike) -> bytes:
        """Authenticate and decrypt a binary SecureCipher payload."""
        raw = _as_bytes(payload, name="payload")
        minimum = self.HEADER.size + self.TAG_SIZE
        if len(raw) < minimum:
            raise CipherFormatError("encrypted payload is too short")
        header = raw[: self.HEADER.size]
        n, r, p, original_size, salt, nonce = self._parse_header(header)
        expected_size = self.HEADER.size + original_size + self.TAG_SIZE
        if len(raw) != expected_size:
            raise CipherFormatError(
                f"encrypted payload size mismatch: expected {expected_size} bytes, got {len(raw)}"
            )
        key = self._derive_key(self._password, salt, n, r, p)
        try:
            plaintext = AESGCM(key).decrypt(nonce, raw[self.HEADER.size :], header)
        except InvalidTag as exc:
            raise IntegrityError(
                "authentication failed: wrong password or ciphertext/metadata was modified"
            ) from exc
        if len(plaintext) != original_size:
            raise IntegrityError("authenticated payload length does not match header")
        return plaintext

    def encrypt_base64(self, data: BytesLike) -> str:
        """Securely encrypt bytes and encode the container as URL-safe Base64."""
        return base64.urlsafe_b64encode(self.encrypt(data)).decode("ascii")

    def decrypt_base64(self, token: str) -> bytes:
        """Decode Base64 and authenticate/decrypt a SecureCipher payload."""
        if not isinstance(token, str):
            raise TypeError("token must be a string")
        try:
            payload = base64.b64decode(token.encode("ascii"), altchars=b"-_", validate=True)
        except (UnicodeEncodeError, binascii.Error, ValueError) as exc:
            raise CipherFormatError("invalid Base64 secure payload") from exc
        return self.decrypt(payload)

    def encrypt_text(self, text: str, *, encoding: str = "utf-8") -> str:
        """Encrypt text and return a URL-safe Base64 authenticated token."""
        if not isinstance(text, str):
            raise TypeError("text must be a string")
        return self.encrypt_base64(text.encode(encoding))

    def decrypt_text(
        self,
        token: str,
        *,
        encoding: str = "utf-8",
        errors: str = "strict",
    ) -> str:
        """Authenticate/decrypt a text token and decode it."""
        return self.decrypt_base64(token).decode(encoding, errors)

    def encrypt_file(
        self,
        file: Pathish,
        output: Pathish | None = None,
        *,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        overwrite: bool = True,
        progress: ProgressCallback | None = None,
    ) -> Path:
        """Stream-encrypt a file with AES-256-GCM and atomic output publishing."""
        chunk_size = _validate_chunk_size(chunk_size)
        source = Path(file)
        destination = Path(output) if output is not None else Path(f"{source}.xsec")
        if not source.is_file():
            raise FileNotFoundError(f"source file does not exist: {source}")
        _prepare_destination(source, destination, overwrite=overwrite)

        total = source.stat().st_size
        salt = secrets.token_bytes(self.SALT_SIZE)
        nonce = secrets.token_bytes(self.NONCE_SIZE)
        header = self._build_header(
            n=self._scrypt_n,
            r=self._scrypt_r,
            p=self._scrypt_p,
            original_size=total,
            salt=salt,
            nonce=nonce,
        )
        key = self._derive_key(
            self._password,
            salt,
            self._scrypt_n,
            self._scrypt_r,
            self._scrypt_p,
        )
        encryptor = Cipher(algorithms.AES(key), modes.GCM(nonce)).encryptor()
        encryptor.authenticate_additional_data(header)

        temp_path = _atomic_temp_path(destination)
        processed = 0
        try:
            with source.open("rb") as fin, temp_path.open("wb") as fout:
                fout.write(header)
                while True:
                    chunk = fin.read(chunk_size)
                    if not chunk:
                        break
                    ciphertext = encryptor.update(chunk)
                    if ciphertext:
                        fout.write(ciphertext)
                    processed += len(chunk)
                    _notify_progress(progress, processed, total)
                final = encryptor.finalize()
                if final:
                    fout.write(final)
                fout.write(encryptor.tag)
                fout.flush()
                os.fsync(fout.fileno())
            _publish_atomic(temp_path, destination)
        except Exception:
            _safe_unlink(temp_path)
            raise
        return destination

    def decrypt_file(
        self,
        file: Pathish,
        output: Pathish | None = None,
        *,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        overwrite: bool = True,
        progress: ProgressCallback | None = None,
    ) -> Path:
        """
        Stream-decrypt an authenticated file.

        Plaintext is written only to a temporary file until GCM authentication
        succeeds, then atomically published at the requested destination.
        """
        chunk_size = _validate_chunk_size(chunk_size)
        source = Path(file)
        if output is None:
            destination = source.with_suffix("") if source.suffix == ".xsec" else Path(f"{source}.dec")
        else:
            destination = Path(output)
        if not source.is_file():
            raise FileNotFoundError(f"source file does not exist: {source}")
        _prepare_destination(source, destination, overwrite=overwrite)

        file_size = source.stat().st_size
        minimum_size = self.HEADER.size + self.TAG_SIZE
        if file_size < minimum_size:
            raise CipherFormatError("encrypted file is too short")

        with source.open("rb") as fin:
            header = fin.read(self.HEADER.size)
            n, r, p, original_size, salt, nonce = self._parse_header(header)
            expected_size = self.HEADER.size + original_size + self.TAG_SIZE
            if file_size != expected_size:
                raise CipherFormatError(
                    f"encrypted file size mismatch: expected {expected_size} bytes, got {file_size}"
                )
            fin.seek(self.HEADER.size + original_size)
            tag = fin.read(self.TAG_SIZE)
            if len(tag) != self.TAG_SIZE:
                raise CipherFormatError("encrypted file has a truncated authentication tag")

        key = self._derive_key(self._password, salt, n, r, p)
        decryptor = Cipher(algorithms.AES(key), modes.GCM(nonce, tag)).decryptor()
        decryptor.authenticate_additional_data(header)

        temp_path = _atomic_temp_path(destination)
        processed = 0
        try:
            with source.open("rb") as fin, temp_path.open("wb") as fout:
                fin.seek(self.HEADER.size)
                remaining = original_size
                while remaining:
                    chunk = fin.read(min(chunk_size, remaining))
                    if not chunk:
                        raise CipherFormatError("encrypted file ended before declared ciphertext size")
                    remaining -= len(chunk)
                    plaintext = decryptor.update(chunk)
                    if plaintext:
                        fout.write(plaintext)
                    processed += len(chunk)
                    _notify_progress(progress, processed, original_size)
                try:
                    final = decryptor.finalize()
                except InvalidTag as exc:
                    raise IntegrityError(
                        "authentication failed: wrong password or encrypted file was modified"
                    ) from exc
                if final:
                    fout.write(final)
                fout.flush()
                os.fsync(fout.fileno())
            _publish_atomic(temp_path, destination)
        except Exception:
            _safe_unlink(temp_path)
            raise
        return destination


def _parse_cli_xor_key(args: argparse.Namespace) -> XORKey:
    if getattr(args, "key_int", None) is not None:
        return args.key_int
    if getattr(args, "key_hex", None) is not None:
        try:
            key = bytes.fromhex(args.key_hex)
        except ValueError as exc:
            raise CipherFormatError("--key-hex must contain valid hexadecimal bytes") from exc
        if not key:
            raise ValueError("--key-hex must not be empty")
        return key
    if getattr(args, "key", None) is not None:
        return args.key
    return 1


def _resolve_cli_password(args: argparse.Namespace) -> str:
    direct = getattr(args, "password", None)
    env_name = getattr(args, "password_env", None)
    if direct is not None and env_name is not None:
        raise ValueError("use only one of --password or --password-env")
    if direct is not None:
        return direct
    if env_name is not None:
        try:
            return os.environ[env_name]
        except KeyError as exc:
            raise ValueError(f"environment variable {env_name!r} is not set") from exc
    return getpass.getpass("Password: ")


def _add_xor_key_options(parser: argparse.ArgumentParser) -> None:
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--key", help="UTF-8 repeating XOR key")
    group.add_argument("--key-int", type=int, help="integer XOR key; low 8 bits are used")
    group.add_argument("--key-hex", help="repeating XOR key as hexadecimal bytes")


def _add_password_options(parser: argparse.ArgumentParser) -> None:
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--password",
        help="password directly (convenient but may be visible in shell/process history)",
    )
    group.add_argument(
        "--password-env",
        metavar="NAME",
        help="read password from environment variable NAME; otherwise prompt securely",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="xor_cipher_advanced",
        description=(
            "Advanced educational XOR transformer plus AES-256-GCM authenticated "
            "encryption. Use secure-* commands for confidential data."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    xor_text = sub.add_parser("xor-text", help="XOR text using Base64-safe transport")
    xor_text.add_argument("mode", choices=("encrypt", "decrypt"))
    xor_text.add_argument("text", help="plaintext or Base64 ciphertext")
    xor_text.add_argument("--encoding", default="utf-8")
    _add_xor_key_options(xor_text)

    xor_file = sub.add_parser("xor-file", help="XOR-transform an arbitrary binary file")
    xor_file.add_argument("mode", choices=("encrypt", "decrypt"))
    xor_file.add_argument("input")
    xor_file.add_argument("-o", "--output")
    xor_file.add_argument("--chunk-size", type=int, default=XORCipher.DEFAULT_CHUNK_SIZE)
    xor_file.add_argument("--no-clobber", action="store_true")
    _add_xor_key_options(xor_file)

    secure_text = sub.add_parser("secure-text", help="AES-256-GCM authenticated text encryption")
    secure_text.add_argument("mode", choices=("encrypt", "decrypt"))
    secure_text.add_argument("text", help="plaintext or Base64 secure token")
    secure_text.add_argument("--encoding", default="utf-8")
    secure_text.add_argument("--scrypt-n", type=int, default=SecureCipher.DEFAULT_SCRYPT_N)
    _add_password_options(secure_text)

    secure_file = sub.add_parser("secure-file", help="AES-256-GCM authenticated file encryption")
    secure_file.add_argument("mode", choices=("encrypt", "decrypt"))
    secure_file.add_argument("input")
    secure_file.add_argument("-o", "--output")
    secure_file.add_argument("--chunk-size", type=int, default=SecureCipher.DEFAULT_CHUNK_SIZE)
    secure_file.add_argument("--scrypt-n", type=int, default=SecureCipher.DEFAULT_SCRYPT_N)
    secure_file.add_argument("--no-clobber", action="store_true")
    _add_password_options(secure_file)

    sub.add_parser("self-test", help="run fast built-in round-trip checks")
    return parser


def _run_self_test() -> None:
    # Fast deterministic API checks; the external test suite contains broader
    # file/tamper/CLI coverage.
    xor = XORCipher(b"abc")
    sample = b"\x00binary\xffdata"
    assert xor.decrypt(xor.encrypt(sample)) == sample
    text = "Hello 🌍"
    assert xor.decrypt_text(xor.encrypt_text(text)) == text

    if SecureCipher.is_available():
        secure = SecureCipher("self-test-password", scrypt_n=2**14)
        protected = secure.encrypt(sample)
        assert secure.decrypt(protected) == sample
        token = secure.encrypt_text(text)
        assert secure.decrypt_text(token) == text
    print("Self-test passed")


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "self-test":
            _run_self_test()
            return 0

        if args.command == "xor-text":
            cipher = XORCipher(_parse_cli_xor_key(args))
            if args.mode == "encrypt":
                print(cipher.encrypt_text(args.text, encoding=args.encoding))
            else:
                print(cipher.decrypt_text(args.text, encoding=args.encoding))
            return 0

        if args.command == "xor-file":
            cipher = XORCipher(_parse_cli_xor_key(args))
            kwargs = {
                "output": args.output,
                "chunk_size": args.chunk_size,
                "overwrite": not args.no_clobber,
            }
            if args.mode == "encrypt":
                result = cipher.encrypt_file(args.input, **kwargs)
            else:
                result = cipher.decrypt_file(args.input, **kwargs)
            print(result)
            return 0

        if args.command in {"secure-text", "secure-file"}:
            password = _resolve_cli_password(args)
            cipher = SecureCipher(password, scrypt_n=args.scrypt_n)
            if args.command == "secure-text":
                if args.mode == "encrypt":
                    print(cipher.encrypt_text(args.text, encoding=args.encoding))
                else:
                    print(cipher.decrypt_text(args.text, encoding=args.encoding))
                return 0

            kwargs = {
                "output": args.output,
                "chunk_size": args.chunk_size,
                "overwrite": not args.no_clobber,
            }
            if args.mode == "encrypt":
                result = cipher.encrypt_file(args.input, **kwargs)
            else:
                result = cipher.decrypt_file(args.input, **kwargs)
            print(result)
            return 0

        parser.error("unknown command")
        return 2
    except (CipherError, OSError, TypeError, ValueError, UnicodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
