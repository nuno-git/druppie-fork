"""Custom agent database models."""

from uuid import uuid4

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from .base import Base, utcnow


class CustomAgent(Base):
    """A user-created custom agent definition stored in the database."""

    __tablename__ = "custom_agents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    agent_id = Column(String(100), unique=True, nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    category = Column(String(50), default="execution")
    system_prompt = Column(Text)
    llm_profile = Column(String(50), default="standard")
    temperature = Column(Float, default=0.1)
    max_tokens = Column(Integer, default=4096)
    max_iterations = Column(Integer, default=10)
    owner_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    is_active = Column(Boolean, default=True)
    deployment_status = Column(String(50), nullable=True)
    deployed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    # Relationships
    mcps = relationship("CustomAgentMcp", back_populates="custom_agent", cascade="all, delete-orphan")
    skills = relationship("CustomAgentSkill", back_populates="custom_agent", cascade="all, delete-orphan")
    system_prompts = relationship("CustomAgentSystemPrompt", back_populates="custom_agent", cascade="all, delete-orphan")
    builtin_tools = relationship("CustomAgentBuiltinTool", back_populates="custom_agent", cascade="all, delete-orphan")
    approval_overrides = relationship("CustomAgentApprovalOverride", back_populates="custom_agent", cascade="all, delete-orphan")
    foundry_tools = relationship("CustomAgentFoundryTool", back_populates="custom_agent", cascade="all, delete-orphan")


class CustomAgentMcp(Base):
    """MCP server association for a custom agent."""

    __tablename__ = "custom_agent_mcps"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    custom_agent_id = Column(UUID(as_uuid=True), ForeignKey("custom_agents.id", ondelete="CASCADE"), nullable=False)
    mcp_name = Column(String(100), nullable=False)

    # Relationships
    custom_agent = relationship("CustomAgent", back_populates="mcps")
    tools = relationship("CustomAgentMcpTool", back_populates="mcp", cascade="all, delete-orphan")


class CustomAgentMcpTool(Base):
    """Tool whitelist entry for a custom agent MCP."""

    __tablename__ = "custom_agent_mcp_tools"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    custom_agent_mcp_id = Column(UUID(as_uuid=True), ForeignKey("custom_agent_mcps.id", ondelete="CASCADE"), nullable=False)
    tool_name = Column(String(200), nullable=False)

    # Relationships
    mcp = relationship("CustomAgentMcp", back_populates="tools")


class CustomAgentSkill(Base):
    """Skill association for a custom agent."""

    __tablename__ = "custom_agent_skills"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    custom_agent_id = Column(UUID(as_uuid=True), ForeignKey("custom_agents.id", ondelete="CASCADE"), nullable=False)
    skill_name = Column(String(100), nullable=False)

    # Relationships
    custom_agent = relationship("CustomAgent", back_populates="skills")


class CustomAgentSystemPrompt(Base):
    """System prompt fragment association for a custom agent."""

    __tablename__ = "custom_agent_system_prompts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    custom_agent_id = Column(UUID(as_uuid=True), ForeignKey("custom_agents.id", ondelete="CASCADE"), nullable=False)
    prompt_id = Column(String(100), nullable=False)

    # Relationships
    custom_agent = relationship("CustomAgent", back_populates="system_prompts")


class CustomAgentBuiltinTool(Base):
    """Built-in tool association for a custom agent."""

    __tablename__ = "custom_agent_builtin_tools"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    custom_agent_id = Column(UUID(as_uuid=True), ForeignKey("custom_agents.id", ondelete="CASCADE"), nullable=False)
    tool_name = Column(String(100), nullable=False)

    # Relationships
    custom_agent = relationship("CustomAgent", back_populates="builtin_tools")


class CustomAgentApprovalOverride(Base):
    """Approval override for a specific tool on a custom agent."""

    __tablename__ = "custom_agent_approval_overrides"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    custom_agent_id = Column(UUID(as_uuid=True), ForeignKey("custom_agents.id", ondelete="CASCADE"), nullable=False)
    tool_key = Column(String(200), nullable=False)
    requires_approval = Column(Boolean, default=True)
    required_role = Column(String(100), nullable=True)

    # Relationships
    custom_agent = relationship("CustomAgent", back_populates="approval_overrides")


class CustomAgentFoundryTool(Base):
    """Foundry-native tool enabled for a custom agent (e.g. code_interpreter, file_search, bing_grounding)."""

    __tablename__ = "custom_agent_foundry_tools"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    custom_agent_id = Column(UUID(as_uuid=True), ForeignKey("custom_agents.id", ondelete="CASCADE"), nullable=False)
    tool_type = Column(String(100), nullable=False)  # e.g. "code_interpreter", "file_search", "bing_grounding"

    # Relationships
    custom_agent = relationship("CustomAgent", back_populates="foundry_tools")
