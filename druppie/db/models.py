"""SQLAlchemy database models for Druppie platform.

Simplified schema for sessions and approvals.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import Column, DateTime, Enum, ForeignKey, JSON, String, Text
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()


class Session(Base):
    """Session model for tracking execution state."""

    __tablename__ = "sessions"

    id = Column(String(36), primary_key=True)  # UUID
    user_id = Column(String(255), nullable=True, index=True)
    status = Column(
        String(20),
        default="active",
        index=True,
    )  # active, paused, completed, failed
    state = Column(JSON, nullable=True)  # ExecutionState as JSON
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "status": self.status,
            "state": self.state,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class Approval(Base):
    """Approval model for tracking approval requests."""

    __tablename__ = "approvals"

    id = Column(String(36), primary_key=True)  # UUID
    session_id = Column(String(36), ForeignKey("sessions.id"), nullable=False, index=True)
    tool_name = Column(String(255), nullable=False)
    arguments = Column(JSON, nullable=True)
    status = Column(
        String(20),
        default="pending",
        index=True,
    )  # pending, approved, rejected
    required_roles = Column(JSON, nullable=True)  # List of roles that can approve
    approvals_received = Column(JSON, nullable=True)  # List of {user_id, role, timestamp}
    danger_level = Column(String(20), default="low")  # low, medium, high, critical
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "tool_name": self.tool_name,
            "arguments": self.arguments,
            "status": self.status,
            "required_roles": self.required_roles,
            "approvals_received": self.approvals_received,
            "danger_level": self.danger_level,
            "description": self.description,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
