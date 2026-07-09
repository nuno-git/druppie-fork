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
- JobDefinition → JobDefinitionSummary, JobDefinitionDetail
- JobRun → JobRunSummary, JobRunDetail
"""

# Enums
# Agent definition (YAML config)
from .agent_definition import AgentDefinition, ApprovalOverride, SandboxConstraints

# Agent run models
from .agent_run import (
    AgentRunDetail,
    AgentRunSummary,
    CompactionEventDetail,
    LLMCallDetail,
    LLMRetryDetail,
    NormalizationDetail,
    ResumeContext,
    ToolCallDetail,
)

# Approval models
from .approval import ApprovalDetail, ApprovalHistoryList, ApprovalSummary, PendingApprovalList

# Evaluation models
from .evaluation import (
    BenchmarkRunDetail,
    BenchmarkRunSummary,
    EvaluationResultDetail,
    EvaluationResultSummary,
    TestAssertionResultSummary,
    TestRunDetail,
    TestRunSummary,
)

# Documentation models
from .documentation import DocumentationEntry

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

# Branch environment models
from .branch_environment import (
    BranchEnvironmentCreate,
    BranchEnvironmentDetail,
    BranchEnvironmentListResponse,
    BranchEnvironmentPipeline,
    BranchEnvironmentStatus,
    BranchEnvironmentSummary,
    PipelineStage,
    PipelineStageStatus,
)

# Question models
from .question import PendingQuestionList, QuestionChoice, QuestionDetail

# Session models
from .session import (
    # Backward compat aliases
    Attachment,
    ChatItem,
    ChatItemType,
    Message,
    MessageSummary,
    SessionDetail,
    SessionSummary,
    TimelineEntry,
    TimelineEntryType,
)

from .job import JobDefinitionDetail, JobDefinitionList, JobDefinitionSummary, JobRunDetail, JobRunList, JobRunSummary

# Model override models
from .model_override import (
    AgentModelInfo,
    ModelManagementView,
    ModelOverrideDetail,
    ModelOverrideSummary,
    ProviderStatus,
    TranslationModelInfo,
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
    "Attachment",
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
    "CompactionEventDetail",
    "LLMCallDetail",
    "LLMRetryDetail",
    "NormalizationDetail",
    "ResumeContext",
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
    # Dev VM
    # Branch environment
    "BranchEnvironmentSummary",
    "BranchEnvironmentDetail",
    "BranchEnvironmentCreate",
    "BranchEnvironmentListResponse",
    "BranchEnvironmentStatus",
    "BranchEnvironmentPipeline",
    "PipelineStage",
    "PipelineStageStatus",
    # User
    "UserInfo",
    # Documentation
    "DocumentationEntry",
    # Agent definition
    "AgentDefinition",
    "ApprovalOverride",
    "SandboxConstraints",
    # Skill
    "SkillSummary",
    "SkillDetail",
    # Tool definition
    "ToolDefinition",
    "ToolDefinitionSummary",
    "ToolType",
    # Evaluation
    "EvaluationResultSummary",
    "EvaluationResultDetail",
    "BenchmarkRunSummary",
    "BenchmarkRunDetail",
    # Test runs
    "TestRunSummary",
    "TestRunDetail",
    "TestAssertionResultSummary",
    "JobDefinitionSummary",
    "JobDefinitionDetail",
    "JobDefinitionList",
    "JobRunSummary",
    "JobRunDetail",
    "JobRunList",
    # Model override
    "ModelOverrideSummary",
    "ModelOverrideDetail",
    "ProviderStatus",
    "AgentModelInfo",
    "TranslationModelInfo",
    "ModelManagementView",
]

# Rebuild models to resolve forward references (circular imports between session/project)
ProjectDetail.model_rebuild()
SessionDetail.model_rebuild()
BenchmarkRunDetail.model_rebuild()
