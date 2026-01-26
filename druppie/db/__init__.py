"""Database module for Druppie platform.

NO JSON columns - everything is properly normalized.
Single source of truth: druppie/db/schema.sql
"""

from .database import get_db, init_db, SessionLocal, engine

from .models import (
    # Base
    Base,
    # Users
    User,
    UserRole,
    UserToken,
    # Projects
    Project,
    # Sessions
    Session,
    # Workflows
    Workflow,
    WorkflowStep,
    # Agent Runs
    AgentRun,
    # Messages
    Message,
    # Tool Calls
    ToolCall,
    ToolCallArgument,
    # Approvals
    Approval,
    # HITL
    HitlQuestion,
    HitlQuestionChoice,
    # Workspaces
    Workspace,
    # Builds & Deployments
    Build,
    Deployment,
    # LLM Tracking
    LlmCall,
)

from .crud import (
    # User CRUD
    get_or_create_user,
    get_user,
    get_user_roles,
    # Session CRUD
    create_session,
    get_session,
    update_session,
    update_session_tokens,
    list_sessions,
    count_sessions,
    # Workflow CRUD
    create_workflow,
    get_workflow,
    get_workflow_for_session,
    update_workflow,
    update_workflow_step,
    # Agent Run CRUD
    create_agent_run,
    get_agent_run,
    get_active_agent_run,
    update_agent_run,
    update_agent_run_tokens,
    # Message CRUD
    create_message,
    get_messages_for_session,
    get_messages_for_agent_run,
    # Tool Call CRUD
    create_tool_call,
    get_tool_call,
    update_tool_call,
    # Approval CRUD
    create_approval,
    get_approval,
    get_pending_approval_for_tool_call,
    resolve_approval,
    list_pending_approvals,
    list_approvals,
    # HITL Question CRUD
    create_hitl_question,
    get_hitl_question,
    get_pending_hitl_question,
    answer_hitl_question,
    list_pending_hitl_questions,
    get_hitl_questions_for_session,
    # Project CRUD
    create_project,
    get_project,
    get_project_by_repo,
    list_projects,
    update_project,
    # Workspace CRUD
    create_workspace,
    get_workspace,
    get_workspace_for_session,
    # Build CRUD
    create_build,
    get_build,
    update_build,
    list_builds,
    # Deployment CRUD
    create_deployment,
    get_deployment,
    update_deployment,
    get_running_deployments,
    # LLM Call CRUD
    create_llm_call,
    get_llm_calls_for_session,
)

__all__ = [
    # Database
    "get_db",
    "init_db",
    "SessionLocal",
    "engine",
    # Base
    "Base",
    # Models
    "User",
    "UserRole",
    "UserToken",
    "Project",
    "Session",
    "Workflow",
    "WorkflowStep",
    "AgentRun",
    "Message",
    "ToolCall",
    "ToolCallArgument",
    "Approval",
    "HitlQuestion",
    "HitlQuestionChoice",
    "Workspace",
    "Build",
    "Deployment",
    "LlmCall",
    # User CRUD
    "get_or_create_user",
    "get_user",
    "get_user_roles",
    # Session CRUD
    "create_session",
    "get_session",
    "update_session",
    "update_session_tokens",
    "list_sessions",
    "count_sessions",
    # Workflow CRUD
    "create_workflow",
    "get_workflow",
    "get_workflow_for_session",
    "update_workflow",
    "update_workflow_step",
    # Agent Run CRUD
    "create_agent_run",
    "get_agent_run",
    "get_active_agent_run",
    "update_agent_run",
    "update_agent_run_tokens",
    # Message CRUD
    "create_message",
    "get_messages_for_session",
    "get_messages_for_agent_run",
    # Tool Call CRUD
    "create_tool_call",
    "get_tool_call",
    "update_tool_call",
    # Approval CRUD
    "create_approval",
    "get_approval",
    "get_pending_approval_for_tool_call",
    "resolve_approval",
    "list_pending_approvals",
    "list_approvals",
    # HITL Question CRUD
    "create_hitl_question",
    "get_hitl_question",
    "get_pending_hitl_question",
    "answer_hitl_question",
    "list_pending_hitl_questions",
    "get_hitl_questions_for_session",
    # Project CRUD
    "create_project",
    "get_project",
    "get_project_by_repo",
    "list_projects",
    "update_project",
    # Workspace CRUD
    "create_workspace",
    "get_workspace",
    "get_workspace_for_session",
    # Build CRUD
    "create_build",
    "get_build",
    "update_build",
    "list_builds",
    # Deployment CRUD
    "create_deployment",
    "get_deployment",
    "update_deployment",
    "get_running_deployments",
    # LLM Call CRUD
    "create_llm_call",
    "get_llm_calls_for_session",
]
