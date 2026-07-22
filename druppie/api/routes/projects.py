"""Projects API routes.

Simple project management - list, view detail, delete.

Architecture:
    Route (this file)
      │
      └──▶ ProjectService ──▶ ProjectRepository ──▶ Database

For deployment management (stop/restart/logs), see deployments.py.
"""

from uuid import UUID

from fastapi import APIRouter, Body, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
import structlog

from druppie.api.deps import get_current_user, get_project_service, get_user_roles
from druppie.api.errors import NotFoundError, ValidationError
from druppie.core.config import get_settings
from druppie.core.gitea import GiteaClient
from druppie.db.database import get_db
from druppie.db.models import Session as SessionModel
from druppie.services import ProjectService
from druppie.domain import DocumentHouseStyle, ProjectSummary, ProjectDetail

logger = structlog.get_logger()

router = APIRouter()


# =============================================================================
# RESPONSE MODELS (list wrapper only - items use domain models)
# =============================================================================


class ProjectListResponse(BaseModel):
    """Paginated project list response."""

    items: list[ProjectSummary]
    total: int
    page: int
    limit: int


class ProjectFileResponse(BaseModel):
    """File content from a project's Gitea repository."""

    path: str
    branch: str
    content: str | None
    size: int
    sha: str | None = None


class ProjectFileChangesResponse(BaseModel):
    """Identifier-level changes in the last commit that touched a file.

    Used by the ArchiMate TD viewer to highlight elements that were
    added or modified in the most recent revision, so reviewers can
    spot their feedback in the next iteration.
    """

    path: str
    branch: str
    last_commit_sha: str | None = None
    last_commit_message: str | None = None
    previous_commit_sha: str | None = None
    added_identifiers: list[str]
    removed_identifiers: list[str]


# =============================================================================
# ROUTES
# =============================================================================


@router.get("/projects", response_model=ProjectListResponse)
async def list_projects(
    page: int = 1,
    limit: int = 20,
    service: ProjectService = Depends(get_project_service),
    user: dict = Depends(get_current_user),
) -> ProjectListResponse:
    """List projects for the current user.

    Admin users see all projects, others see only their own.

    Args:
        page: Page number (1-indexed)
        limit: Items per page

    Returns:
        Paginated list of projects with token usage stats
    """
    user_id = UUID(user["sub"])
    user_roles = get_user_roles(user)

    # Admin sees all projects, others see their own
    if "admin" in user_roles:
        # For admin, pass None to get all
        items, total = service.list_all(page=page, limit=limit)
    else:
        items, total = service.list_for_user(user_id, page=page, limit=limit)

    return ProjectListResponse(
        items=items,
        total=total,
        page=page,
        limit=limit,
    )


@router.get("/projects/{project_id}", response_model=ProjectDetail)
async def get_project(
    project_id: UUID,
    service: ProjectService = Depends(get_project_service),
    user: dict = Depends(get_current_user),
) -> ProjectDetail:
    """Get project detail.

    Includes token usage and current deployment status.

    Args:
        project_id: Project UUID

    Returns:
        Full project detail with deployment info

    Raises:
        NotFoundError: Project doesn't exist
        AuthorizationError: User doesn't own the project
    """
    user_id = UUID(user["sub"])
    user_roles = get_user_roles(user)

    return service.get_detail(project_id, user_id, user_roles)


class SetHouseStyleRequest(BaseModel):
    """Body for changing a project's document house style."""
    house_style: DocumentHouseStyle


@router.put("/projects/{project_id}/house-style", response_model=ProjectDetail)
async def set_project_house_style(
    project_id: UUID,
    body: SetHouseStyleRequest,
    service: ProjectService = Depends(get_project_service),
    user: dict = Depends(get_current_user),
) -> ProjectDetail:
    """Set the corporate identity used to render this project's documents.

    The documenter agent receives this value as context and imports the
    matching Typst template when exporting a PDF.
    """
    user_id = UUID(user["sub"])
    user_roles = get_user_roles(user)

    return service.set_house_style(project_id, body.house_style, user_id, user_roles)


