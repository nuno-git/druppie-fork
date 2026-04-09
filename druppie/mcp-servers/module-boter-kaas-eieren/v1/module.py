"""Boter-Kaas-Eieren Module v1 — Public API.

Entry point for v1 business logic. One public method per MCP tool.
Imported by v1/tools.py for MCP exposure.
"""

import uuid
import json
import random
from typing import Dict, Any

from .. import db

# Win conditions (row, column, diagonal combinations)
WIN_CONDITIONS = [
    [0, 1, 2],  # Top row
    [3, 4, 5],  # Middle row
    [6, 7, 8],  # Bottom row
    [0, 3, 6],  # Left column
    [1, 4, 7],  # Middle column
    [2, 5, 8],  # Right column
    [0, 4, 8],  # Diagonal
    [2, 4, 6],  # Anti-diagonal
]


def new_game() -> Dict[str, Any]:
    """Create a new tic-tac-toe game.

    Returns:
        Dict with game_id, board, current_player, game_active, result
    """
    game_id = str(uuid.uuid4())
    board = ["", "", "", "", "", "", "", "", ""]

    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO games (id, board, current_player, game_active, result)
            VALUES (?, ?, ?, ?, ?)
            """,
            (game_id, json.dumps(board), "X", True, None),
        )
        conn.commit()

    return {
        "game_id": game_id,
        "board": board,
        "current_player": "X",
        "game_active": True,
        "result": None,
    }


def make_move(game_id: str, position: int) -> Dict[str, Any]:
    """Make a move in the game.

    Args:
        game_id: The game identifier
        position: Board position (0-8)

    Returns:
        Updated game state

    Raises:
        ValueError: If move is invalid
    """
    # Validate position
    if not 0 <= position <= 8:
        raise ValueError(f"Position must be between 0 and 8, got {position}")

    with db.get_db() as conn:
        cursor = conn.cursor()

        # Get current game state
        cursor.execute("SELECT * FROM games WHERE id = ?", (game_id,))
        row = cursor.fetchone()

        if not row:
            raise ValueError(f"Game {game_id} not found")

        board = json.loads(row["board"])
        current_player = row["current_player"]
        game_active = row["game_active"]

        if not game_active:
            raise ValueError(f"Game {game_id} is already finished")

        # Check if cell is empty
        if board[position] != "":
            raise ValueError(f"Position {position} is already occupied")

        # Player X makes a move
        board[position] = "X"

        # Check for win/draw after player's move
        result = _check_result(board, "X")
        if result:
            game_active = False
        elif "" not in board:
            result = "draw"
            game_active = False

        # AI (O) makes a move if game is still active
        if game_active:
            board = _ai_move(board)
            result = _check_result(board, "O")
            if result:
                game_active = False
            elif "" not in board:
                result = "draw"
                game_active = False

        # Update database
        cursor.execute(
            """
            UPDATE games
            SET board = ?, current_player = ?, game_active = ?, result = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (json.dumps(board), "X", game_active, result, game_id),
        )
        conn.commit()

        return {
            "game_id": game_id,
            "board": board,
            "current_player": "X",
            "game_active": game_active,
            "result": result,
        }


def get_game_state(game_id: str) -> Dict[str, Any]:
    """Get the current state of a game.

    Args:
        game_id: The game identifier

    Returns:
        Current game state

    Raises:
        ValueError: If game not found
    """
    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM games WHERE id = ?", (game_id,))
        row = cursor.fetchone()

        if not row:
            raise ValueError(f"Game {game_id} not found")

        return {
            "game_id": row["id"],
            "board": json.loads(row["board"]),
            "current_player": row["current_player"],
            "game_active": bool(row["game_active"]),
            "result": row["result"],
        }


def _check_result(board: list, player: str) -> str | None:
    """Check if the given player has won.

    Args:
        board: Current board state
        player: Player to check ("X" or "O")

    Returns:
        "X_wins", "O_wins", or None
    """
    for condition in WIN_CONDITIONS:
        if all(board[i] == player for i in condition):
            return f"{player}_wins"
    return None


def _ai_move(board: list) -> list:
    """AI makes a move using minimax with 40% randomization.

    Args:
        board: Current board state

    Returns:
        Updated board with AI move
    """
    # 40% chance of random move (makes AI beatable)
    if random.random() < 0.4:
        empty_cells = [i for i, cell in enumerate(board) if cell == ""]
        if empty_cells:
            position = random.choice(empty_cells)
            board[position] = "O"
            return board

    # Otherwise, use minimax for optimal play
    best_score = float("-inf")
    best_position = None

    empty_cells = [i for i, cell in enumerate(board) if cell == ""]

    for position in empty_cells:
        board[position] = "O"
        score = _minimax(board, 0, False)
        board[position] = ""  # Undo move

        if score > best_score:
            best_score = score
            best_position = position

    if best_position is not None:
        board[best_position] = "O"

    return board


def _minimax(board: list, depth: int, is_maximizing: bool) -> int:
    """Minimax algorithm with alpha-beta pruning.

    Args:
        board: Current board state
        depth: Current depth in the game tree
        is_maximizing: True if AI's turn, False if player's turn

    Returns:
        Score for the current position
    """
    # Check terminal states
    if _check_result(board, "O"):
        return 10 - depth  # AI wins, prefer faster wins
    if _check_result(board, "X"):
        return depth - 10  # Player wins, prefer longer losses
    if "" not in board:
        return 0  # Draw

    if is_maximizing:
        best_score = -1000
        for i in range(9):
            if board[i] == "":
                board[i] = "O"
                score = _minimax(board, depth + 1, False)
                board[i] = ""
                best_score = max(score, best_score)
        return best_score
    else:
        best_score = 1000
        for i in range(9):
            if board[i] == "":
                board[i] = "X"
                score = _minimax(board, depth + 1, True)
                board[i] = ""
                best_score = min(score, best_score)
        return best_score
