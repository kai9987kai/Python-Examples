#!/usr/bin/env python3
"""
Script Name     : password_cracker.py
Author          : Craig Richards / Improved
Description     : Modern, cross-platform dictionary password cracker using hashlib.
                  Supports MD5, SHA-1, and SHA-256. Automatically generates
                  demo files if they are missing.
"""

import hashlib
import os
import sys

# Define default filenames
PASSWORDS_FILE = 'passwords.txt'
DICTIONARY_FILE = 'dictionary.txt'


def detect_algorithm(hash_str):
    """Detects the hashing algorithm based on the length of the hex hash string."""
    clean_hash = hash_str.strip().lower()
    # Check if the string is valid hexadecimal
    if not all(c in '0123456789abcdef' for c in clean_hash):
        return None
    
    if len(clean_hash) == 32:
        return 'md5'
    elif len(clean_hash) == 40:
        return 'sha1'
    elif len(clean_hash) == 64:
        return 'sha256'
    return None


def hash_word(word, algo):
    """Hashes a word using the specified algorithm."""
    encoded_word = word.encode('utf-8', errors='ignore')
    if algo == 'md5':
        return hashlib.md5(encoded_word).hexdigest()
    elif algo == 'sha1':
        return hashlib.sha1(encoded_word).hexdigest()
    elif algo == 'sha256':
        return hashlib.sha256(encoded_word).hexdigest()
    return None


def create_demo_files():
    """Generates mock password and dictionary files to demonstrate functionality."""
    print("[*] Demo files not found. Creating mock 'passwords.txt' and 'dictionary.txt'...")
    
    demo_passwords = {
        "admin": "admin",      # SHA-256: 8c6976...
        "user1": "password",   # SHA-256: 5e8848...
        "guest": "secret",     # MD5: 5ebe22...
        "coder": "python"      # SHA-1: 41b63e...
    }
    
    # Write passwords file
    with open(PASSWORDS_FILE, 'w', encoding='utf-8') as pf:
        pf.write("# Mock Passwords File (format: username:hash)\n")
        # admin (sha256)
        pf.write(f"admin:{hashlib.sha256(demo_passwords['admin'].encode()).hexdigest()}\n")
        # user1 (sha256)
        pf.write(f"user1:{hashlib.sha256(demo_passwords['user1'].encode()).hexdigest()}\n")
        # guest (md5)
        pf.write(f"guest:{hashlib.md5(demo_passwords['guest'].encode()).hexdigest()}\n")
        # coder (sha1)
        pf.write(f"coder:{hashlib.sha1(demo_passwords['coder'].encode()).hexdigest()}\n")
        
    # Write dictionary file
    with open(DICTIONARY_FILE, 'w', encoding='utf-8') as df:
        words = ["qwerty", "123456", "admin", "welcome", "password", "secret", "letmein", "python", "compile"]
        for word in words:
            df.write(f"{word}\n")
            
    print("[+] Demo files created successfully!\n")


def test_pass(crypt_pass):
    """Attempts to crack the given hash using the dictionary file."""
    crypt_pass = crypt_pass.strip()
    algo = detect_algorithm(crypt_pass)
    
    if not algo:
        print(f"[-] Unsupported or invalid hash format (must be 32, 40, or 64 hex chars): {crypt_pass}\n")
        return False
        
    print(f"[*] Detected algorithm: {algo.upper()}")
    
    try:
        with open(DICTIONARY_FILE, 'r', encoding='utf-8', errors='ignore') as dict_file:
            for line in dict_file:
                word = line.strip()
                if not word or word.startswith('#'):
                    continue
                
                hashed_word = hash_word(word, algo)
                if hashed_word == crypt_pass.lower():
                    print(f"[+] Found Password: {word}\n")
                    return True
    except OSError as e:
        print(f"[-] Error reading dictionary file: {e}")
        return False

    print("[-] Password Not Found.\n")
    return False


def main():
    # Ensure demo files exist if neither is present
    if not os.path.exists(PASSWORDS_FILE) or not os.path.exists(DICTIONARY_FILE):
        create_demo_files()
        
    print(f"[*] Reading target passwords from: {PASSWORDS_FILE}")
    print(f"[*] Reading dictionary from: {DICTIONARY_FILE}")
    print("=" * 50)
    
    try:
        with open(PASSWORDS_FILE, 'r', encoding='utf-8', errors='ignore') as pass_file:
            for line in pass_file:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                
                if ":" in line:
                    parts = line.split(':', 1)
                    user = parts[0].strip()
                    crypt_pass = parts[1].strip()
                    print(f"[*] Cracking Password For: {user}")
                    test_pass(crypt_pass)
    except OSError as e:
        print(f"[-] Error reading passwords file: {e}")


if __name__ == "__main__":
    main()
