#!/usr/bin/env python3
"""
Advanced Pure-Python SHA-1 Implementation
=========================================

Features
--------
- Pure Python implementation of the SHA-1 compression algorithm.
- hashlib-like API:
      update()
      digest()
      hexdigest()
      copy()
- Streaming hashing for very large files.
- Streaming stdin support.
- Constant-memory file processing.
- Built-in SHA-1 conformance tests.
- Optional verification against hashlib.sha1.
- Correct handling of multiple 512-bit blocks.
- Proper SHA-1 padding.
- Type hints.
- Robust CLI.
- Backwards-compatible final_hash() method.

IMPORTANT SECURITY NOTE
-----------------------
SHA-1 is cryptographically broken for collision resistance.

Do NOT use SHA-1 for:
- password hashing
- new digital-signature systems
- certificate systems
- integrity protection against hostile attackers
- new cryptographic protocols

For new designs, consider SHA-256, SHA-512, SHA-3, BLAKE2,
Argon2/scrypt for passwords, or another algorithm appropriate
to the specific security requirement.

This implementation is primarily educational and useful for
legacy compatibility, testing, and understanding SHA-1.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import os
import struct
import sys
import unittest
from pathlib import Path
from typing import BinaryIO, Final


# ============================================================================
# SHA-1 constants
# ============================================================================

MASK32: Final[int] = 0xFFFFFFFF

BLOCK_SIZE: Final[int] = 64
"""SHA-1 input block size in bytes: 512 bits."""

DIGEST_SIZE: Final[int] = 20
"""SHA-1 output size in bytes: 160 bits."""


INITIAL_STATE: Final[tuple[int, int, int, int, int]] = (
    0x67452301,
    0xEFCDAB89,
    0x98BADCFE,
    0x10325476,
    0xC3D2E1F0,
)


ROUND_CONSTANTS: Final[tuple[int, int, int, int]] = (
    0x5A827999,
    0x6ED9EBA1,
    0x8F1BBCDC,
    0xCA62C1D6,
)


# ============================================================================
# SHA-1 implementation
# ============================================================================


class SHA1Hash:
    """
    Incremental pure-Python SHA-1 implementation.

    The public API deliberately resembles hashlib:

        sha = SHA1Hash()
        sha.update(b"Hello ")
        sha.update(b"World")

        print(sha.hexdigest())

    Or:

        digest = SHA1Hash(b"Hello World").hexdigest()

    Calling digest() or hexdigest() does NOT destroy the current hashing
    state. More data can continue to be added afterwards.
    """

    name = "sha1"
    block_size = BLOCK_SIZE
    digest_size = DIGEST_SIZE

    def __init__(
        self,
        data: bytes | bytearray | memoryview = b"",
    ) -> None:
        self._h: list[int] = list(INITIAL_STATE)

        # Bytes that have not yet accumulated into a complete 64-byte block.
        self._unprocessed = bytearray()

        # Number of actual message bytes seen before SHA-1 padding.
        self._message_byte_length = 0

        if data:
            self.update(data)

    # ------------------------------------------------------------------------
    # Core bit operations
    # ------------------------------------------------------------------------

    @staticmethod
    def _left_rotate(value: int, bits: int) -> int:
        """
        Rotate a 32-bit integer left.

        Example:
            1001... rotated left becomes ...1001

        All arithmetic is constrained to 32 bits.
        """

        bits &= 31
        value &= MASK32

        if bits == 0:
            return value

        return (
            (value << bits)
            | (value >> (32 - bits))
        ) & MASK32

    @staticmethod
    def _round_function(
        round_number: int,
        b: int,
        c: int,
        d: int,
    ) -> tuple[int, int]:
        """
        Return SHA-1's nonlinear Boolean function and round constant.

        SHA-1 uses four logical phases:

            0-19   Choose
            20-39  Parity
            40-59  Majority
            60-79  Parity
        """

        if round_number < 20:
            f = (b & c) | ((~b) & d)
            k = ROUND_CONSTANTS[0]

        elif round_number < 40:
            f = b ^ c ^ d
            k = ROUND_CONSTANTS[1]

        elif round_number < 60:
            f = (b & c) | (b & d) | (c & d)
            k = ROUND_CONSTANTS[2]

        else:
            f = b ^ c ^ d
            k = ROUND_CONSTANTS[3]

        return f & MASK32, k

    # ------------------------------------------------------------------------
    # SHA-1 message schedule
    # ------------------------------------------------------------------------

    @classmethod
    def _expand_block(
        cls,
        block: bytes | bytearray | memoryview,
    ) -> list[int]:
        """
        Convert one 64-byte SHA-1 block into its 80-word message schedule.

        The initial sixteen 32-bit words come directly from the block.

        Words 16-79 are generated using:

            W[t] = ROTL1(
                W[t-3] ^
                W[t-8] ^
                W[t-14] ^
                W[t-16]
            )
        """

        if len(block) != BLOCK_SIZE:
            raise ValueError(
                f"SHA-1 requires {BLOCK_SIZE}-byte blocks; "
                f"received {len(block)} bytes."
            )

        words = list(
            struct.unpack(
                ">16I",
                block,
            )
        )

        words.extend([0] * 64)

        for i in range(16, 80):
            words[i] = cls._left_rotate(
                words[i - 3]
                ^ words[i - 8]
                ^ words[i - 14]
                ^ words[i - 16],
                1,
            )

        return words

    # ------------------------------------------------------------------------
    # SHA-1 compression function
    # ------------------------------------------------------------------------

    def _process_block(
        self,
        block: bytes | bytearray | memoryview,
    ) -> None:
        """
        Process exactly one 512-bit SHA-1 block.

        This is the central SHA-1 compression function.
        """

        words = self._expand_block(block)

        a, b, c, d, e = self._h

        for i in range(80):
            f, k = self._round_function(
                i,
                b,
                c,
                d,
            )

            temp = (
                self._left_rotate(a, 5)
                + f
                + e
                + k
                + words[i]
            ) & MASK32

            a, b, c, d, e = (
                temp,
                a,
                self._left_rotate(b, 30),
                c,
                d,
            )

        # This MUST happen for every individual block.
        #
        # The original program performed this accumulation outside the
        # block-processing loop, which caused incorrect hashes for
        # sufficiently long messages.

        self._h[0] = (
            self._h[0] + a
        ) & MASK32

        self._h[1] = (
            self._h[1] + b
        ) & MASK32

        self._h[2] = (
            self._h[2] + c
        ) & MASK32

        self._h[3] = (
            self._h[3] + d
        ) & MASK32

        self._h[4] = (
            self._h[4] + e
        ) & MASK32

    # ------------------------------------------------------------------------
    # Public incremental API
    # ------------------------------------------------------------------------

    def update(
        self,
        data: bytes | bytearray | memoryview,
    ) -> "SHA1Hash":
        """
        Add more data to the SHA-1 message.

        Data can be supplied incrementally:

            h = SHA1Hash()

            h.update(b"abc")
            h.update(b"def")
            h.update(b"ghi")

        This avoids loading an entire file into RAM.
        """

        if not isinstance(
            data,
            (
                bytes,
                bytearray,
                memoryview,
            ),
        ):
            raise TypeError(
                "SHA1Hash.update() requires a bytes-like object, "
                f"not {type(data).__name__!r}."
            )

        view = memoryview(data).cast("B")

        self._message_byte_length += len(view)

        # --------------------------------------------------------------------
        # First complete any partial block left from the previous update().
        # --------------------------------------------------------------------

        if self._unprocessed:
            required = (
                BLOCK_SIZE
                - len(self._unprocessed)
            )

            self._unprocessed.extend(
                view[:required]
            )

            view = view[required:]

            if len(self._unprocessed) == BLOCK_SIZE:
                self._process_block(
                    self._unprocessed
                )

                self._unprocessed.clear()

        # --------------------------------------------------------------------
        # Process every complete block without copying everything.
        # --------------------------------------------------------------------

        complete_length = (
            len(view)
            - (len(view) % BLOCK_SIZE)
        )

        for offset in range(
            0,
            complete_length,
            BLOCK_SIZE,
        ):
            self._process_block(
                view[
                    offset:
                    offset + BLOCK_SIZE
                ]
            )

        # --------------------------------------------------------------------
        # Retain trailing incomplete bytes.
        # --------------------------------------------------------------------

        if complete_length < len(view):
            self._unprocessed.extend(
                view[complete_length:]
            )

        return self

    def copy(self) -> "SHA1Hash":
        """
        Return an independent copy of the current hashing state.

        Useful for branching hashes:

            base = SHA1Hash(b"prefix:")

            a = base.copy().update(b"A").hexdigest()
            b = base.copy().update(b"B").hexdigest()
        """

        duplicate = self.__class__()

        duplicate._h = self._h.copy()

        duplicate._unprocessed = (
            self._unprocessed.copy()
        )

        duplicate._message_byte_length = (
            self._message_byte_length
        )

        return duplicate

    # ------------------------------------------------------------------------
    # SHA-1 finalization
    # ------------------------------------------------------------------------

    def _finalized_state(self) -> list[int]:
        """
        Produce the completed SHA-1 internal state without modifying self.
        """

        clone = self.copy()

        # SHA-1 stores message length modulo 2^64.
        bit_length = (
            clone._message_byte_length * 8
        ) & 0xFFFFFFFFFFFFFFFF

        final = bytearray(
            clone._unprocessed
        )

        # First padding bit:
        #
        #     10000000 = 0x80

        final.append(0x80)

        # SHA-1 requires message length before the final 8-byte length
        # field to be congruent to 56 mod 64.

        zero_padding = (
            56
            - (len(final) % BLOCK_SIZE)
        ) % BLOCK_SIZE

        final.extend(
            b"\x00" * zero_padding
        )

        # Append original message length as unsigned 64-bit big-endian bits.

        final.extend(
            struct.pack(
                ">Q",
                bit_length,
            )
        )

        if len(final) % BLOCK_SIZE != 0:
            raise RuntimeError(
                "Internal SHA-1 padding error."
            )

        for offset in range(
            0,
            len(final),
            BLOCK_SIZE,
        ):
            clone._process_block(
                final[
                    offset:
                    offset + BLOCK_SIZE
                ]
            )

        return clone._h

    def digest(self) -> bytes:
        """
        Return the 20-byte SHA-1 digest.
        """

        state = self._finalized_state()

        return struct.pack(
            ">5I",
            *state,
        )

    def hexdigest(self) -> str:
        """
        Return the SHA-1 digest as a 40-character lowercase hexadecimal string.
        """

        return self.digest().hex()

    def final_hash(self) -> str:
        """
        Backwards-compatible alias matching the original program.
        """

        return self.hexdigest()

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}"
            f"(bytes_processed={self._message_byte_length}, "
            f"pending={len(self._unprocessed)})"
        )


# ============================================================================
# Streaming helpers
# ============================================================================


def hash_stream(
    stream: BinaryIO,
    chunk_size: int = 1024 * 1024,
) -> SHA1Hash:
    """
    Hash a binary stream incrementally.

    Default chunk size:
        1 MiB

    Memory usage therefore remains approximately constant even for
    multi-gigabyte files.
    """

    if chunk_size <= 0:
        raise ValueError(
            "chunk_size must be greater than zero."
        )

    hasher = SHA1Hash()

    while True:
        chunk = stream.read(chunk_size)

        if not chunk:
            break

        hasher.update(chunk)

    return hasher


def hash_stream_with_reference(
    stream: BinaryIO,
    chunk_size: int = 1024 * 1024,
) -> tuple[SHA1Hash, str]:
    """
    Hash a stream simultaneously using this implementation and hashlib.

    Useful for validation without needing to read the stream twice.
    """

    if chunk_size <= 0:
        raise ValueError(
            "chunk_size must be greater than zero."
        )

    custom = SHA1Hash()
    reference = hashlib.sha1()

    while True:
        chunk = stream.read(chunk_size)

        if not chunk:
            break

        custom.update(chunk)
        reference.update(chunk)

    return custom, reference.hexdigest()


def hash_file(
    path: Path,
    chunk_size: int = 1024 * 1024,
) -> SHA1Hash:
    """
    Hash a file while keeping memory usage bounded.
    """

    with path.open("rb") as stream:
        return hash_stream(
            stream,
            chunk_size,
        )


def hash_file_with_reference(
    path: Path,
    chunk_size: int = 1024 * 1024,
) -> tuple[SHA1Hash, str]:
    """
    Hash a file with both implementations in a single pass.
    """

    with path.open("rb") as stream:
        return hash_stream_with_reference(
            stream,
            chunk_size,
        )


def hash_text(
    text: str,
    encoding: str = "utf-8",
) -> SHA1Hash:
    """
    Encode and hash a Python string.
    """

    return SHA1Hash(
        text.encode(encoding)
    )


# ============================================================================
# Test suite
# ============================================================================


class SHA1HashTests(unittest.TestCase):
    """
    SHA-1 correctness and regression tests.
    """

    def test_standard_vectors(self) -> None:
        """
        Test standard well-known SHA-1 vectors.
        """

        vectors = {
            b"":
                "da39a3ee5e6b4b0d3255bfef95601890afd80709",

            b"abc":
                "a9993e364706816aba3e25717850c26c9cd0d89d",

            (
                b"abcdbcdecdefdefgefghfghighijhijk"
                b"ijkljklmklmnlmnomnopnopq"
            ):
                "84983e441c3bd26ebaae4aa1f95129e5e54670f1",

            b"The quick brown fox jumps over the lazy dog":
                "2fd4e1c67a2d28fced849ee1bb76e7391b93eb12",

            b"The quick brown fox jumps over the lazy cog":
                "de9f2c7fd25e1b3afad3e85a0bd17d9b100db4b3",
        }

        for message, expected in vectors.items():
            with self.subTest(
                message=message
            ):
                actual = (
                    SHA1Hash(message)
                    .hexdigest()
                )

                self.assertEqual(
                    actual,
                    expected,
                )

    def test_original_example(self) -> None:
        """
        Preserve the original test case.
        """

        message = b"Test String"

        expected = hashlib.sha1(
            message
        ).hexdigest()

        actual = SHA1Hash(
            message
        ).final_hash()

        self.assertEqual(
            actual,
            expected,
        )

    def test_incremental_updates(self) -> None:
        """
        Ensure hundreds of small update() operations equal a single hash.
        """

        data = (
            b"0123456789abcdef" * 1000
        ) + b"tail"

        hasher = SHA1Hash()

        for i in range(
            0,
            len(data),
            7,
        ):
            hasher.update(
                data[i:i + 7]
            )

        expected = hashlib.sha1(
            data
        ).hexdigest()

        self.assertEqual(
            hasher.hexdigest(),
            expected,
        )

    def test_block_boundaries(self) -> None:
        """
        Test the particularly error-prone SHA-1 padding boundaries.
        """

        sizes = (
            0,
            1,
            54,
            55,
            56,
            57,
            62,
            63,
            64,
            65,
            118,
            119,
            120,
            121,
            126,
            127,
            128,
            129,
            255,
            256,
            257,
            1024,
        )

        for size in sizes:
            data = bytes(
                (
                    i * 37 + 11
                ) & 0xFF

                for i in range(size)
            )

            with self.subTest(
                size=size
            ):
                expected = hashlib.sha1(
                    data
                ).hexdigest()

                actual = SHA1Hash(
                    data
                ).hexdigest()

                self.assertEqual(
                    actual,
                    expected,
                )

    def test_copy(self) -> None:
        """
        Verify branching hash states.
        """

        base = SHA1Hash(
            b"prefix:"
        )

        first = (
            base
            .copy()
            .update(b"one")
            .hexdigest()
        )

        second = (
            base
            .copy()
            .update(b"two")
            .hexdigest()
        )

        self.assertEqual(
            first,
            hashlib.sha1(
                b"prefix:one"
            ).hexdigest(),
        )

        self.assertEqual(
            second,
            hashlib.sha1(
                b"prefix:two"
            ).hexdigest(),
        )

    def test_digest_does_not_destroy_state(self) -> None:
        """
        hashlib permits hashing to continue after digest()/hexdigest().
        This implementation does the same.
        """

        hasher = SHA1Hash(
            b"abc"
        )

        first = hasher.hexdigest()
        second = hasher.hexdigest()

        self.assertEqual(
            first,
            second,
        )

        hasher.update(
            b"def"
        )

        self.assertEqual(
            hasher.hexdigest(),
            hashlib.sha1(
                b"abcdef"
            ).hexdigest(),
        )

    def test_stream_hashing(self) -> None:
        """
        Ensure streamed input produces the same result as hashlib.
        """

        data = os.urandom(
            250_000
        )

        stream = io.BytesIO(
            data
        )

        actual = hash_stream(
            stream,
            chunk_size=4093,
        ).hexdigest()

        expected = hashlib.sha1(
            data
        ).hexdigest()

        self.assertEqual(
            actual,
            expected,
        )

    def test_million_a(self) -> None:
        """
        Famous SHA-1 test vector:
            one million ASCII 'a' characters.
        """

        expected = (
            "34aa973cd4c4daa4f61eeb2bdbad27316534016f"
        )

        data = b"a" * 1_000_000

        actual = SHA1Hash(
            data
        ).hexdigest()

        self.assertEqual(
            actual,
            expected,
        )

    def test_type_validation(self) -> None:
        """
        update() should reject normal Python strings.
        """

        with self.assertRaises(TypeError):
            SHA1Hash().update(
                "not bytes"  # type: ignore[arg-type]
            )

    def test_invalid_chunk_size(self) -> None:
        with self.assertRaises(ValueError):
            hash_stream(
                io.BytesIO(b"abc"),
                0,
            )


def run_self_tests(
    verbosity: int = 2,
) -> bool:
    """
    Execute the built-in unittest suite.
    """

    suite = (
        unittest
        .defaultTestLoader
        .loadTestsFromTestCase(
            SHA1HashTests
        )
    )

    runner = unittest.TextTestRunner(
        verbosity=verbosity
    )

    result = runner.run(
        suite
    )

    return result.wasSuccessful()


# ============================================================================
# CLI
# ============================================================================


def build_parser() -> argparse.ArgumentParser:
    """
    Construct the command-line interface.
    """

    parser = argparse.ArgumentParser(
        prog="sha1_advanced",
        description=(
            "Educational pure-Python SHA-1 implementation with "
            "streaming file support and hashlib verification."
        ),
        epilog=(
            "Security warning: SHA-1 is collision-broken and should "
            "not be selected for new security-sensitive systems."
        ),
    )

    source = (
        parser
        .add_mutually_exclusive_group()
    )

    source.add_argument(
        "-s",
        "--string",
        dest="input_string",
        metavar="TEXT",
        help="hash a text string",
    )

    source.add_argument(
        "-f",
        "--file",
        type=Path,
        metavar="PATH",
        help=(
            "hash a file using streaming I/O"
        ),
    )

    source.add_argument(
        "--stdin",
        action="store_true",
        help=(
            "read raw data from standard input"
        ),
    )

    parser.add_argument(
        "--encoding",
        default="utf-8",
        metavar="ENCODING",
        help=(
            "encoding used by --string "
            "(default: utf-8)"
        ),
    )

    parser.add_argument(
        "--chunk-size",
        type=int,
        default=1024 * 1024,
        metavar="BYTES",
        help=(
            "stream read size in bytes "
            "(default: 1048576)"
        ),
    )

    parser.add_argument(
        "--compare",
        action="store_true",
        help=(
            "calculate the digest simultaneously with hashlib.sha1 "
            "and verify that both implementations agree"
        ),
    )

    parser.add_argument(
        "--uppercase",
        action="store_true",
        help=(
            "display hexadecimal digest in uppercase"
        ),
    )

    parser.add_argument(
        "--digest-only",
        action="store_true",
        help=(
            "print only the digest"
        ),
    )

    parser.add_argument(
        "--self-test",
        action="store_true",
        help=(
            "run the built-in SHA-1 test suite and exit"
        ),
    )

    return parser


# ============================================================================
# Main program
# ============================================================================


def main(
    argv: list[str] | None = None,
) -> int:
    parser = build_parser()

    args = parser.parse_args(
        argv
    )

    if args.chunk_size <= 0:
        parser.error(
            "--chunk-size must be greater than zero"
        )

    # ------------------------------------------------------------------------
    # Self-test mode
    # ------------------------------------------------------------------------

    if args.self_test:
        success = run_self_tests()

        return (
            0
            if success
            else 1
        )

    reference_digest: str | None = None

    try:

        # --------------------------------------------------------------------
        # File input
        # --------------------------------------------------------------------

        if args.file is not None:

            if not args.file.exists():
                parser.error(
                    f"file does not exist: {args.file}"
                )

            if not args.file.is_file():
                parser.error(
                    f"not a regular file: {args.file}"
                )

            if args.compare:

                hasher, reference_digest = (
                    hash_file_with_reference(
                        args.file,
                        args.chunk_size,
                    )
                )

            else:

                hasher = hash_file(
                    args.file,
                    args.chunk_size,
                )

            label = str(
                args.file
            )

        # --------------------------------------------------------------------
        # stdin input
        # --------------------------------------------------------------------

        elif args.stdin:

            if args.compare:

                hasher, reference_digest = (
                    hash_stream_with_reference(
                        sys.stdin.buffer,
                        args.chunk_size,
                    )
                )

            else:

                hasher = hash_stream(
                    sys.stdin.buffer,
                    args.chunk_size,
                )

            label = "stdin"

        # --------------------------------------------------------------------
        # String input
        # --------------------------------------------------------------------

        else:

            text = (
                args.input_string
                if args.input_string is not None
                else "Hello World!! Welcome to Cryptography"
            )

            encoded = text.encode(
                args.encoding
            )

            hasher = SHA1Hash(
                encoded
            )

            label = repr(
                text
            )

            if args.compare:
                reference_digest = (
                    hashlib.sha1(
                        encoded
                    ).hexdigest()
                )

    except UnicodeError as exc:
        parser.exit(
            2,
            f"encoding error: {exc}\n",
        )

    except PermissionError as exc:
        parser.exit(
            2,
            f"permission error: {exc}\n",
        )

    except OSError as exc:
        parser.exit(
            2,
            f"I/O error: {exc}\n",
        )

    # ------------------------------------------------------------------------
    # Produce digest
    # ------------------------------------------------------------------------

    digest = hasher.hexdigest()

    if args.uppercase:
        digest = digest.upper()

    # ------------------------------------------------------------------------
    # Optional verification
    # ------------------------------------------------------------------------

    if reference_digest is not None:

        comparison_digest = (
            reference_digest.upper()
            if args.uppercase
            else reference_digest
        )

        if digest != comparison_digest:

            print(
                "ERROR: SHA-1 implementation mismatch.",
                file=sys.stderr,
            )

            print(
                f"custom : {digest}",
                file=sys.stderr,
            )

            print(
                f"hashlib: {comparison_digest}",
                file=sys.stderr,
            )

            return 1

    # ------------------------------------------------------------------------
    # Output
    # ------------------------------------------------------------------------

    if args.digest_only:
        print(
            digest
        )

    else:
        print(
            f"{digest}  {label}"
        )

    if (
        reference_digest is not None
        and not args.digest_only
    ):
        print(
            "verification: OK - result matches hashlib.sha1",
            file=sys.stderr,
        )

    return 0


# ============================================================================
# Entry point
# ============================================================================


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
