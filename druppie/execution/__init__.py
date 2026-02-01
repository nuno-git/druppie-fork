"""Execution layer - coordinates agent runs and tool execution.

See README.md in this folder for detailed documentation.

Quick overview:
- Orchestrator: Entry point, manages sessions and pending runs
- ToolExecutor: Single entry point for ALL tool execution
- MCPHttp: Simple HTTP client for MCP servers

Key design decisions:
1. Pending runs pattern: Create agent runs as pending, execute_pending_runs() handles all
2. ToolExecutor handles everything: builtin tools, HITL, MCP (with approval checking)
3. ToolCall is the central record: Question and Approval link back to it
4. Agent only completes when it calls the `done` tool
"""

from druppie.execution.orchestrator import Orchestrator
from druppie.execution.tool_executor import ToolExecutor, ToolCallStatus
from druppie.execution.mcp_http import MCPHttp, MCPHttpError
from druppie.execution.tool_context import ToolContext

__all__ = [
    "Orchestrator",
    "ToolExecutor",
    "ToolCallStatus",
    "MCPHttp",
    "MCPHttpError",
    "ToolContext",
]
