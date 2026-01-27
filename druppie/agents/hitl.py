"""Backwards compatibility - all tools moved to builtin_tools.py"""

from druppie.agents.builtin_tools import (
    BUILTIN_TOOLS as HITL_TOOLS,
    execute_builtin_tool as execute_hitl_tool,
    is_builtin_tool as is_hitl_tool,
    ask_question,
    ask_multiple_choice_question,
)

__all__ = [
    "HITL_TOOLS",
    "execute_hitl_tool",
    "is_hitl_tool",
    "ask_question",
    "ask_multiple_choice_question",
]
