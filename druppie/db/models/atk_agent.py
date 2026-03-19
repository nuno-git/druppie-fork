"""ATK Agent database models.

Tracks declarative agents deployed to M365 Copilot via ATK CLI.
Three normalized tables: agents, shares, and deployment logs.
"""

from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID

from .base import Base, utcnow


class AtkAgent(Base):
    """A declarative agent deployed to M365 Copilot via ATK CLI."""

    __tablename__ = "atk_agents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    name = Column(String(255), unique=True, nullable=False)
    description = Column(Text)
    m365_app_id = Column(String(255), nullable=True)
    environment = Column(String(50), default="dev")
    status = Column(String(50), default="scaffolded")  # scaffolded, provisioned, deployed, shared, uninstalled, failed
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class AtkAgentShare(Base):
    """Record of an agent shared with a user."""

    __tablename__ = "atk_agent_shares"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    atk_agent_id = Column(UUID(as_uuid=True), ForeignKey("atk_agents.id"), nullable=False)
    email = Column(String(255), nullable=False)
    scope = Column(String(50), default="users")
    shared_at = Column(DateTime(timezone=True), default=utcnow)


class AtkDeploymentLog(Base):
    """Audit trail for ATK agent lifecycle actions."""

    __tablename__ = "atk_deployment_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    atk_agent_id = Column(UUID(as_uuid=True), ForeignKey("atk_agents.id"), nullable=False)
    action = Column(String(50), nullable=False)  # scaffold, provision, share, update, uninstall
    environment = Column(String(50), nullable=True)
    status = Column(String(50), nullable=False)  # success, failed
    details = Column(Text, nullable=True)
    performed_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    performed_at = Column(DateTime(timezone=True), default=utcnow)
