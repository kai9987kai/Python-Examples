# Advanced XOR Cipher

A modern Python 3 rewrite and major expansion of the original **XORCipher** implementation by Christian Bender (2017).

This project provides two deliberately separate cryptographic layers:

1. **`XORCipher`** — a fast, reversible repeating-key XOR transformation system intended for education, experimentation, data transformation, fixtures, and lightweight obfuscation.
2. **`SecureCipher`** — authenticated **AES-256-GCM encryption** with password-based **scrypt** key derivation for data that actually requires confidentiality and integrity.

> [!WARNING]
> **XOR is not secure encryption.**
>
> Repeating-key XOR is vulnerable to known-plaintext attacks, frequency analysis, key recovery, and other cryptanalytic techniques. Do not use `XORCipher` to protect passwords, private documents, credentials, API keys, personal information, or other sensitive data.
>
> Use `SecureCipher` / the `secure-*` CLI commands when security matters.

---

## Features

### Modern XOR engine

* Python 3 implementation
* Binary-native transformation engine
* Integer XOR keys
* String keys
* `bytes` keys
* `bytearray` keys
* `memoryview` keys
* Multi-byte repeating keys
* Correct byte-level integer key normalization
* Unicode/UTF-8 support
* Base64-safe ciphertext
* Hexadecimal ciphertext
* Arbitrary binary-file support
* Streaming processing for large files
* Continuous key position across file chunks
* Configurable chunk sizes
* Atomic file output
* Source/output collision detection
* Optional no-clobber protection
* Progress callback support
* Modern type hints
* `pathlib` file handling
* Specific exception classes
* Legacy-compatible helper methods
* Built-in self-test
* Full command-line interface

### Secure encryption engine

* AES-256-GCM authenticated encryption
* Password-based encryption
* scrypt password key derivation
* 256-bit encryption keys
* Random salt for every encryption
* Fresh 96-bit GCM nonce for every encryption
* 128-bit authentication tag
* Authenticated metadata
* Tamper detection
* Wrong-password detection
* Truncation detection
* Randomized ciphertext
* Binary file encryption
* Streaming encryption/decryption
* Atomic file publishing
* Secure password prompting
* Environment-variable password support
* Configurable scrypt work factor
* Custom encrypted file container format

---

# Why This Version Exists

The original 2017 implementation was small and useful for demonstrating XOR:

```python
chr(ord(ch) ^ key)
```

However, it had several limitations:

* operated mainly on Python strings
* used text mode for files
* could corrupt arbitrary binary files
* repeatedly concatenated strings
* used broad `except:` blocks
* wrote to hard-coded filenames
* accepted only a single integer XOR key
* used incorrect key normalization for values above `255`
* had inconsistent `encrypt()` and `decrypt()` input types
* did not provide transport-safe ciphertext formats
* had no authenticated encryption
* had no tamper detection
* had no CLI
* had no structured error system
* had limited automated validation

This version keeps the simplicity of XOR while redesigning the project around modern Python and adding a separate secure cryptographic system.

---

# Original vs Advanced Version

| Capability               | Original | Advanced |
| ------------------------ | -------: | -------: |
| Python 3                 |  Partial |        ✅ |
| Integer XOR keys         |        ✅ |        ✅ |
| Multi-byte keys          |        ❌ |        ✅ |
| String keys              |        ❌ |        ✅ |
| Bytes keys               |        ❌ |        ✅ |
| Unicode                  |  Limited |        ✅ |
| Binary data              |        ❌ |        ✅ |
| Binary files             |        ❌ |        ✅ |
| Streaming files          |        ❌ |        ✅ |
| Large-file support       |  Limited |        ✅ |
| Base64 ciphertext        |        ❌ |        ✅ |
| Hex ciphertext           |        ❌ |        ✅ |
| Custom output paths      |        ❌ |        ✅ |
| Atomic writes            |        ❌ |        ✅ |
| Collision protection     |        ❌ |        ✅ |
| No-clobber mode          |        ❌ |        ✅ |
| Progress callbacks       |        ❌ |        ✅ |
| Typed exceptions         |        ❌ |        ✅ |
| Type hints               |        ❌ |        ✅ |
| CLI                      |        ❌ |        ✅ |
| Self-test                |        ❌ |        ✅ |
| Password encryption      |        ❌ |        ✅ |
| AES-256-GCM              |        ❌ |        ✅ |
| Authentication           |        ❌ |        ✅ |
| Tamper detection         |        ❌ |        ✅ |
| Wrong-password detection |        ❌ |        ✅ |
| scrypt KDF               |        ❌ |        ✅ |

