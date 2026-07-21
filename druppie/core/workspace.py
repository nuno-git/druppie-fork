"""Canonical workspace path resolution.

Provides a single source of truth for computing workspace paths
so MCP servers and builtin tools never disagree on where files live.
"""

import os
from pathlib import Path

WORKSPACE_ROOT = Path(os.getenv("WORKSPACE_ROOT", "/app/workspace"))


def workspace_path_for(
    user_id: str,
    project_id: str,
    session_id: str,
) -> Path:
    """Return the canonical workspace path for a user/project/session.

    All MCP servers and builtin tools MUST use this function
    so files end up in a single deterministic location.

    Path format: WORKSPACE_ROOT / <user_id> / <project_id> / <session_id>

    Args:
        user_id: The user identifier.
        project_id: The project identifier.
        session_id: The session identifier.

    Returns:
        Absolute Path to the workspace directory.
    """
    return WORKSPACE_ROOT / user_id / project_id / session_id


def workspace_path_for_session(session) -> Path:
    """Return the canonical workspace path for a session.

    Delegates to :func:`workspace_path_for` using session attributes.
    Falls back to "default" when session.user_id is missing so the
    platform never attempts to write to a None directory.

    Args:
        session: A Session model instance (needs user_id, project_id, id).

    Returns:
        Absolute Path to the session's workspace directory.
    """
    user_part = str(session.user_id) if session.user_id else "default"
    return workspace_path_for(
        user_id=user_part,
        project_id=str(session.project_id),
        session_id=str(session.id),
    )


def workspace_path_for_session_or_none(session) -> Path | None:
    """Return workspace path only if session has a project_id.

    Args:
        session: A Session model instance.

    Returns:
        Path if session.project_id exists, None otherwise.
    """
    if not session or not getattr(session, "project_id", None):
        return None
    return workspace_path_for_session(session)
