#!/usr/bin/env python3
"""
Script Name     : rock_paper_scissors.py
Description     : An interactive terminal-based Rock, Paper, Scissors game.
                  Features abbreviations, score tracking, and clean math logic.
"""

import random
import sys


def get_computer_choice():
    """Returns a random choice of rock, paper, or scissors."""
    return random.choice(["rock", "paper", "scissors"])


def evaluate_winner(player, computer):
    """
    Evaluates the winner of the round.
    Returns: 'draw', 'player', or 'computer'
    """
    choices = {"rock": 0, "paper": 1, "scissors": 2}
    p_num = choices[player]
    c_num = choices[computer]
    
    if p_num == c_num:
        return 'draw'
    elif (p_num - c_num) % 3 == 1:
        return 'player'
    else:
        return 'computer'


def main():
    print("=========================================")
    print("       ROCK, PAPER, SCISSORS GAME        ")
    print("=========================================")
    print("Rules: Rock beats Scissors, Scissors beats Paper, Paper beats Rock.")
    print("You can enter 'r', 'p', 's', or the full word. Enter 'q' to exit.")
    print("-" * 41)

    player_score = 0
    computer_score = 0
    ties = 0

    input_mapping = {
        'r': 'rock', 'rock': 'rock',
        'p': 'paper', 'paper': 'paper',
        's': 'scissors', 'scissors': 'scissors'
    }

    while True:
        user_input = input("\nYour Move [r/p/s] or 'q' to quit: ").strip().lower()
        
        if user_input == 'q':
            print("\nFinal Scores:")
            print(f"  You      : {player_score}")
            print(f"  Computer : {computer_score}")
            print(f"  Ties     : {ties}")
            print("\nThanks for playing! Goodbye.")
            break
            
        if user_input not in input_mapping:
            print("[-] Invalid input. Please enter 'r', 'p', 's', or 'q'.")
            continue

        player_move = input_mapping[user_input]
        computer_move = get_computer_choice()
        
        print(f"[*] You chose      : {player_move.capitalize()}")
        print(f"[*] Computer chose : {computer_move.capitalize()}")
        
        result = evaluate_winner(player_move, computer_move)
        
        if result == 'draw':
            print("[=] It's a draw!")
            ties += 1
        elif result == 'player':
            print("[+] You won this round! 🎉")
            player_score += 1
        else:
            print("[-] Computer won this round. 🤖")
            computer_score += 1
            
        print(f"Scoreboard -> You: {player_score} | Computer: {computer_score} | Ties: {ties}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n[*] Game interrupted. Goodbye!")
        sys.exit(0)