---

# Requirements

## XOR functionality

The XOR functionality uses only the Python standard library.

Recommended:

```text
Python 3.10+
```

## Secure AES functionality

Install the `cryptography` package:

```bash
python -m pip install cryptography
```

or:

```bash
pip install cryptography
```

The XOR functionality remains usable without this optional dependency.

---

# Installation

Clone your repository:

```bash
git clone <your-repository-url>
cd <your-repository-directory>
```

Or simply place:

```text
xor_cipher_advanced.py
```

inside your project.

Verify the program:

```bash
python xor_cipher_advanced.py self-test
```

Expected result:

```text
Self-test passed
```

---

# Quick Start

## Python XOR example

```python
from xor_cipher_advanced import XORCipher

cipher = XORCipher("demo-key")

encrypted = cipher.encrypt_text("Hello world 🌍")

print(encrypted)

decrypted = cipher.decrypt_text(encrypted)

print(decrypted)
```

Output from `decrypt_text()`:

```text
Hello world 🌍
```

---

# XORCipher

`XORCipher` implements repeating-key XOR over raw bytes.

Encryption and decryption are the same mathematical operation:

```text
plaintext XOR key = ciphertext

ciphertext XOR key = plaintext
```

Therefore:

```python
cipher.encrypt(data)
```

and:

```python
cipher.decrypt(data)
```

perform the same underlying transformation.

The separate names make application code easier to understand.

---

# Creating an XOR Cipher

## String key

```python
from xor_cipher_advanced import XORCipher

cipher = XORCipher("my-secret-key")
```

The string is encoded as UTF-8 and used as a repeating byte sequence.

---

## Integer key

```python
cipher = XORCipher(67)
```

Integer keys use their low eight bits.

Conceptually:

```python
key & 0xFF
```

Examples:

```text
67  -> 67
255 -> 255
256 -> 0
257 -> 1
511 -> 255
```

This fixes a flaw in the original implementation, which repeatedly subtracted `255`.

---

## Bytes key

```python
cipher = XORCipher(b"\x10\x20\x30\x40")
```

---

## Bytearray key

```python
cipher = XORCipher(bytearray([10, 20, 30, 40]))
```

---

## Memoryview key

```python
cipher = XORCipher(memoryview(b"advanced-key"))
```

---

# Raw Byte Encryption

```python
from xor_cipher_advanced import XORCipher

cipher = XORCipher("example-key")

plaintext = b"Binary data \x00\x01\x02\xff"

encrypted = cipher.encrypt(plaintext)
decrypted = cipher.decrypt(encrypted)

assert decrypted == plaintext
```

---

# Transform API

Because XOR encryption and decryption are identical operations, the core transformation can also be called directly:

```python
result = cipher.transform(b"hello")
```

Applying it twice restores the original data:

```python
original = b"hello"

encrypted = cipher.transform(original)
decrypted = cipher.transform(encrypted)

assert decrypted == original
```

---

# Unicode Text Encryption

Use:

```python
encrypt_text()
```

for text that needs a transport-safe representation.

```python
cipher = XORCipher("unicode-key")

token = cipher.encrypt_text(
    "Hello 🌍 — こんにちは — Привет — مرحبا"
)

print(token)

original = cipher.decrypt_text(token)

print(original)
```

The default encoding is UTF-8.

---

# Base64 Support

Raw encrypted bytes frequently contain control characters and invalid text sequences.

For this reason, Base64 should normally be used when transporting XOR ciphertext as text.

