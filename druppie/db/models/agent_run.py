"""Agent run and message database models."""

from typing import Any
from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from .base import Base, utcnow


class AgentRun(Base):
    """Tracks each agent execution for message isolation.

    Agent runs can be:
    - Created by planner with status='pending' (planned runs)
    - Created at runtime with status='running' (immediate execution)

    For pending runs created by planner:
    - planned_prompt: The task description for the agent
    - sequence_number: Execution order (0, 1, 2...)
    """

    __tablename__ = "agent_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"))
    agent_id = Column(String(100), nullable=False)
    parent_run_id = Column(UUID(as_uuid=True), ForeignKey("agent_runs.id"))

    # pending = created by planner, not started yet
    status = Column(String(20), default="running")  # pending, running, paused_tool, paused_hitl, completed, failed
    iteration_count = Column(Integer, default=0)

    # For pending runs created by planner
    planned_prompt = Column(Text)  # Task description for the agent
    sequence_number = Column(Integer)  # Execution order (0, 1, 2...)

    prompt_tokens = Column(Integer, default=0)
    completion_tokens = Column(Integer, default=0)
    total_tokens = Column(Integer, default=0)

    started_at = Column(DateTime(timezone=True), default=utcnow)
    completed_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=utcnow)

    # Relationships
    messages = relationship("Message", back_populates="agent_run")
    tool_calls = relationship("ToolCall", back_populates="agent_run")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "session_id": str(self.session_id) if self.session_id else None,
            "agent_id": self.agent_id,
            "parent_run_id": str(self.parent_run_id) if self.parent_run_id else None,
            "status": self.status,
            "iteration_count": self.iteration_count,
            "planned_prompt": self.planned_prompt,
            "sequence_number": self.sequence_number,
            "prompt_tokens": self.prompt_tokens or 0,
            "completion_tokens": self.completion_tokens or 0,
            "total_tokens": self.total_tokens or 0,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Message(Base):
    """A message in the conversation."""

    __tablename__ = "messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"))
    agent_run_id = Column(UUID(as_uuid=True), ForeignKey("agent_runs.id"))

    role = Column(String(20), nullable=False)  # user, assistant, system, tool
    content = Column(Text, nullable=False)

    agent_id = Column(String(100))  # For assistant messages
    tool_name = Column(String(200))  # For tool messages
    tool_call_id = Column(String(100))  # For tool messages

    sequence_number = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    agent_run = relationship("AgentRun", back_populates="messages")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "session_id": str(self.session_id) if self.session_id else None,
            "agent_run_id": str(self.agent_run_id) if self.agent_run_id else None,
            "role": self.role,
            "content": self.content,
            "agent_id": self.agent_id,
            "tool_name": self.tool_name,
            "tool_call_id": self.tool_call_id,
            "sequence_number": self.sequence_number,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
