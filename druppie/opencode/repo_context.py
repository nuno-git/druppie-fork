"""Resolve repo context for sandbox sessions.

Single source of truth for determining repo_owner, repo_name, git_provider,
and context repo fields based on repo_target. Used by both initial sandbox
creation (builtin_tools.py) and retry (sandbox.py routes).
"""

import os
from dataclasses import dataclass
from uuid import UUID


@dataclass
class RepoContext:
    repo_owner: str
    repo_name: str
    git_provider: str  # "gitea" or "github"
    context_repo_owner: str | None = None
    context_repo_name: str | None = None
    context_git_provider: str | None = None


def resolve_repo_context(
    repo_target: str,
    session_id: UUID | None,
    db,
) -> RepoContext:
    """Resolve git repo context from repo_target and session.

    For repo_target="project": resolves the session's Gitea project repo.
    For repo_target="druppie_core": resolves the Druppie GitHub repo,
    with the session's project repo as read-only context.

    Args:
        repo_target: "project" or "druppie_core".
        session_id: Parent session UUID (used to look up project).
        db: SQLAlchemy session.

    Returns:
        RepoContext with all fields populated.

    Raises:
        ValueError: If druppie_core is requested but env vars are missing.
    """
    from druppie.repositories import SessionRepository, ProjectRepository

    # Helper: look up the session's project
    def _get_project():
        if not session_id:
            return None
        session = SessionRepository(db).get_by_id(session_id)
        if session and session.project_id:
            return ProjectRepository(db).get_by_id(session.project_id)
        return None

    if repo_target == "druppie_core":
        druppie_owner = os.getenv("DRUPPIE_REPO_OWNER")
        druppie_name = os.getenv("DRUPPIE_REPO_NAME")
        if not druppie_owner or not druppie_name:
            raise ValueError(
                "DRUPPIE_REPO_OWNER and DRUPPIE_REPO_NAME must be configured "
                "for repo_target='druppie_core'"
            )

        ctx = RepoContext(
            repo_owner=druppie_owner,
            repo_name=druppie_name,
            git_provider="github",
            context_git_provider="gitea",
            context_repo_owner=os.getenv("GITEA_ORG", "druppie"),
        )

        project = _get_project()
        if project:
            ctx.context_repo_owner = project.repo_owner or ctx.context_repo_owner
            ctx.context_repo_name = project.repo_name or None

        return ctx

    # Default: project repo on Gitea
    ctx = RepoContext(
        repo_owner=os.getenv("GITEA_ORG", "druppie"),
        repo_name="",
        git_provider="gitea",
    )

    project = _get_project()
    if project:
        ctx.repo_owner = project.repo_owner or ctx.repo_owner
        ctx.repo_name = project.repo_name or ""

    return ctx