```python
cipher = XORCipher("key")

encrypted = cipher.encrypt_base64(b"Hello world")

print(encrypted)

decrypted = cipher.decrypt_base64(encrypted)

assert decrypted == b"Hello world"
```

---

# Hexadecimal Support

```python
cipher = XORCipher("key")

encrypted = cipher.encrypt_hex(b"Hello world")

print(encrypted)

decrypted = cipher.decrypt_hex(encrypted)

assert decrypted == b"Hello world"
```

Hexadecimal output is useful for:

* debugging
* protocol inspection
* test vectors
* byte-level experiments
* logging non-sensitive transformed data

---

# Character-List Compatibility

The modern implementation includes compatibility-style methods for programs based on the original API.

```python
cipher = XORCipher(67)

encrypted_chars = cipher.encrypt_chars("hello")
decrypted_chars = cipher.decrypt_chars(encrypted_chars)

print(encrypted_chars)
print(decrypted_chars)
```

---

# Legacy String Helpers

Compatibility helpers are also available:

```python
cipher.encrypt_string(...)
cipher.decrypt_string(...)
```

These allow older programs to migrate gradually while using the redesigned implementation.

For new programs, prefer:

```python
encrypt()
decrypt()
encrypt_text()
decrypt_text()
encrypt_base64()
decrypt_base64()
```

---

# XOR File Encryption

Unlike the original implementation, files are processed in **binary mode**.

That means the program can XOR-transform essentially any file type:

* `.txt`
* `.json`
* `.csv`
* `.png`
* `.jpg`
* `.zip`
* `.exe`
* `.blend`
* `.obj`
* `.fbx`
* `.mp3`
* `.mp4`
* `.pdf`
* arbitrary binary data

Example:

```python
from xor_cipher_advanced import XORCipher

cipher = XORCipher("file-key")

cipher.encrypt_file("example.pdf")
```

By default this creates:

```text
example.pdf.xor
```

Decrypt it:

```python
cipher.decrypt_file("example.pdf.xor")
```

When the input filename ends in `.xor`, the default decryption destination removes the suffix.

Result:

```text
example.pdf
```

---

# Custom Output Path

```python
cipher.encrypt_file(
    "input.bin",
    output="encrypted/output.bin"
)
```

Decrypt:

```python
cipher.decrypt_file(
    "encrypted/output.bin",
    output="restored/input.bin"
)
```

Parent directories are automatically created when necessary.

---

# Streaming Large Files

Files are processed incrementally instead of loading everything into RAM.

The default chunk size is:

```text
1 MiB
```

or:

```text
1,048,576 bytes
```

Custom chunk size:

```python
cipher.encrypt_file(
    "large-file.bin",
    chunk_size=4 * 1024 * 1024
)
```

The XOR key position continues correctly between chunks.

For example, splitting the input into unusual chunk sizes does not reset the repeating key:

```python
cipher.encrypt_file(
    "large-file.bin",
    chunk_size=7777
)
```

The result remains equivalent to transforming the same data continuously.

---

# Atomic File Output

File operations use temporary files and atomic replacement.

Instead of writing directly to the final destination:

```text
input
   ↓
temporary file
   ↓
successful completion
   ↓
final destination
```

This reduces the risk of leaving a corrupted output file when processing fails unexpectedly.

---

# File Collision Protection

The library prevents accidentally using the same file as both input and output.

This is rejected:

```python
cipher.encrypt_file(
    "document.bin",
    output="document.bin"
)
```

Rather than overwriting the source while reading it, the operation raises an exception.

---

# Preventing Overwrites

Use:

```python
overwrite=False
```

when calling the Python API.

For example:

```python
cipher.encrypt_file(
    "file.dat",
    output="file.dat.xor",
    overwrite=False
)
```

If the destination already exists:

```text
FileExistsError
```

is raised.

The CLI exposes this as:

```text
--no-clobber
```

---

# Progress Callbacks

Applications can monitor large file operations.

Example:

