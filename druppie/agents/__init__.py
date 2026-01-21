"""Agent module - clean abstraction for running agents.

Usage:
    from druppie.agents import Agent

    result = await Agent("router").run("Create a todo app")
"""

from druppie.agents.runtime import Agent, AgentError, AgentNotFoundError, AgentMaxIterationsError
from druppie.agents.models import AgentDefinition, AgentResult

__all__ = [
    "Agent",
    "AgentError",
    "AgentNotFoundError",
    "AgentMaxIterationsError",
    "AgentDefinition",
    "AgentResult",
]
