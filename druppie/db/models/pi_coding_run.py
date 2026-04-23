"""PiCodingRun — persistence for vendored pi_agent execute_coding_task_pi runs.

Each execute_coding_task_pi invocation creates one row. The pi_agent
orchestrator streams journal events to the druppie backend over HTTP; those
events are appended to ``events`` (JSON array). On completion, ``summary``
holds the final RunSummary emitted by pi_agent, and ``status`` becomes
``succeeded`` or ``failed``.

Sibling to SandboxSession, not a replacement — execute_coding_task (legacy,
control-plane) and execute_coding_task_pi (vendored) coexist during cutover.
"""

from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID

from .base import Base, utcnow


class PiCodingRun(Base):
    __tablename__ = "pi_coding_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    run_id = Column(String(64), unique=True, nullable=False, index=True)
    session_id = Column(UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=True, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    tool_call_id = Column(UUID(as_uuid=True), ForeignKey("tool_calls.id", ondelete="SET NULL"), nullable=True, index=True)

    task_prompt = Column(Text, nullable=False)
    agent_name = Column(String(100), nullable=True)
    repo_target = Column(String(20), default="project", nullable=False, server_default="project")
    git_provider = Column(String(20), nullable=False)

    repo_owner = Column(String(255), nullable=True)
    repo_name = Column(String(255), nullable=True)
    branch_name = Column(String(255), nullable=True)
    base_sha = Column(String(64), nullable=True)

    status = Column(String(20), default="running", nullable=False, server_default="running")
    exit_code = Column(Integer, nullable=True)

    events = Column(Text, nullable=True)
    summary = Column(Text, nullable=True)
    stdout_tail = Column(Text, nullable=True)
    stderr_tail = Column(Text, nullable=True)

    pr_url = Column(String(500), nullable=True)
    pr_number = Column(Integer, nullable=True)

    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    completed_at = Column(DateTime(timezone=True), nullable=True)