```python
from xor_cipher_advanced import XORCipher

cipher = XORCipher("progress-key")


def progress(processed: int, total: int) -> None:
    if total:
        percentage = processed / total * 100
        print(f"{percentage:.1f}%")


cipher.encrypt_file(
    "large-file.bin",
    progress=progress
)
```

This makes the library suitable for:

* desktop interfaces
* progress bars
* batch-processing systems
* logging
* automation
* GUI applications

---

# SecureCipher

For confidential data, use `SecureCipher`.

```python
from xor_cipher_advanced import SecureCipher

cipher = SecureCipher(
    "correct horse battery staple"
)

encrypted = cipher.encrypt_text(
    "This information actually needs protection."
)

print(encrypted)

decrypted = cipher.decrypt_text(encrypted)

print(decrypted)
```

---

# Secure Mode Architecture

Secure mode combines:

```text
Password
   ↓
scrypt
   ↓
256-bit encryption key
   ↓
AES-256-GCM
   ↓
Authenticated ciphertext
```

Each encryption generates fresh random cryptographic parameters.

---

# scrypt Password Derivation

Passwords are not used directly as AES keys.

Instead:

```text
password
   +
random salt
   ↓
scrypt
   ↓
256-bit key
```

Default parameters:

```text
N = 32768
r = 8
p = 1
```

The default `N` value is:

```python
2**15
```

A random **16-byte salt** is generated for every encryption operation.

---

# AES-256-GCM

Secure mode uses a 256-bit AES key with Galois/Counter Mode.

Each encryption includes:

```text
16-byte random salt
12-byte random nonce
16-byte GCM authentication tag
```

The nonce is freshly generated for every encryption operation.

---

# Authentication and Integrity

AES-GCM does more than conceal plaintext.

It also detects modifications.

If an encrypted message or file is changed, authentication fails rather than silently producing altered plaintext.

Examples include:

```text
ciphertext bit changed
file truncated
authentication tag changed
header modified
wrong password
corrupted container
```

These conditions produce an error instead of unauthenticated output.

---

# Randomized Secure Encryption

Encrypting identical plaintext twice with the same password intentionally produces different ciphertext.

```python
cipher = SecureCipher("password")

a = cipher.encrypt_text("same message")
b = cipher.encrypt_text("same message")

assert a != b
```

Both still decrypt to:

```text
same message
```

This occurs because secure encryption generates fresh random salt and nonce values.

---

# Secure Binary Encryption

```python
cipher = SecureCipher("strong-password")

plaintext = b"\x00\x01\x02\x03\xff"

encrypted = cipher.encrypt(plaintext)

decrypted = cipher.decrypt(encrypted)

assert decrypted == plaintext
```

---

# Secure File Encryption

```python
from xor_cipher_advanced import SecureCipher

cipher = SecureCipher(
    "use-a-long-unique-password"
)

cipher.encrypt_file("document.pdf")
```

The default encrypted filename is:

```text
document.pdf.xsec
```

Decrypt:

```python
cipher.decrypt_file(
    "document.pdf.xsec"
)
```

Because the source ends in `.xsec`, the suffix is removed by default.

Result:

```text
document.pdf
```

---

# Secure Streaming

Secure file encryption also processes data incrementally.

Default chunk size:

```text
1 MiB
```

Example:

```python
cipher.encrypt_file(
    "huge-archive.bin",
    chunk_size=8 * 1024 * 1024
)
```

This allows large files to be encrypted without loading the entire file into memory.

---

# Authenticated File Container

Secure files use a custom container beginning with:

```text
XCSAFE01
```

The container stores the information required for decryption, including:

* format identification
* scrypt parameters
* original plaintext length
* random salt
* random nonce
* ciphertext
* GCM authentication tag

The encryption password itself is **never stored in the container**.

---

# Authenticated Metadata

Container metadata participates in authentication.

This prevents an attacker from changing important encryption metadata without detection.

For example, modification of protected header information causes authentication to fail.

---

# Safe Decryption Behaviour

Authenticated decryption does not publish the final plaintext file until authentication has succeeded.

