"""Agent Runtime Library — unified agent execution environment.

Storage-agnostic Python library for running AI agents with:
- done() enforcement
- MCP tool routing with approval gates
- Subagent spawning with depth/circular detection
- Event tracking and real-time callbacks
- Context overflow handling
- Cancellation support
"""

from druppie.agent_runtime.compaction import CompactionConfig, MessageCompactor
from druppie.agent_runtime.definition import (
    AgentDefinition,
    build_done_schema,
    load_definition,
    parse_definition,
)
from druppie.agent_runtime.events import EventEmitter
from druppie.agent_runtime.loop import AgentLoop
from druppie.agent_runtime.subagents import SubagentsMCP
from druppie.agent_runtime.tools.done import DoneTool
from druppie.agent_runtime.tools.mcp import MCPConnection
from druppie.agent_runtime.tools.provider import MCPToolProvider, ToolProvider
from druppie.agent_runtime.types import (
    AgentCancelledError,
    AgentEvent,
    AgentLoopError,
    AgentResult,
    CancellationToken,
    CompletionPrecondition,
    CompletionSummaryRequirement,
    DoneResult,
    LoopConfig,
    RequiredToolCall,
)

__all__ = [
    "CompactionConfig",
    "MessageCompactor",
    "AgentEvent",
    "AgentResult",
    "LoopConfig",
    "CancellationToken",
    "DoneResult",
    "CompletionPrecondition",
    "CompletionSummaryRequirement",
    "RequiredToolCall",
    "AgentLoopError",
    "AgentCancelledError",
    "AgentDefinition",
    "load_definition",
    "parse_definition",
    "build_done_schema",
    "EventEmitter",
    "AgentLoop",
    "ToolProvider",
    "MCPToolProvider",
    "DoneTool",
    "MCPConnection",
    "SubagentsMCP",
]
