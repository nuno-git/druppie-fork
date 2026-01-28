"""LLM call database model."""

from typing import Any
from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from .base import Base, utcnow


class LlmCall(Base):
    """Tracks LLM API calls for cost transparency and debugging."""

    __tablename__ = "llm_calls"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"))
    agent_run_id = Column(UUID(as_uuid=True), ForeignKey("agent_runs.id"))
    provider = Column(String(50), nullable=False)  # deepinfra, zai, openai
    model = Column(String(100), nullable=False)
    prompt_tokens = Column(Integer, nullable=False)
    completion_tokens = Column(Integer, nullable=False)
    total_tokens = Column(Integer, nullable=False)
    duration_ms = Column(Integer)
    # Full request/response data for debugging
    request_messages = Column(JSON)  # Array of messages sent to LLM
    response_content = Column(Text)  # LLM response text
    response_tool_calls = Column(JSON)  # Tool calls returned by LLM
    tools_provided = Column(JSON)  # Tools available to the LLM
    created_at = Column(DateTime(timezone=True), default=utcnow)

    # Relationships
    tool_calls = relationship("ToolCall", back_populates="llm_call", order_by="ToolCall.tool_call_index")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "session_id": str(self.session_id) if self.session_id else None,
            "agent_run_id": str(self.agent_run_id) if self.agent_run_id else None,
            "provider": self.provider,
            "model": self.model,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "duration_ms": self.duration_ms,
            "request_messages": self.request_messages,
            "response_content": self.response_content,
            "response_tool_calls": self.response_tool_calls,
            "tools_provided": self.tools_provided,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
