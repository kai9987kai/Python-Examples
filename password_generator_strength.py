#!/usr/bin/python3
"""
Description : Generates secure, cryptographically random passwords and analyzes their strength (entropy).
Author      : Antigravity
"""
import string
import secrets
import math
import sys

# Handle Python 2/3 compatibility for input
try:
    input = raw_input
except NameError:
    pass


def get_strength_rating(entropy):
    """Returns a textual rating and feedback based on password entropy."""
    if entropy < 40:
        return "Very Weak (easily guessable or brute-forced)"
    elif entropy < 60:
        return "Weak (prone to online attacks)"
    elif entropy < 80:
        return "Medium (reasonable security for low-value accounts)"
    elif entropy < 100:
        return "Strong (excellent security for standard accounts)"
    else:
        return "Very Strong (extremely secure, resistant to offline attacks)"


def generate_password(length, use_upper, use_lower, use_digits, use_special):
    """Generates a secure password and calculates its entropy."""
    # Define character pools
    pool = ""
    charset_size = 0
    
    if use_lower:
        pool += string.ascii_lowercase
        charset_size += 26
    if use_upper:
        pool += string.ascii_uppercase
        charset_size += 26
    if use_digits:
        pool += string.digits
        charset_size += 10
    if use_special:
        # A standard set of punctuation characters
        special_chars = "!@#$%^&*()-_=+[]{}|;:,.<>?/~`"
        pool += special_chars
        charset_size += len(special_chars)

    if not pool:
        raise ValueError("At least one character type must be selected!")

    # Guarantee at least one character of each selected type is included
    password_chars = []
    if use_lower:
        password_chars.append(secrets.choice(string.ascii_lowercase))
    if use_upper:
        password_chars.append(secrets.choice(string.ascii_uppercase))
    if use_digits:
        password_chars.append(secrets.choice(string.digits))
    if use_special:
        password_chars.append(secrets.choice(special_chars))

    # Fill the rest of the password length
    while len(password_chars) < length:
        password_chars.append(secrets.choice(pool))

    # Shuffle the characters cryptographically to ensure the guaranteed ones aren't always at the start
    secrets.SystemRandom().shuffle(password_chars)
    password = "".join(password_chars)

    # Calculate entropy: E = L * log2(R)
    # where L is length, R is size of character pool
    entropy = length * math.log2(charset_size)

    return password, entropy, charset_size


def get_boolean_input(prompt, default=True):
    choice = input(prompt).strip().lower()
    if not choice:
        return default
    return choice in ('y', 'yes', 'true', '1')


def main():
    print("=========================================")
    print("      SECURE PASSWORD GENERATOR &        ")
    print("             STRENGTH METER              ")
    print("=========================================")
    
    try:
        length_input = input("Enter password length [default: 16]: ").strip()
        length = int(length_input) if length_input else 16
        if length < 4:
            print("Password must be at least 4 characters long for safety.")
            length = 4
    except ValueError:
        print("Invalid length entered. Using default of 16.")
        length = 16

    print("\nConfigure Character Sets:")
    use_lower = get_boolean_input("Include lowercase letters? (Y/n): ", True)
    use_upper = get_boolean_input("Include uppercase letters? (Y/n): ", True)
    use_digits = get_boolean_input("Include numbers? (Y/n): ", True)
    use_special = get_boolean_input("Include special characters/symbols? (Y/n): ", True)

    try:
        password, entropy, charset_size = generate_password(
            length, use_upper, use_lower, use_digits, use_special
        )
    except ValueError as e:
        print(f"\nError: {e}")
        sys.exit(1)

    print("\n" + "=" * 41)
    print(f"Generated Password:  {password}")
    print("-" * 41)
    print(f"Character Pool Size: {charset_size}")
    print(f"Password Length:     {length}")
    print(f"Calculated Entropy:  {entropy:.2f} bits")
    print(f"Strength Rating:     {get_strength_rating(entropy)}")
    print("=" * 41)


if __name__ == "__main__":
    main()
