import base64
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from xor_cipher_advanced import XORCipher, SecureCipher, CipherError, IntegrityError


class XORCipherTests(unittest.TestCase):
    def test_integer_key_round_trip_bytes(self):
        cipher = XORCipher(67)
        data = b"hello world\x00\xff"
        encrypted = cipher.encrypt(data)
        self.assertNotEqual(encrypted, data)
        self.assertEqual(cipher.decrypt(encrypted), data)

    def test_repeating_key_round_trip_unicode_text(self):
        cipher = XORCipher("brain-key")
        text = "Hello 🌍 — Καλημέρα — こんにちは"
        token = cipher.encrypt_text(text)
        self.assertIsInstance(token, str)
        self.assertNotEqual(token, text)
        self.assertEqual(cipher.decrypt_text(token), text)

    def test_hex_round_trip(self):
        cipher = XORCipher(b"abc")
        token = cipher.encrypt_hex(b"\x00\x01\x02payload")
        self.assertRegex(token, r"^[0-9a-f]+$")
        self.assertEqual(cipher.decrypt_hex(token), b"\x00\x01\x02payload")

    def test_base64_round_trip(self):
        cipher = XORCipher(b"abc")
        token = cipher.encrypt_base64(b"binary\x00data")
        base64.urlsafe_b64decode(token.encode("ascii"))
        self.assertEqual(cipher.decrypt_base64(token), b"binary\x00data")

    def test_zero_key_is_valid_and_not_replaced(self):
        cipher = XORCipher(0)
        data = b"unchanged"
        self.assertEqual(cipher.encrypt(data), data)
        self.assertEqual(cipher.decrypt(data), data)

    def test_large_integer_key_uses_low_byte(self):
        self.assertEqual(XORCipher(256).key_bytes, b"\x00")
        self.assertEqual(XORCipher(511).key_bytes, b"\xff")

    def test_negative_integer_key_rejected(self):
        with self.assertRaises(ValueError):
            XORCipher(-1)

    def test_empty_repeating_key_rejected(self):
        with self.assertRaises(ValueError):
            XORCipher(b"")

    def test_transform_offset_matches_whole_transform(self):
        cipher = XORCipher(b"ABCDE")
        data = bytes(range(100))
        whole = cipher.encrypt(data)
        part1 = cipher.transform(data[:37], offset=0)
        part2 = cipher.transform(data[37:], offset=37)
        self.assertEqual(part1 + part2, whole)

    def test_binary_file_round_trip_across_non_aligned_chunks(self):
        cipher = XORCipher(b"five5")
        data = os.urandom(100_003)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = root / "input.bin"
            enc = root / "encrypted.xor"
            dec = root / "decrypted.bin"
            src.write_bytes(data)
            out1 = cipher.encrypt_file(src, enc, chunk_size=4097)
            out2 = cipher.decrypt_file(enc, dec, chunk_size=4097)
            self.assertEqual(out1, enc)
            self.assertEqual(out2, dec)
            self.assertEqual(dec.read_bytes(), data)

    def test_file_source_destination_collision_rejected(self):
        cipher = XORCipher(7)
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "same.bin"
            p.write_bytes(b"data")
            with self.assertRaises(ValueError):
                cipher.encrypt_file(p, p)

    def test_legacy_char_helpers_round_trip(self):
        cipher = XORCipher(67)
        encrypted = cipher.encrypt_chars("hallo welt")
        self.assertEqual(cipher.decrypt_chars(encrypted), "hallo welt")


@unittest.skipUnless(SecureCipher.is_available(), "cryptography package is not installed")
class SecureCipherTests(unittest.TestCase):
    def test_secure_bytes_round_trip_and_randomized_ciphertext(self):
        cipher = SecureCipher("correct horse battery staple", scrypt_n=2**14)
        data = b"sensitive payload" * 100
        a = cipher.encrypt(data)
        b = cipher.encrypt(data)
        self.assertNotEqual(a, b)
        self.assertEqual(cipher.decrypt(a), data)
        self.assertEqual(cipher.decrypt(b), data)

    def test_secure_text_round_trip(self):
        cipher = SecureCipher("pāssw0rd!", scrypt_n=2**14)
        text = "Encrypted Unicode 🔐 data"
        token = cipher.encrypt_text(text)
        self.assertEqual(cipher.decrypt_text(token), text)

    def test_wrong_password_fails_authentication(self):
        good = SecureCipher("right-password", scrypt_n=2**14)
        bad = SecureCipher("wrong-password", scrypt_n=2**14)
        blob = good.encrypt(b"secret")
        with self.assertRaises(IntegrityError):
            bad.decrypt(blob)

    def test_tampering_fails_authentication(self):
        cipher = SecureCipher("password", scrypt_n=2**14)
        blob = bytearray(cipher.encrypt(b"important data"))
        blob[-5] ^= 0x40
        with self.assertRaises(IntegrityError):
            cipher.decrypt(bytes(blob))

    def test_truncated_payload_rejected(self):
        cipher = SecureCipher("password", scrypt_n=2**14)
        with self.assertRaises(CipherError):
            cipher.decrypt(b"too-short")

    def test_secure_file_round_trip_and_atomic_failure(self):
        good = SecureCipher("right-password", scrypt_n=2**14)
        bad = SecureCipher("wrong-password", scrypt_n=2**14)
        data = os.urandom(250_123)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = root / "src.bin"
            enc = root / "src.bin.xsec"
            dec = root / "dec.bin"
            protected = root / "protected.bin"
            src.write_bytes(data)
            protected.write_bytes(b"DO NOT OVERWRITE")
            good.encrypt_file(src, enc, chunk_size=7001)
            good.decrypt_file(enc, dec, chunk_size=4093)
            self.assertEqual(dec.read_bytes(), data)
            with self.assertRaises(IntegrityError):
                bad.decrypt_file(enc, protected, chunk_size=4093)
            self.assertEqual(protected.read_bytes(), b"DO NOT OVERWRITE")

    def test_secure_file_tampering_does_not_publish_partial_plaintext(self):
        cipher = SecureCipher("password", scrypt_n=2**14)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = root / "src.bin"
            enc = root / "src.bin.xsec"
            out = root / "out.bin"
            src.write_bytes(os.urandom(50_000))
            cipher.encrypt_file(src, enc, chunk_size=3333)
            damaged = bytearray(enc.read_bytes())
            damaged[-20] ^= 1
            enc.write_bytes(damaged)
            with self.assertRaises(IntegrityError):
                cipher.decrypt_file(enc, out, chunk_size=3333)
            self.assertFalse(out.exists())


class CLITests(unittest.TestCase):
    def test_cli_self_test(self):
        script = Path(__file__).with_name("xor_cipher_advanced.py")
        proc = subprocess.run(
            [sys.executable, str(script), "self-test"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("Self-test passed", proc.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
