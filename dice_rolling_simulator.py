#!/usr/bin/env python3
"""
Script Name     : dice_rolling_simulator.py
Description     : A terminal-based Dice Rolling Simulator. Supports standard
                  dice shapes (d6, d8, d12) and loops interactively.
"""

import random
import sys


def roll_die(sides):
    """Generates a random value simulating a die roll."""
    value = random.randint(1, sides)
    print(f"\n[+] You rolled a d{sides} and got: {value}!")


def main():
    print("=========================================")
    print("       DICE ROLLING SIMULATOR            ")
    print("=========================================")
    print("Welcome! Roll different dice types interactively.")
    
    while True:
        print("\nChoose a die to roll:")
        print("  [6]  - 6-sided die (d6)")
        print("  [8]  - 8-sided die (d8)")
        print("  [12] - 12-sided die (d12)")
        print("  [q]  - Quit the simulator")
        
        choice = input("\nSelect an option: ").strip().lower()
        
        if choice in ('q', 'exit', 'quit'):
            print("\nThanks for using the Dice Rolling Simulator! Have a great day! =)")
            break
            
        try:
            sides = int(choice)
            if sides in (6, 8, 12):
                roll_die(sides)
            else:
                print("[-] Invalid selection. Please choose 6, 8, 12, or 'q'.")
                continue
        except ValueError:
            print("[-] Invalid input. Please enter a valid number (6, 8, 12) or 'q'.")
            continue
            
        # Prompt user if they want to roll again or exit immediately
        while True:
            action = input("\nType [roll] to select another die, or [exit] to quit: ").strip().lower()
            if action in ('roll', 'r'):
                break
            elif action in ('exit', 'e', 'q', 'quit'):
                print("\nThanks for using the Dice Rolling Simulator! Have a great day! =)")
                return
            else:
                print("[-] Invalid command. Enter 'roll' or 'exit'.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n[*] Simulator interrupted. Goodbye!")
        sys.exit(0)