Conceptually:

```text
encrypted input
      ↓
temporary plaintext
      ↓
verify GCM authentication
      ↓
success?
   ↙       ↘
 yes       no
 ↓          ↓
publish    delete temporary output
```

This prevents failed authentication from leaving a final partially decrypted file behind.

---

# Detecting Secure-Mode Availability

Applications can check whether the optional dependency is installed:

```python
from xor_cipher_advanced import SecureCipher

if SecureCipher.is_available():
    print("Secure encryption available")
else:
    print("Install cryptography")
```

Install it with:

```bash
python -m pip install cryptography
```

---

# Command-Line Interface

Display the main help page:

```bash
python xor_cipher_advanced.py --help
```

Available commands:

```text
xor-text
xor-file
secure-text
secure-file
self-test
```

---

# XOR Text CLI

## Encrypt with a string key

```bash
python xor_cipher_advanced.py xor-text encrypt "Hello world" --key "brain-key"
```

The output is Base64-safe ciphertext.

Decrypt:

```bash
python xor_cipher_advanced.py xor-text decrypt "BASE64_CIPHERTEXT" --key "brain-key"
```

---

## Integer XOR key

```bash
python xor_cipher_advanced.py xor-text encrypt "Hello world" --key-int 67
```

Decrypt:

```bash
python xor_cipher_advanced.py xor-text decrypt "BASE64_CIPHERTEXT" --key-int 67
```

---

## Hexadecimal key

```bash
python xor_cipher_advanced.py xor-text encrypt "Hello world" --key-hex 01020304ff
```

---

# XOR File CLI

Encrypt:

```bash
python xor_cipher_advanced.py xor-file encrypt example.pdf --key "file-key"
```

Result:

```text
example.pdf.xor
```

Decrypt:

```bash
python xor_cipher_advanced.py xor-file decrypt example.pdf.xor --key "file-key"
```

---

# Custom CLI Output

```bash
python xor_cipher_advanced.py xor-file encrypt input.bin \
    --key "my-key" \
    --output encrypted.bin
```

Short version:

```bash
python xor_cipher_advanced.py xor-file encrypt input.bin \
    --key "my-key" \
    -o encrypted.bin
```

---

# CLI Chunk Size

```bash
python xor_cipher_advanced.py xor-file encrypt large.bin \
    --key "stream-key" \
    --chunk-size 4194304
```

This example uses:

```text
4 MiB
```

chunks.

---

# CLI No-Clobber Protection

```bash
python xor_cipher_advanced.py xor-file encrypt file.bin \
    --key "key" \
    --no-clobber
```

The command fails instead of replacing an existing destination.

---

# Secure Text CLI

Encrypt:

```bash
python xor_cipher_advanced.py secure-text encrypt "Highly confidential message"
```

The program securely prompts for a password.

Decrypt:

```bash
python xor_cipher_advanced.py secure-text decrypt "SECURE_BASE64_TOKEN"
```

---

# Secure File CLI

Encrypt:

```bash
python xor_cipher_advanced.py secure-file encrypt document.pdf
```

You will be prompted for a password.

Output:

```text
document.pdf.xsec
```

Decrypt:

```bash
python xor_cipher_advanced.py secure-file decrypt document.pdf.xsec
```

---

# Password Handling

The safest normal CLI approach is to omit password arguments:

```bash
python xor_cipher_advanced.py secure-file encrypt document.pdf
```

The program then uses a secure password prompt.

---

## Environment Variable Password

For automation, a password can be obtained from an environment variable.

### PowerShell

```powershell
$env:XORCIPHER_PASSWORD="example-password"
python xor_cipher_advanced.py secure-file encrypt document.pdf --password-env XORCIPHER_PASSWORD
```

### Linux / macOS

```bash
export XORCIPHER_PASSWORD='example-password'

python xor_cipher_advanced.py secure-file encrypt document.pdf \
    --password-env XORCIPHER_PASSWORD
```

---

# Direct Password CLI Argument

The CLI also accepts:

```bash
--password
```

Example:

