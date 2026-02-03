"""Domain models for Druppie API responses.

Domain models provide a clean, typed interface between layers:
- Repositories return domain models
- Services work with domain models
- API routes return domain models

Naming convention:
- Summary: lightweight, for lists
- Detail: full data, for single-item views

1:1 mapping with database tables:
- Session → SessionSummary, SessionDetail
- Message → Message
- AgentRun → AgentRunSummary, AgentRunDetail
- ToolCall → ToolCallDetail
- LlmCall → LLMCallDetail
- Approval → ApprovalSummary, ApprovalDetail
- Question → QuestionDetail
- Project → ProjectSummary, ProjectDetail
- User → UserInfo
"""

# Enums
from .common import (
    SessionStatus,
    AgentRunStatus,
    ToolCallStatus,
    ApprovalStatus,
    QuestionStatus,
    DeploymentStatus,
)

# Common models
from .common import TokenUsage, TimestampMixin, LLMMessage

# Session models
from .session import (
    SessionSummary,
    SessionDetail,
    Message,
    TimelineEntry,
    TimelineEntryType,
    # Backward compat aliases
    ChatItem,
    ChatItemType,
    MessageSummary,
)

# Agent run models
from .agent_run import AgentRunSummary, AgentRunDetail, LLMCallDetail, LLMRawResponse, ToolCallDetail

# Approval models
from .approval import ApprovalSummary, ApprovalDetail, PendingApprovalList, ApprovalHistoryList

# Question models
from .question import QuestionDetail, QuestionChoice, PendingQuestionList

# Project models
from .project import ProjectSummary, ProjectDetail, DeploymentInfo, DeploymentSummary

# User models
from .user import UserInfo

# Agent definition (YAML config)
from .agent_definition import AgentDefinition, ApprovalOverride


__all__ = [
    # Enums
    "SessionStatus",
    "AgentRunStatus",
    "ToolCallStatus",
    "ApprovalStatus",
    "QuestionStatus",
    "DeploymentStatus",
    # Common
    "TokenUsage",
    "TimestampMixin",
    "LLMMessage",
    # Session
    "SessionSummary",
    "SessionDetail",
    "Message",
    "TimelineEntry",
    "TimelineEntryType",
    # Backward compat
    "ChatItem",
    "ChatItemType",
    "MessageSummary",
    # Agent run
    "AgentRunSummary",
    "AgentRunDetail",
    "LLMCallDetail",
    "LLMRawResponse",
    "ToolCallDetail",
    # Approval
    "ApprovalSummary",
    "ApprovalDetail",
    "PendingApprovalList",
    "ApprovalHistoryList",
    # Question
    "QuestionDetail",
    "QuestionChoice",
    "PendingQuestionList",
    # Project
    "ProjectSummary",
    "ProjectDetail",
    "DeploymentInfo",
    "DeploymentSummary",
    # User
    "UserInfo",
    # Agent definition
    "AgentDefinition",
    "ApprovalOverride",
]

# Rebuild models to resolve forward references (circular imports between session/project)
ProjectDetail.model_rebuild()
SessionDetail.model_rebuild()