class DeleteProjectsRequest(BaseModel):
    """Body for project deletion."""
    project_ids: list[UUID] | None = None


@router.delete("/projects")
async def delete_projects(
    body: DeleteProjectsRequest | None = Body(None),
    service: ProjectService = Depends(get_project_service),
    user: dict = Depends(get_current_user),
):
    """Delete projects.

    Unified endpoint for single and batch deletion:
    - If project_ids is provided, deletes those specific projects.
    - If project_ids is omitted/null, deletes all projects for the user (admins: all).

    Returns:
        Success confirmation with count of deleted projects
    """
    user_id = UUID(user["sub"])
    user_roles = get_user_roles(user)

    count = await service.delete_many(
        project_ids=body.project_ids if body else None,
        user_id=user_id,
        user_roles=user_roles,
    )

    logger.info("projects_deleted", user_id=str(user["sub"]), count=count)
    return {"success": True, "deleted_count": count}


@router.get("/projects/{project_id}/file", response_model=ProjectFileResponse)
async def get_project_file(
    project_id: UUID,
    path: str = Query(..., description="Repository-relative file path"),
    branch: str = Query("main", description="Branch to read from"),
    service: ProjectService = Depends(get_project_service),
    user: dict = Depends(get_current_user),
) -> ProjectFileResponse:
    """Read a file's content from the project's Gitea repository.

    Used by the TD viewer to fetch supporting artifacts referenced from
    markdown (e.g. docs/architecture.archimate for ArchiMate code blocks).
    """
    user_id = UUID(user["sub"])
    user_roles = get_user_roles(user)
    project = service.get_detail(project_id, user_id, user_roles)
    if not project.repo_name:
        raise ValidationError("Project has no associated Gitea repository", field="project_id")

    client = GiteaClient()
    try:
        result = await client.get_file(project.repo_name, path, branch=branch or "main")
    finally:
        await client.close()

    if not result.get("success"):
        error = result.get("error") or "Gitea fetch failed"
        if "not found" in str(error).lower() or result.get("status") == 404:
            raise NotFoundError("file", path)
        raise ValidationError(f"Failed to read file: {error}", field="path")

    return ProjectFileResponse(
        path=path,
        branch=branch or "main",
        content=result.get("content"),
        size=result.get("size", 0) or 0,
        sha=result.get("sha"),
    )


@router.get("/projects/{project_id}/file/workspace", response_model=ProjectFileResponse)
async def get_project_file_from_workspace(
    project_id: UUID,
    session_id: UUID = Query(..., description="Session whose workspace holds the file"),
    path: str = Query(..., description="Workspace-relative file path"),
    db: Session = Depends(get_db),
    service: ProjectService = Depends(get_project_service),
    user: dict = Depends(get_current_user),
) -> ProjectFileResponse:
    """Read a file from a session's workspace (not Gitea).

    Used by the TD viewer during approval-preview: the .archimate file
    referenced from an embedded code block only exists in the session
    workspace until the TD itself is approved and the architect commits
    + pushes both files. Reading from the workspace lets reviewers see
    the rendered plate before the commit lands in Gitea.
    """
    user_id = UUID(user["sub"])
    user_roles = get_user_roles(user)
    # Authorisation: must be able to see the project.
    service.get_detail(project_id, user_id, user_roles)

    # Confirm the session belongs to this project.
    session = (
        db.query(SessionModel)
        .filter(SessionModel.id == session_id, SessionModel.project_id == project_id)
        .first()
    )
    if session is None:
        raise NotFoundError("session", str(session_id))

    workspace_root = get_settings().workspace.root
    # Coding MCP layout: <root>/<user>/<project>/<session>/<file>
    matches = list(workspace_root.glob(f"*/*/{session_id}"))
    if not matches:
        raise NotFoundError("workspace", str(session_id))
    workspace_dir = matches[0].resolve()

    # Path-traversal guard.
    candidate = (workspace_dir / path).resolve()
    try:
        candidate.relative_to(workspace_dir)
    except ValueError:
        raise ValidationError("Path escapes the workspace", field="path")
    if not candidate.is_file():
        raise NotFoundError("file", path)

    content = candidate.read_text(encoding="utf-8")
    return ProjectFileResponse(
        path=path,
        branch=f"workspace:{session_id}",
        content=content,
        size=candidate.stat().st_size,
        sha=None,
    )


