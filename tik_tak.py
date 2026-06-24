"""
Advanced Tic-Tac-Toe
Two-player terminal game
"""

from typing import List, Optional


WINNING_COMBINATIONS = (
    (0, 1, 2),
    (3, 4, 5),
    (6, 7, 8),
    (0, 3, 6),
    (1, 4, 7),
    (2, 5, 8),
    (0, 4, 8),
    (2, 4, 6),
)


def create_board() -> List[str]:
    """Create an empty numbered board."""
    return [str(number) for number in range(1, 10)]


def print_board(board: List[str]) -> None:
    """Display the current board."""
    print("\n")
    print(f" {board[0]} | {board[1]} | {board[2]} ")
    print("---+---+---")
    print(f" {board[3]} | {board[4]} | {board[5]} ")
    print("---+---+---")
    print(f" {board[6]} | {board[7]} | {board[8]} ")
    print()


def choose_symbol(player_number: int, unavailable: Optional[str] = None) -> str:
    """Allow a player to choose X or O."""
    while True:
        symbol = input(f"Player {player_number}, choose X or O: ").strip().upper()

        if symbol not in ("X", "O"):
            print("Please enter X or O.")
        elif symbol == unavailable:
            print(f"That symbol is already taken. Choose {'O' if symbol == 'X' else 'X'}.")
        else:
            return symbol


def get_move(board: List[str], player_number: int, symbol: str) -> int:
    """Get and validate a player's board position."""
    while True:
        choice = input(f"Player {player_number} ({symbol}), choose a position (1-9): ").strip()

        if not choice.isdigit():
            print("Please enter a number from 1 to 9.")
            continue

        position = int(choice)

        if position < 1 or position > 9:
            print("That position is outside the board. Choose 1 to 9.")
            continue

        index = position - 1

        if board[index] in ("X", "O"):
            print("That position is already taken. Choose another one.")
            continue

        return index


def check_winner(board: List[str], symbol: str) -> bool:
    """Return True when the supplied symbol has won."""
    return any(
        board[a] == board[b] == board[c] == symbol
        for a, b, c in WINNING_COMBINATIONS
    )


def is_draw(board: List[str]) -> bool:
    """Return True when no free spaces remain."""
    return all(space in ("X", "O") for space in board)


def play_game() -> None:
    """Run one complete game."""
    board = create_board()

    print("\n" + "=" * 35)
    print("          TIC-TAC-TOE")
    print("=" * 35)
    print("Choose positions using the numbers shown.")

    print_board(board)

    player_1_symbol = choose_symbol(1)
    player_2_symbol = choose_symbol(2, unavailable=player_1_symbol)

    current_player = 1
    symbols = {
        1: player_1_symbol,
        2: player_2_symbol,
    }

    while True:
        current_symbol = symbols[current_player]
        move = get_move(board, current_player, current_symbol)

        board[move] = current_symbol
        print_board(board)

        if check_winner(board, current_symbol):
            print(f"Congratulations! Player {current_player} ({current_symbol}) wins! 🏆")
            break

        if is_draw(board):
            print("The game is a draw!")
            break

        current_player = 2 if current_player == 1 else 1


def main() -> None:
    """Allow repeated games."""
    while True:
        play_game()

        again = input("\nPlay again? (Y/N): ").strip().upper()
        if again != "Y":
            print("\nThanks for playing Tic-Tac-Toe!")
            break


if __name__ == "__main__":
    main()
