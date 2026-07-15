"""Shared fixtures for agent runtime tests."""

from typing import Any
from unittest.mock import AsyncMock

import pytest

from druppie.agent_runtime.definition import AgentDefinition
from druppie.agent_runtime.events import EventEmitter
from druppie.agent_runtime.tools.mcp import MCPConnection
from druppie.agent_runtime.types import AgentEvent


@pytest.fixture
def sample_definition() -> AgentDefinition:
    """A minimal agent definition for testing."""
    return AgentDefinition(
        id="test_agent",
        name="Test Agent",
        description="A test agent for unit tests",
        system_prompt="You are a test agent.",
        mcps={},
    )


@pytest.fixture
def sample_definition_with_sandbox() -> AgentDefinition:
    """An agent definition with sandbox MCP configured."""
    return AgentDefinition(
        id="builder",
        name="Builder",
        description="Builds things",
        system_prompt="You are a builder.",
        mcps={
            "sandbox": {"tools": ["read_file", "write_file", "bash"], "git": "current_project"},
            "core-tools": {"tools": ["make_plan"]},
        },
    )


@pytest.fixture
def sample_definition_with_subagents() -> AgentDefinition:
    """An agent definition that can spawn subagents."""
    return AgentDefinition(
        id="developer",
        name="Developer",
        description="Orchestrates development",
        system_prompt="You are a developer.",
        role="both",
        subagents=["coding_planner"],
        mcps={
            "sandbox": {"tools": ["read_file", "write_file"], "git": "current_project"},
            "core-tools": {"tools": ["invoke_skill"]},
        },
    )


@pytest.fixture
def sample_definition_with_done_variables() -> AgentDefinition:
    """An agent definition with custom done_variables."""
    return AgentDefinition(
        id="planner",
        name="Planner",
        description="Plans things",
        system_prompt="You are a planner.",
        subagents=["architect", "developer"],
        done_variables={
            "next_agent": {"type": "string", "enum": ["architect", "developer"], "required": True},
            "confidence": {"type": "number", "required": False},
        },
    )


@pytest.fixture
def mock_llm():
    """A configurable mock LLM callable.

    Usage:
        mock = mock_llm()
        mock.set_responses([
            {"content": None, "tool_calls": [{"id": "tc1", "type": "function", "function": {"name": "done", "arguments": '{"summary": "done"}'}}]},
        ])
    """
    def _create():
        return MockLLM()
    return _create


class MockLLM:
    """Configurable mock LLM for testing the agent loop."""

    def __init__(self):
        self.responses: list[dict[str, Any]] = []
        self._call_index = 0
        self.calls: list[dict[str, Any]] = []

    def set_responses(self, responses: list[dict[str, Any]]) -> None:
        """Set the sequence of responses the mock will return."""
        self.responses = responses

    async def __call__(self, messages: list[dict], tools: list[dict] | None = None, **kwargs) -> dict:
        """Simulate an LLM call."""
        self.calls.append({"messages": messages, "tools": tools, "kwargs": kwargs})

        if self._call_index < len(self.responses):
            response = self.responses[self._call_index]
            self._call_index += 1
            return response

        return {"content": "No more responses configured", "tool_calls": None}


@pytest.fixture
def mock_mcp_connection():
    """A mock MCPConnection for testing."""
    def _create(
        server_name: str = "test_server",
        tool_names: list[str] | None = None,
    ) -> MCPConnection:
        tools = [
            {"name": name, "parameters": {"type": "object", "properties": {}}}
            for name in (tool_names or ["test_tool"])
        ]
        call_fn = AsyncMock(return_value={"success": True, "data": "mock result"})
        return MCPConnection(
            server_name=server_name,
            endpoint="http://localhost:9000",
            tools=tools,
            _call_tool_fn=call_fn,
        )
    return _create


@pytest.fixture
def event_collector():
    """An EventEmitter that collects events for assertions."""
    emitter = EventEmitter()
    collected: list[AgentEvent] = []
    emitter.on(lambda e: collected.append(e))
    return emitter, collected
