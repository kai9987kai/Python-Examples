"""
Advanced Tic-Tac-Toe
Python 3 terminal edition
"""

import random

EMPTY = " "
PLAYER = "player"
COMPUTER = "computer"


def draw_board(board):
    """Display the board. Empty spaces show their move number."""
    def cell(index):
        return board[index] if board[index] != EMPTY else str(index + 1)

    print("\n")
    print(f" {cell(0)} | {cell(1)} | {cell(2)} ")
    print("---+---+---")
    print(f" {cell(3)} | {cell(4)} | {cell(5)} ")
    print("---+---+---")
    print(f" {cell(6)} | {cell(7)} | {cell(8)} ")
    print()


def get_choice(prompt, choices):
    """Keep asking until the player enters a valid choice."""
    while True:
        answer = input(prompt).strip().lower()
        if answer in choices:
            return answer
        print(f"Please enter one of: {', '.join(choices)}")


def choose_letter():
    """Return player and computer letters."""
    choice = get_choice("Choose X or O: ", ["x", "o"])

    if choice == "x":
        return "X", "O"
    return "O", "X"


def choose_difficulty():
    """Choose AI difficulty."""
    print("\nDifficulty levels:")
    print("1. Easy   - random moves")
    print("2. Medium - blocks and takes winning moves")
    print("3. Hard   - unbeatable minimax AI")

    choice = get_choice("Select difficulty (1-3): ", ["1", "2", "3"])
    return {"1": "easy", "2": "medium", "3": "hard"}[choice]


def available_moves(board):
    """Return all available board positions."""
    return [index for index, value in enumerate(board) if value == EMPTY]


def make_move(board, index, letter):
    """Place a letter on the board if possible."""
    if index not in range(9):
        return False

    if board[index] != EMPTY:
        return False

    board[index] = letter
    return True


def check_winner(board, letter):
    """Return True when the supplied letter has won."""
    winning_lines = [
        (0, 1, 2), (3, 4, 5), (6, 7, 8),
        (0, 3, 6), (1, 4, 7), (2, 5, 8),
        (0, 4, 8), (2, 4, 6)
    ]

    return any(
        board[a] == letter and board[b] == letter and board[c] == letter
        for a, b, c in winning_lines
    )


def is_board_full(board):
    return EMPTY not in board


def get_player_move(board):
    """Ask the player for a valid move. Returns None when they quit."""
    while True:
        choice = input("Choose a square (1-9), or Q to quit: ").strip().lower()

        if choice == "q":
            return None

        if not choice.isdigit():
            print("Enter a number from 1 to 9.")
            continue

        move = int(choice) - 1

        if move not in range(9):
            print("That square does not exist.")
        elif board[move] != EMPTY:
            print("That square is already occupied.")
        else:
            return move


def find_winning_move(board, letter):
    """Return a winning position for letter, or None."""
    for move in available_moves(board):
        test_board = board[:]
        test_board[move] = letter

        if check_winner(test_board, letter):
            return move

    return None


def get_medium_move(board, computer_letter, player_letter):
    """Tactical AI: win, block, prioritise centre/corners."""
    winning_move = find_winning_move(board, computer_letter)
    if winning_move is not None:
        return winning_move

    blocking_move = find_winning_move(board, player_letter)
    if blocking_move is not None:
        return blocking_move

    if board[4] == EMPTY:
        return 4

    corners = [0, 2, 6, 8]
    open_corners = [move for move in corners if board[move] == EMPTY]

    if open_corners:
        return random.choice(open_corners)

    return random.choice(available_moves(board))


def minimax(board, computer_letter, player_letter, maximizing, depth, alpha, beta):
    """
    Evaluate the best possible score.
    Uses alpha-beta pruning to make hard AI faster.
    """
    if check_winner(board, computer_letter):
        return 10 - depth

    if check_winner(board, player_letter):
        return depth - 10

    if is_board_full(board):
        return 0

    if maximizing:
        best_score = float("-inf")

        for move in available_moves(board):
            board[move] = computer_letter
            score = minimax(
                board, computer_letter, player_letter,
                False, depth + 1, alpha, beta
            )
            board[move] = EMPTY

            best_score = max(best_score, score)
            alpha = max(alpha, best_score)

            if beta <= alpha:
                break

        return best_score

    best_score = float("inf")

    for move in available_moves(board):
        board[move] = player_letter
        score = minimax(
            board, computer_letter, player_letter,
            True, depth + 1, alpha, beta
        )
        board[move] = EMPTY

        best_score = min(best_score, score)
        beta = min(beta, best_score)

        if beta <= alpha:
            break

    return best_score


def get_hard_move(board, computer_letter, player_letter):
    """Choose the strongest possible move using minimax."""
    best_score = float("-inf")
    best_moves = []

    for move in available_moves(board):
        board[move] = computer_letter

        score = minimax(
            board, computer_letter, player_letter,
            False, 0, float("-inf"), float("inf")
        )

        board[move] = EMPTY

        if score > best_score:
            best_score = score
            best_moves = [move]
        elif score == best_score:
            best_moves.append(move)

    return random.choice(best_moves)


def get_computer_move(board, computer_letter, player_letter, difficulty):
    """Return a move based on selected difficulty."""
    if difficulty == "easy":
        return random.choice(available_moves(board))

    if difficulty == "medium":
        return get_medium_move(board, computer_letter, player_letter)

    return get_hard_move(board, computer_letter, player_letter)


def play_game(difficulty, scores):
    """Run one complete game."""
    board = [EMPTY] * 9
    player_letter, computer_letter = choose_letter()

    # X always starts in standard Tic-Tac-Toe.
    turn = PLAYER if player_letter == "X" else COMPUTER

    print(f"\nYou are {player_letter}. Computer is {computer_letter}.")
    print(f"{turn.capitalize()} goes first.")

    while True:
        draw_board(board)

        if turn == PLAYER:
            move = get_player_move(board)

            if move is None:
                print("\nYou resigned. Computer wins this round.")
                scores[COMPUTER] += 1
                return

            make_move(board, move, player_letter)

            if check_winner(board, player_letter):
                draw_board(board)
                print("You won! Excellent game.")
                scores[PLAYER] += 1
                return

            turn = COMPUTER

        else:
            print("Computer is thinking...")
            move = get_computer_move(
                board, computer_letter, player_letter, difficulty
            )
            make_move(board, move, computer_letter)

            if check_winner(board, computer_letter):
                draw_board(board)
                print("The computer wins this round.")
                scores[COMPUTER] += 1
                return

            turn = PLAYER

        if is_board_full(board):
            draw_board(board)
            print("It is a tie.")
            scores["ties"] += 1
            return


def show_scoreboard(scores):
    """Display session statistics."""
    print("\n====== SCOREBOARD ======")
    print(f"You:      {scores[PLAYER]}")
    print(f"Computer: {scores[COMPUTER]}")
    print(f"Ties:     {scores['ties']}")
    print("========================")


def main():
    print("=" * 32)
    print("   ADVANCED TIC-TAC-TOE")
    print("=" * 32)

    scores = {
        PLAYER: 0,
        COMPUTER: 0,
        "ties": 0
    }

    difficulty = choose_difficulty()

    while True:
        play_game(difficulty, scores)
        show_scoreboard(scores)

        again = get_choice(
            "\nPlay again? (y = same difficulty, d = change difficulty, n = quit): ",
            ["y", "d", "n"]
        )

        if again == "n":
            print("\nThanks for playing!")
            break

        if again == "d":
            difficulty = choose_difficulty()


if __name__ == "__main__":
    main()
