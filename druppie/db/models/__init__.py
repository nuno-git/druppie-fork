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
message_attachments MessageAttachment Attachment
llm_retries       LlmRetry            LLMRetryDetail
tool_call_normalizations ToolCallNormalization NormalizationDetail
approvals         Approval            ApprovalSummary, ApprovalDetail
questions         Question            QuestionSummary, QuestionDetail
benchmark_runs    BenchmarkRun        —
evaluation_results EvaluationResult   —
test_runs         TestRun             —
test_run_tags     TestRunTag          —

Removed tables (handled by MCPs):
- workspaces: Coding MCP manages workspace lifecycle
- builds: Docker MCP tracks via container labels
- deployments: Docker MCP tracks via container labels
- session_events: Derived from other tables, not stored

New tables (cron job pipeline):
- job_definitions  JobDefinition       JobDefinitionSummary, JobDefinitionDetail
- job_runs         JobRun              JobRunSummary, JobRunDetail

Runtime configuration:
- model_overrides  ModelOverride       ModelOverrideSummary, ModelOverrideDetail
"""

# Agent execution models
from .agent_run import AgentRun, Message

# Approval model
from .approval import Approval
from .base import Base, new_uuid, utcnow

# Benchmark and evaluation models
from .benchmark_run import BenchmarkRun

# Compaction event model
from .compaction_event import CompactionEvent

# Documentation cache
from .documentation_cache import DocumentationCache

# Escalation event model (audit history for escalation state-machine)
from .escalation_event import EscalationEvent
from .evaluation_result import EvaluationResult
from .job import JobDefinition, JobRun
from .llm_call import LlmCall
from .llm_retry import LlmRetry
from .message_attachment import MessageAttachment

# Model override (runtime LLM configuration)
from .model_override import ModelOverride
from .pdf_render import PdfRender

# Project model
from .project import Project
from .project_dependency import ProjectDependency

# Question model (HITL questions from agents)
from .question import Question
from .resume_context_event import ResumeContextEvent

# Sandbox session model
from .sandbox_session import SandboxSession

# Session model
from .session import Session

# Test run models (testing framework)
from .test_assertion_result import TestAssertionResult
from .test_batch_run import TestBatchRun
from .test_run import TestRun
from .test_run_tag import TestRunTag
from .test_running_status import TestRunningStatus
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
    "ProjectDependency",
    # Documentation cache
    "DocumentationCache",
    # Session
    "Session",
    # Agent execution
    "AgentRun",
    "Message",
    "CompactionEvent",
    "ResumeContextEvent",
    "ToolCall",
    "LlmCall",
    "LlmRetry",
    "ToolCallNormalization",
    # Message attachments
    "MessageAttachment",
    # PDF render cache
    "PdfRender",
    # Approval
    "Approval",
    # Question
    "Question",
    # Escalation event
    "EscalationEvent",
    # Benchmark and evaluation
    "BenchmarkRun",
    "EvaluationResult",
    # Test runs (testing framework)
    "TestBatchRun",
    "TestRun",
    "TestRunTag",
    "TestAssertionResult",
    "TestRunningStatus",
    # Cron jobs
    "JobDefinition",
    "JobRun",
    # Model override
    "ModelOverride",
    "SandboxSession",
]