```bash
python xor_cipher_advanced.py secure-file encrypt document.pdf \
    --password "example-password"
```

However, this is primarily provided for convenience and testing.

> [!CAUTION]
> Command-line arguments can potentially be exposed through shell history, scripts, logs, or process inspection.
>
> Prefer the secure interactive prompt or an appropriate secrets-management mechanism.

---

# Configuring scrypt

The default scrypt work factor is:

```text
32768
```

Custom example:

```bash
python xor_cipher_advanced.py secure-file encrypt document.pdf \
    --scrypt-n 65536
```

Supported `N` values must:

* be powers of two
* be at least `16384`
* not exceed `1048576`

The Python class additionally validates the `r` and `p` parameters.

---

# Custom Character Encoding

Text commands default to UTF-8.

You can specify another encoding:

```bash
python xor_cipher_advanced.py xor-text encrypt "Hello" \
    --key "key" \
    --encoding utf-16
```

Secure text commands support the same option:

```bash
python xor_cipher_advanced.py secure-text encrypt "Hello" \
    --encoding utf-8
```

---

# Self-Test

Run:

```bash
python xor_cipher_advanced.py self-test
```

Successful result:

```text
Self-test passed
```

The built-in self-test verifies fundamental round-trip behaviour for the cipher implementations.

---

# Automated Test Suite

A separate test suite is included:

```text
test_xor_cipher_advanced.py
```

Run it with:

```bash
python -m unittest -v test_xor_cipher_advanced.py
```

The implementation was validated against tests covering areas including:

* integer XOR keys
* repeating XOR keys
* bytes
* Unicode
* Base64
* hexadecimal encoding
* empty input
* binary files
* chunk boundaries
* output collision handling
* AES-GCM encryption
* randomized secure ciphertext
* secure text round trips
* secure files
* wrong passwords
* tampering
* truncated ciphertext
* authentication failures
* atomic output behaviour

---

# Error Handling

The module exposes structured exceptions.

## `CipherError`

Base class for cipher-specific errors.

```python
from xor_cipher_advanced import CipherError
```

---

## `CipherFormatError`

Raised when encrypted data has an invalid or unsupported structure.

```python
from xor_cipher_advanced import CipherFormatError
```

Examples:

* invalid secure container
* truncated encrypted data
* malformed header
* inconsistent stored size

---

## `IntegrityError`

Raised when authenticated decryption fails.

```python
from xor_cipher_advanced import IntegrityError
```

Possible causes include:

* wrong password
* modified ciphertext
* modified metadata
* invalid authentication tag
* corrupted encrypted data

Applications should generally avoid attempting to distinguish a wrong password from malicious modification.

---

## `MissingDependencyError`

Raised if secure functionality is requested without `cryptography`.

```python
from xor_cipher_advanced import MissingDependencyError
```

Install the dependency with:

```bash
python -m pip install cryptography
```

---

# Example Error Handling

```python
from xor_cipher_advanced import (
    SecureCipher,
    IntegrityError,
    CipherFormatError,
    MissingDependencyError,
)

try:
    cipher = SecureCipher("password")

    plaintext = cipher.decrypt_text(
        encrypted_token
    )

except IntegrityError:
    print("Authentication failed")

except CipherFormatError:
    print("Encrypted data is malformed")

except MissingDependencyError:
    print("Install the cryptography package")
```

---

# Complete XOR Example

```python
from xor_cipher_advanced import XORCipher


cipher = XORCipher("advanced-repeating-key")

message = "XOR experiment 🧠"

encrypted_bytes = cipher.encrypt(
    message.encode("utf-8")
)

print("Encrypted bytes:")
print(encrypted_bytes)

decrypted_bytes = cipher.decrypt(
    encrypted_bytes
)

print("Decrypted:")
print(
    decrypted_bytes.decode("utf-8")
)

token = cipher.encrypt_text(message)

print("Base64 token:")
print(token)

assert cipher.decrypt_text(token) == message
```

---

# Complete Secure Example

