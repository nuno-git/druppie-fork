"""Boter-Kaas-Eieren v1 — MCP Tool Definitions.

Wraps v1/module.py business logic as MCP tools via FastMCP.
This file is the SINGLE SOURCE OF TRUTH for the tool contract:
- Tool name, description, input schema → via @mcp.tool() decorator
- Version, resource metrics → via @mcp.tool(meta={...})
- Agent guidance → via FastMCP(instructions=...)
All discoverable by MCP clients via initialize + tools/list.
"""

import os
import time
from fastmcp import FastMCP
from .module import new_game, make_move, get_game_state

MODULE_ID = "boter-kaas-eieren"
MODULE_VERSION = "1.0.0"

mcp = FastMCP(
    "Boter-Kaas-Eieren v1",
    version=MODULE_VERSION,
    instructions="""Tic-tac-toe game module (Dutch: Boter-Kaas-Eieren).

Use when:
- You want to play a game of tic-tac-toe
- You need to create a new game, make moves, or check game state

Don't use when:
- You need to play other types of games
- You need to manage multiple games simultaneously
""",
)


@mcp.tool(
    name="new_game",
    description="Create a new tic-tac-toe game. Returns game_id and initial board state.",
    meta={
        "module_id": MODULE_ID,
        "version": MODULE_VERSION,
        "resource_metrics": {
            "processing_ms": {"type": "integer", "unit": "milliseconds"},
        },
    },
)
async def new_game_tool(
    user_id: str = "",
    project_id: str = "",
    session_id: str = "",
    app_id: str = "",
) -> dict:
    """Create a new tic-tac-toe game."""
    start = time.time()
    result = new_game()
    elapsed_ms = int((time.time() - start) * 1000)
    return {
        **result,
        "_meta": {
            "module_id": MODULE_ID,
            "module_version": MODULE_VERSION,
            "usage": {
                "cost_cents": 0.0,
                "resources": {"processing_ms": elapsed_ms},
            },
        },
    }


@mcp.tool(
    name="make_move",
    description="Make a move in a tic-tac-toe game. After player (X) moves, AI (O) responds automatically.",
    meta={
        "module_id": MODULE_ID,
        "version": MODULE_VERSION,
        "resource_metrics": {
            "processing_ms": {"type": "integer", "unit": "milliseconds"},
        },
    },
)
async def make_move_tool(
    game_id: str,
    position: int,
    user_id: str = "",
    project_id: str = "",
    session_id: str = "",
    app_id: str = "",
) -> dict:
    """Make a move in the game (0-8 position)."""
    start = time.time()
    result = make_move(game_id, position)
    elapsed_ms = int((time.time() - start) * 1000)
    return {
        **result,
        "_meta": {
            "module_id": MODULE_ID,
            "module_version": MODULE_VERSION,
            "usage": {
                "cost_cents": 0.0,
                "resources": {"processing_ms": elapsed_ms},
            },
        },
    }


@mcp.tool(
    name="get_game_state",
    description="Get the current state of a tic-tac-toe game including board, whose turn it is, and game result if finished.",
    meta={
        "module_id": MODULE_ID,
        "version": MODULE_VERSION,
        "resource_metrics": {
            "processing_ms": {"type": "integer", "unit": "milliseconds"},
        },
    },
)
async def get_game_state_tool(
    game_id: str,
    user_id: str = "",
    project_id: str = "",
    session_id: str = "",
    app_id: str = "",
) -> dict:
    """Get the current game state."""
    start = time.time()
    result = get_game_state(game_id)
    elapsed_ms = int((time.time() - start) * 1000)
    return {
        **result,
        "_meta": {
            "module_id": MODULE_ID,
            "module_version": MODULE_VERSION,
            "usage": {
                "cost_cents": 0.0,
                "resources": {"processing_ms": elapsed_ms},
            },
        },
    }
