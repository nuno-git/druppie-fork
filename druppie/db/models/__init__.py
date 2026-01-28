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
approvals         Approval            ApprovalSummary, ApprovalDetail
questions         Question            QuestionSummary, QuestionDetail

Removed tables (handled by MCPs):
- workspaces: Coding MCP manages workspace lifecycle
- builds: Docker MCP tracks via container labels
- deployments: Docker MCP tracks via container labels
- session_events: Derived from other tables, not stored
"""

from .base import Base, utcnow, new_uuid

# User models
from .user import User, UserRole, UserToken

# Project model
from .project import Project

# Session model
from .session import Session

# Agent execution models
from .agent_run import AgentRun, Message
from .tool_call import ToolCall
from .llm_call import LlmCall

# Approval model
from .approval import Approval

# Question model (HITL questions from agents)
from .question import Question

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
    # Approval
    "Approval",
    # Question
    "Question",
]
