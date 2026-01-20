"""Autonomous agent runtime for Druppie.

This module provides:
- Agent: Autonomous agent that uses MCPs to complete tasks
- AgentRuntime: Orchestrates multiple agents with parallel execution
- A2AProtocol: Simple agent-to-agent messaging
"""

from druppie.agents.agent import Agent
from druppie.agents.a2a import A2AProtocol, AgentMessage
from druppie.agents.runtime import AgentRuntime

__all__ = ["Agent", "AgentRuntime", "A2AProtocol", "AgentMessage"]