```python
from xor_cipher_advanced import (
    SecureCipher,
    IntegrityError,
)


password = "correct horse battery staple"

cipher = SecureCipher(password)

message = (
    "Authenticated encryption protects "
    "confidentiality and integrity."
)

encrypted = cipher.encrypt_text(message)

print("Encrypted:")
print(encrypted)

try:
    decrypted = cipher.decrypt_text(
        encrypted
    )

    print("Decrypted:")
    print(decrypted)

except IntegrityError:
    print(
        "Wrong password or modified ciphertext."
    )
```

---

# XOR vs SecureCipher

Use `XORCipher` for:

* understanding XOR
* cryptography education
* reversible experiments
* test fixtures
* byte transformation
* controlled obfuscation
* algorithm demonstrations

Do **not** use XOR for:

* passwords
* account credentials
* private files
* medical information
* financial information
* authentication tokens
* API secrets
* encryption against an attacker

Use `SecureCipher` when confidentiality or integrity matters.

---

# Performance

Both file implementations stream data in chunks.

The default is:

```text
1 MiB
```

This avoids memory consumption proportional to input-file size.

For example, encrypting a multi-gigabyte file does not require loading the complete multi-gigabyte file into Python memory.

Larger chunk sizes may reduce I/O overhead in some environments:

```python
chunk_size=8 * 1024 * 1024
```

Smaller chunks may be useful for constrained environments.

Actual performance depends on:

* storage speed
* CPU
* Python version
* operating system
* scrypt parameters
* AES implementation
* file size
* chunk size

---

# Security Model

## XOR mode

XOR mode provides:

```text
reversible transformation
```

It does **not** provide:

```text
strong confidentiality
authentication
integrity protection
tamper resistance
secure key exchange
```

---

## Secure mode

Secure mode provides:

```text
Confidentiality
       +
Integrity
       +
Authentication
```

through AES-256-GCM.

Passwords are transformed using scrypt before being used as encryption keys.

---

# Important Password Guidance

Encryption is only as useful as the secrecy and quality of its credentials.

Prefer:

* long passwords
* unique passwords
* randomly generated passwords
* password-manager-generated credentials

Avoid:

* reused passwords
* short dictionary words
* passwords stored directly in source code
* committing credentials to Git
* exposing passwords in shell commands when avoidable

If the password is permanently lost, encrypted data generally cannot be recovered.

---

# Atomic Processing Design

File operations intentionally use a temporary-output strategy.

For encryption:

```text
Source
  │
  ▼
Transform / Encrypt
  │
  ▼
Temporary File
  │
  ▼
Success
  │
  ▼
Atomic Replace
  │
  ▼
Destination
```

For authenticated decryption:

```text
Encrypted Source
      │
      ▼
Decrypt
      │
      ▼
Temporary Output
      │
      ▼
Authenticate GCM Tag
      │
 ┌────┴────┐
 │         │
Pass      Fail
 │         │
 ▼         ▼
Publish   Delete
```

This significantly improves failure handling compared with directly writing unauthenticated output to the final destination.

---

# API Overview

## XORCipher

```text
key_bytes
key_length
transform()
encrypt()
decrypt()
encrypt_base64()
decrypt_base64()
encrypt_hex()
decrypt_hex()
encrypt_text()
decrypt_text()
encrypt_string()
decrypt_string()
encrypt_chars()
decrypt_chars()
encrypt_file()
decrypt_file()
```

---

## SecureCipher

```text
is_available()
encrypt()
decrypt()
encrypt_base64()
decrypt_base64()
encrypt_text()
decrypt_text()
encrypt_file()
decrypt_file()
```

---

# Project Structure

A minimal repository can use:

```text
project/
│
├── xor_cipher_advanced.py
├── test_xor_cipher_advanced.py
└── README.md
```

---

# Design Principles

The rewritten implementation follows several core principles.

### Binary first

Encryption algorithms operate on bytes, not human-readable strings.

Text encoding is handled at the API boundary.

### Explicit security boundaries

XOR and authenticated encryption are not treated as equivalent security mechanisms.

### Stream large data

