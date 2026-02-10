"""Tool call database model."""

from typing import TYPE_CHECKING, Any
from uuid import uuid4

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from .base import Base, utcnow

if TYPE_CHECKING:
    from druppie.domain.tool import ToolDefinition


class ToolCall(Base):
    """A tool call made by an agent.

    Tool calls represent MCP tool invocations (e.g., coding:write_file) or
    built-in tools (e.g., execute_agent, done).

    The `arguments` column stores tool parameters as JSONB. This is consistent
    with how `approvals.arguments` stores the same data. We use JSONB because:
    1. Arguments are only used for display, never queried individually
    2. Simpler schema (no separate table, no JOINs)
    3. Single atomic insert when creating a tool call

    Tool metadata (description, parameter schema) is available via the
    `definition` property, which looks up the tool in the ToolRegistry.
    """

    __tablename__ = "tool_calls"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"))
    agent_run_id = Column(UUID(as_uuid=True), ForeignKey("agent_runs.id"))
    llm_call_id = Column(UUID(as_uuid=True), ForeignKey("llm_calls.id"))

    mcp_server = Column(String(100), nullable=False)
    tool_name = Column(Text, nullable=False)
    tool_call_index = Column(Integer, default=0)  # Order in the LLM response (0, 1, 2...)

    # Tool arguments as JSONB
    arguments = Column(JSON)

    status = Column(String(20), default="pending")  # pending, waiting_approval, executing, completed, failed
    result = Column(Text)
    error_message = Column(Text)

    created_at = Column(DateTime(timezone=True), default=utcnow)
    executed_at = Column(DateTime(timezone=True))

    # Relationships
    agent_run = relationship("AgentRun", back_populates="tool_calls")
    llm_call = relationship("LlmCall", back_populates="tool_calls")

    # -------------------------------------------------------------------------
    # Tool Definition Access (from ToolRegistry)
    # -------------------------------------------------------------------------

    @property
    def definition(self) -> "ToolDefinition | None":
        """Get the tool definition from the registry.

        Returns:
            ToolDefinition or None if not found in registry
        """
        from druppie.core.tool_registry import get_tool_registry

        return get_tool_registry().get_by_server_and_name(self.mcp_server, self.tool_name)

    @property
    def full_name(self) -> str:
        """Get full tool name (e.g., 'coding_write_file' or 'done')."""
        if self.mcp_server and self.mcp_server != "builtin":
            return f"{self.mcp_server}_{self.tool_name}"
        return self.tool_name

    @property
    def tool_description(self) -> str:
        """Get tool description from definition."""
        defn = self.definition
        return defn.description if defn else ""

    def validate_arguments(self) -> tuple[bool, str | None]:
        """Validate arguments against tool schema.

        Returns:
            Tuple of (is_valid, error_message)
        """
        defn = self.definition
        if not defn:
            return True, None  # Can't validate without definition
        is_valid, error, _ = defn.validate_arguments(self.arguments or {})
        return is_valid, error

    # -------------------------------------------------------------------------
    # Serialization
    # -------------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "id": str(self.id),
            "session_id": str(self.session_id) if self.session_id else None,
            "agent_run_id": str(self.agent_run_id) if self.agent_run_id else None,
            "llm_call_id": str(self.llm_call_id) if self.llm_call_id else None,
            "mcp_server": self.mcp_server,
            "tool_name": self.tool_name,
            "full_name": self.full_name,
            "tool_call_index": self.tool_call_index or 0,
            "description": self.tool_description,
            "status": self.status,
            "result": self.result,
            "error_message": self.error_message,
            "arguments": self.arguments or {},
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "executed_at": self.executed_at.isoformat() if self.executed_at else None,
        }
