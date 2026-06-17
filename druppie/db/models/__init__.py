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
"""

# Agent execution models
from .agent_run import AgentRun, Message

# Compaction event model
from .compaction_event import CompactionEvent

# Approval model
from .approval import Approval
from .base import Base, new_uuid, utcnow

# Benchmark and evaluation models
from .benchmark_run import BenchmarkRun
from .evaluation_result import EvaluationResult

# Test run models (testing framework)
from .test_assertion_result import TestAssertionResult
from .test_batch_run import TestBatchRun
from .test_run import TestRun
from .test_run_tag import TestRunTag
from .test_running_status import TestRunningStatus
from .llm_call import LlmCall
from .llm_retry import LlmRetry

# Project model
from .project import Project
from .project_dependency import ProjectDependency

# Documentation cache
from .documentation_cache import DocumentationCache

# Question model (HITL questions from agents)
from .question import Question

from .job import JobDefinition, JobRun

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
    "ProjectDependency",
    # Documentation cache
    "DocumentationCache",
    # Session
    "Session",
    # Agent execution
    "AgentRun",
    "Message",
    "CompactionEvent",
    "ToolCall",
    "LlmCall",
    "LlmRetry",
    "ToolCallNormalization",
    # Approval
    "Approval",
    # Question
    "Question",
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
]