Large files should not need to fit entirely in memory.

### Authenticate before publishing

Secure plaintext output is only finalized after authentication succeeds.

### Fail clearly

Specific exceptions are preferable to:

```python
except:
    return False
```

### Avoid destructive defaults

Input/output path collisions are detected before processing.

### Keep transport formats safe

Binary ciphertext can be represented with Base64 or hexadecimal encoding.

### Preserve useful compatibility

Legacy-style helpers remain available while the primary API follows modern Python conventions.

---

# Migration From the Original XORCipher

Original:

```python
crypt = XORCipher()
key = 67

encrypted = crypt.encrypt(
    "hallo welt",
    key
)
```

Modern approach:

```python
cipher = XORCipher(67)

encrypted = cipher.encrypt(
    b"hallo welt"
)
```

For text-oriented applications:

```python
cipher = XORCipher(67)

encrypted = cipher.encrypt_text(
    "hallo welt"
)

decrypted = cipher.decrypt_text(
    encrypted
)
```

For files:

```python
cipher.encrypt_file(
    "test.txt"
)
```

instead of relying on a hard-coded:

```text
encrypt.out
```

destination.

---

# Improvements Over the 2017 Key Logic

The original code normalized a large key using:

```python
while key > 255:
    key -= 255
```

That produces incorrect byte semantics.

For example:

```text
256 - 255 = 1
```

but the low eight bits of `256` are:

```text
0
```

The modern implementation correctly uses byte-level semantics equivalent to:

```python
key & 0xFF
```

Therefore:

```text
256 -> 0
257 -> 1
511 -> 255
512 -> 0
```

This behaviour is predictable and mathematically consistent with an 8-bit XOR key.

---

# Why XOR Encryption and Decryption Are Identical

XOR has the property:

```text
A XOR B XOR B = A
```

For example:

```text
plaintext = P
key       = K
```

Encryption:

```text
C = P XOR K
```

Decryption:

```text
P = C XOR K
```

Substitute the encrypted value:

```text
P = (P XOR K) XOR K
```

Because:

```text
K XOR K = 0
```

the original plaintext is recovered.

This makes XOR useful for teaching reversible bitwise transformations, but this mathematical symmetry does **not** make basic XOR cryptographically secure.

---

# Educational Uses

This project can be useful for learning about:

* XOR operations
* symmetric transformations
* repeating-key systems
* bytes vs strings
* Unicode encoding
* Base64
* hexadecimal encoding
* binary file processing
* streaming algorithms
* password-based key derivation
* cryptographic salts
* nonces
* authenticated encryption
* integrity verification
* atomic filesystem operations
* command-line application design
* modern Python type annotations
* cryptographic API boundaries

---

# Security Disclaimer

This repository contains both an intentionally insecure educational primitive and a real authenticated-encryption implementation.

`XORCipher` must not be interpreted as a secure encryption system simply because this project also contains AES functionality.

The distinction is intentional:

```text
XORCipher
    ↓
education / transformation / obfuscation

SecureCipher
    ↓
authenticated confidential encryption
```

Cryptography is difficult to implement correctly. For high-value, regulated, mission-critical, or production security systems, use established formats, protocols, libraries, and professional security review appropriate to the threat model.

---

# Credits

The original `XORCipher` concept and implementation were written by:

**Christian Bender**

Original date:

```text
21 December 2017
```

This version substantially redesigns and extends that implementation for modern Python, binary processing, testing, command-line use, safer file operations, and authenticated encryption.

---

# Summary

The original XOR cipher has evolved from a small educational string utility into a substantially more capable encryption and data-transformation toolkit.

The project now provides:

```text
Repeating XOR
    +
Binary processing
    +
Unicode
    +
Base64
    +
Hex
    +
Streaming files
    +
Atomic writes
    +
CLI
    +
Testing
    +
AES-256-GCM
    +
scrypt
    +
Authentication
    +
Tamper detection
```

while maintaining a clear rule:

> **Use XOR to learn and experiment. Use authenticated encryption when security actually matters.**