@router.get("/projects/{project_id}/file/changes", response_model=ProjectFileChangesResponse)
async def get_project_file_changes(
    project_id: UUID,
    path: str = Query(..., description="Repository-relative file path"),
    branch: str = Query("main", description="Branch to read from"),
    service: ProjectService = Depends(get_project_service),
    user: dict = Depends(get_current_user),
) -> ProjectFileChangesResponse:
    """Return identifiers added or removed in the most recent commit on ``path``.

    Fetches the last two commits that touched the file, diffs the
    ``identifier="..."`` attributes between them, and returns the
    differences. Used to highlight elements that landed in the latest
    revision so a reviewer can recognise their own feedback.
    """
    import re

    user_id = UUID(user["sub"])
    user_roles = get_user_roles(user)
    project = service.get_detail(project_id, user_id, user_roles)
    if not project.repo_name:
        raise ValidationError("Project has no associated Gitea repository", field="project_id")

    client = GiteaClient()
    try:
        commits_result = await client.list_commits_for_path(
            project.repo_name, path, branch=branch or "main", limit=2,
        )
        commits = commits_result.get("commits") if commits_result.get("success") else []
        if not commits:
            return ProjectFileChangesResponse(
                path=path, branch=branch or "main",
                added_identifiers=[], removed_identifiers=[],
            )

        # Read at the latest commit
        latest = commits[0]
        current = await client.get_file(project.repo_name, path, branch=latest["sha"])
        if not current.get("success") or not current.get("content"):
            return ProjectFileChangesResponse(
                path=path, branch=branch or "main",
                last_commit_sha=latest["sha"],
                last_commit_message=latest["message"],
                added_identifiers=[], removed_identifiers=[],
            )

        # Read at the previous commit (if any)
        previous_content: str | None = None
        previous_sha: str | None = None
        if len(commits) > 1:
            previous_sha = commits[1]["sha"]
            previous = await client.get_file(project.repo_name, path, branch=previous_sha)
            if previous.get("success"):
                previous_content = previous.get("content")
    finally:
        await client.close()

    id_pattern = re.compile(r'identifier="([^"]+)"')
    current_ids = set(id_pattern.findall(current["content"] or ""))
    previous_ids = set(id_pattern.findall(previous_content or ""))

    return ProjectFileChangesResponse(
        path=path,
        branch=branch or "main",
        last_commit_sha=latest["sha"],
        last_commit_message=latest["message"],
        previous_commit_sha=previous_sha,
        added_identifiers=sorted(current_ids - previous_ids),
        removed_identifiers=sorted(previous_ids - current_ids),
    )


@router.get("/projects/{project_id}/dependencies")
async def get_project_dependencies(
    project_id: UUID,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """List all dependencies discovered for a project."""
    from druppie.repositories import ProjectDependencyRepository

    dep_repo = ProjectDependencyRepository(db)
    deps = dep_repo.list_for_project(project_id)
    return [
        {
            "manager": d.manager,
            "name": d.name,
            "version": d.version,
            "first_seen_at": d.first_seen_at.isoformat() if d.first_seen_at else None,
            "last_seen_at": d.last_seen_at.isoformat() if d.last_seen_at else None,
        }
        for d in deps
    ]
