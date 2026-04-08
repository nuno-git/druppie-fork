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
# Agent definition (YAML config)
from .agent_definition import AgentDefinition, ApprovalOverride

# Agent run models
from .agent_run import (
    AgentRunDetail,
    AgentRunSummary,
    LLMCallDetail,
    LLMRetryDetail,
    NormalizationDetail,
    ToolCallDetail,
)

# Approval models
from .approval import ApprovalDetail, ApprovalHistoryList, ApprovalSummary, PendingApprovalList

# Custom agent models
from .custom_agent import (
    CustomAgentCreate,
    CustomAgentDetail,
    CustomAgentSummary,
    CustomAgentUpdate,
)

# Common models
from .common import (
    AgentRunStatus,
    ApprovalStatus,
    DeploymentStatus,
    LLMMessage,
    QuestionStatus,
    SessionStatus,
    TimestampMixin,
    TokenUsage,
    ToolCallStatus,
)

# Project models
from .project import DeploymentInfo, DeploymentSummary, ProjectDetail, ProjectSummary

# Question models
from .question import PendingQuestionList, QuestionChoice, QuestionDetail

# Session models
from .session import (
    # Backward compat aliases
    ChatItem,
    ChatItemType,
    Message,
    MessageSummary,
    SessionDetail,
    SessionSummary,
    TimelineEntry,
    TimelineEntryType,
)

# Skill models
from .skill import SkillDetail, SkillSummary

# Tool definition (unified tool metadata with JSON schema validation)
from .tool import ToolDefinition, ToolDefinitionSummary, ToolType

# User models
from .user import UserInfo

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
    "LLMRetryDetail",
    "NormalizationDetail",
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
    # Custom agent
    "CustomAgentSummary",
    "CustomAgentDetail",
    "CustomAgentCreate",
    "CustomAgentUpdate",
    # Skill
    "SkillSummary",
    "SkillDetail",
    # Tool definition
    "ToolDefinition",
    "ToolDefinitionSummary",
    "ToolType",
]

# Rebuild models to resolve forward references (circular imports between session/project)
ProjectDetail.model_rebuild()
SessionDetail.model_rebuild()
