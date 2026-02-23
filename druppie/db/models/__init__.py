"""SQLAlchemy database models for Druppie platform.

Simplified schema with 1:1 mapping to domain models:

Database Table    SQLAlchemy Model    Domain Model(s)
─────────────────────────────────────────────────────
users             User                UserInfo
projects          Project             ProjectSummary, ProjectDetail
sessions          Session             SessionSummary, SessionDetail
messages          Message             Message
agent_runs        AgentRun            AgentRunSummary, AgentRunDetail
llm_calls         LlmCall             LlmCallSummary
tool_calls        ToolCall            ToolCallSummary, ToolCallDetail
llm_retries       LlmRetry            LLMRetryDetail
tool_call_normalizations ToolCallNormalization NormalizationDetail
approvals         Approval            ApprovalSummary, ApprovalDetail
questions         Question            QuestionSummary, QuestionDetail

Removed tables (handled by MCPs):
- workspaces: Coding MCP manages workspace lifecycle
- builds: Docker MCP tracks via container labels
- deployments: Docker MCP tracks via container labels
- session_events: Derived from other tables, not stored
"""

# Agent execution models
from .agent_run import AgentRun, Message

# Approval model
from .approval import Approval
from .base import Base, new_uuid, utcnow
from .llm_call import LlmCall
from .llm_retry import LlmRetry

# Project model
from .project import Project

# Question model (HITL questions from agents)
from .question import Question

# Sandbox session ownership mapping
from .sandbox_session import SandboxSession

# Session model
from .session import Session
from .tool_call import ToolCall
from .tool_call_normalization import ToolCallNormalization

# User models
from .user import User, UserRole, UserToken

__all__ = [
    # Base
    "Base",
    "utcnow",
    "new_uuid",
    # User
    "User",
    "UserRole",
    "UserToken",
    # Project
    "Project",
    # Session
    "Session",
    # Agent execution
    "AgentRun",
    "Message",
    "ToolCall",
    "LlmCall",
    "LlmRetry",
    "ToolCallNormalization",
    # Approval
    "Approval",
    # Question
    "Question",
    # Sandbox session ownership
    "SandboxSession",
]
