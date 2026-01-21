"""Database module for Druppie platform."""

from .models import Base, Session, Approval, Project, Build, Workspace, HitlQuestion
from .crud import (
    # Session CRUD
    create_session,
    get_session,
    update_session,
    delete_session,
    get_session_state,
    save_session_state,
    delete_session_state,
    list_sessions,
    upsert_session,
    # Approval CRUD
    create_approval,
    get_approval,
    update_approval,
    list_pending_approvals,
    list_approvals_for_session,
    list_approvals,
    list_approvals_for_roles,
    # Project CRUD
    create_project,
    get_project,
    get_project_by_repo,
    list_projects,
    update_project,
    delete_project,
    # Build CRUD
    create_build,
    get_build,
    list_builds,
    update_build,
    get_running_build,
    # Workspace CRUD
    create_workspace,
    get_workspace,
    get_workspace_by_session,
    list_workspaces,
    update_workspace,
    delete_workspace,
    # HITL Question CRUD
    create_hitl_question,
    get_hitl_question,
    get_hitl_questions_for_session,
    list_pending_hitl_questions,
    answer_hitl_question,
    expire_hitl_question,
    list_hitl_questions,
)

__all__ = [
    # Models
    "Base",
    "Session",
    "Approval",
    "Project",
    "Build",
    "Workspace",
    "HitlQuestion",
    # Session CRUD
    "create_session",
    "get_session",
    "update_session",
    "delete_session",
    "get_session_state",
    "save_session_state",
    "delete_session_state",
    "list_sessions",
    "upsert_session",
    # Approval CRUD
    "create_approval",
    "get_approval",
    "update_approval",
    "list_pending_approvals",
    "list_approvals_for_session",
    "list_approvals",
    "list_approvals_for_roles",
    # Project CRUD
    "create_project",
    "get_project",
    "get_project_by_repo",
    "list_projects",
    "update_project",
    "delete_project",
    # Build CRUD
    "create_build",
    "get_build",
    "list_builds",
    "update_build",
    "get_running_build",
    # Workspace CRUD
    "create_workspace",
    "get_workspace",
    "get_workspace_by_session",
    "list_workspaces",
    "update_workspace",
    "delete_workspace",
    # HITL Question CRUD
    "create_hitl_question",
    "get_hitl_question",
    "get_hitl_questions_for_session",
    "list_pending_hitl_questions",
    "answer_hitl_question",
    "expire_hitl_question",
    "list_hitl_questions",
]
