"""Dependency injection for FastAPI routes.

Provides common dependencies for FastAPI route handlers including:
- Database sessions
- Authentication and authorization
- Main execution loop
- Repository and Service layer injection (clean architecture)

The clean architecture uses dependency injection to wire up:
  Route → Service → Repository → Database

Example usage in a route:
    @router.get("/{session_id}")
    async def get_session(
        session_id: UUID,
        service: SessionService = Depends(get_session_service),
        user: dict = Depends(get_current_user),
    ) -> SessionDetail:
        return service.get_detail(session_id, UUID(user["sub"]), get_user_roles(user))
"""

import os
from functools import wraps
from typing import Callable, Generator

from fastapi import Depends, HTTPException, Header
from sqlalchemy.orm import Session
import structlog

logger = structlog.get_logger()

from druppie.core.auth import get_auth_service, AuthService
from druppie.core.loop import get_main_loop, MainLoop
from druppie.db.database import get_db, init_db, SessionLocal, engine
from druppie.db import get_or_create_user
from uuid import UUID

# Import repositories and services for dependency injection
from druppie.repositories import (
    SessionRepository,
    ApprovalRepository,
    QuestionRepository,
    ProjectRepository,
)
from druppie.services import (
    SessionService,
    ApprovalService,
    QuestionService,
    ProjectService,
    WorkflowService,
)

# Initialize database tables on import
init_db()


# =============================================================================
# REPOSITORY DEPENDENCIES
# =============================================================================
# Repositories handle database access. Each repository gets a DB session.


def get_session_repository(db: Session = Depends(get_db)) -> SessionRepository:
    """Get SessionRepository with DB session injected."""
    return SessionRepository(db)


def get_approval_repository(db: Session = Depends(get_db)) -> ApprovalRepository:
    """Get ApprovalRepository with DB session injected."""
    return ApprovalRepository(db)


def get_question_repository(db: Session = Depends(get_db)) -> QuestionRepository:
    """Get QuestionRepository with DB session injected."""
    return QuestionRepository(db)


def get_project_repository(db: Session = Depends(get_db)) -> ProjectRepository:
    """Get ProjectRepository with DB session injected."""
    return ProjectRepository(db)


# =============================================================================
# SERVICE DEPENDENCIES
# =============================================================================
# Services handle business logic. Each service gets its required repositories.


def get_session_service(
    session_repo: SessionRepository = Depends(get_session_repository),
) -> SessionService:
    """Get SessionService with repositories injected."""
    return SessionService(session_repo)


def get_approval_service(
    approval_repo: ApprovalRepository = Depends(get_approval_repository),
) -> ApprovalService:
    """Get ApprovalService with repositories injected."""
    return ApprovalService(approval_repo)


def get_question_service(
    question_repo: QuestionRepository = Depends(get_question_repository),
    session_repo: SessionRepository = Depends(get_session_repository),
) -> QuestionService:
    """Get QuestionService with repositories injected.

    QuestionService needs SessionRepository to check ownership
    (questions belong to sessions, sessions belong to users).
    """
    return QuestionService(question_repo, session_repo)


def get_project_service(
    project_repo: ProjectRepository = Depends(get_project_repository),
    session_repo: SessionRepository = Depends(get_session_repository),
) -> ProjectService:
    """Get ProjectService with repositories injected."""
    return ProjectService(project_repo, session_repo)


def get_loop() -> MainLoop:
    """Get the main execution loop."""
    return get_main_loop()


def get_orchestrator(db: Session = Depends(get_db)):
    """Get the orchestrator for message processing.

    The Orchestrator is the new simplified entry point that replaces MainLoop.
    It coordinates: router → planner → execute pending runs.
    """
    from druppie.core.orchestrator import Orchestrator
    return Orchestrator(db)


def get_workflow_service(
    loop: MainLoop = Depends(get_loop),
) -> WorkflowService:
    """Get WorkflowService with MainLoop injected.

    WorkflowService wraps the MainLoop and provides methods for
    resuming paused workflows (after questions, approvals, etc.).
    """
    return WorkflowService(loop)


def get_auth() -> AuthService:
    """Get the authentication service."""
    return get_auth_service()


async def get_current_user(
    authorization: str | None = Header(None),
    auth: AuthService = Depends(get_auth),
) -> dict:
    """Get current user from JWT token.

    Returns user info dict or raises 401 if not authenticated.
    Also syncs user to database from Keycloak on first login.
    """
    user = auth.validate_request(authorization)
    if not user:
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing authentication token",
        )

    # Sync user to database (creates if doesn't exist)
    try:
        user_id = user.get("sub")
        if user_id:
            db = SessionLocal()
            try:
                get_or_create_user(
                    db,
                    user_id=UUID(user_id),
                    username=user.get("preferred_username"),
                    email=user.get("email"),
                    display_name=user.get("name"),
                )
            finally:
                db.close()
    except Exception as e:
        logger.warning("user_sync_failed", user_id=user.get("sub"), error=str(e))

    return user


async def get_optional_user(
    authorization: str | None = Header(None),
    auth: AuthService = Depends(get_auth),
) -> dict | None:
    """Get current user if authenticated, or None."""
    return auth.validate_request(authorization)


# Internal API key for MCP servers to call backend
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY", "")

# Security warning for missing/default API key
if not INTERNAL_API_KEY:
    logger.warning(
        "internal_api_key_not_configured",
        message="INTERNAL_API_KEY not set - internal API authentication disabled",
    )
    INTERNAL_API_KEY = "disabled"  # Prevent empty string matching


async def verify_internal_api_key(
    x_internal_api_key: str | None = Header(None),
) -> bool:
    """Verify internal API key for MCP server requests.

    MCP servers use this to authenticate when calling backend endpoints.
    """
    if not x_internal_api_key:
        raise HTTPException(
            status_code=401,
            detail="Missing internal API key",
        )
    if x_internal_api_key != INTERNAL_API_KEY:
        raise HTTPException(
            status_code=403,
            detail="Invalid internal API key",
        )
    return True


# =============================================================================
# ROLE-BASED AUTHORIZATION HELPERS
# =============================================================================


def get_user_roles(user: dict) -> list[str]:
    """Extract roles from user token.

    Args:
        user: User dict from token validation

    Returns:
        List of role names
    """
    return user.get("realm_access", {}).get("roles", [])


def user_has_role(user: dict, role: str) -> bool:
    """Check if user has a specific role.

    Args:
        user: User dict from token validation
        role: Role name to check

    Returns:
        True if user has the role
    """
    roles = get_user_roles(user)
    return role in roles or "admin" in roles


def user_has_any_role(user: dict, roles: list[str]) -> bool:
    """Check if user has any of the specified roles.

    Args:
        user: User dict from token validation
        roles: List of role names (any match succeeds)

    Returns:
        True if user has any of the roles
    """
    user_roles = get_user_roles(user)
    if "admin" in user_roles:
        return True
    return any(role in user_roles for role in roles)


def require_role(role: str) -> Callable:
    """Dependency that requires a specific role.

    Usage:
        @router.get("/admin-only")
        async def admin_endpoint(
            user: dict = Depends(get_current_user),
            _: bool = Depends(require_role("admin")),
        ):
            pass

    Args:
        role: Required role name

    Returns:
        Dependency function that validates role
    """
    async def check_role(user: dict = Depends(get_current_user)) -> bool:
        if not user_has_role(user, role):
            raise HTTPException(
                status_code=403,
                detail=f"Requires role: {role}",
            )
        return True
    return check_role


def require_any_role(roles: list[str]) -> Callable:
    """Dependency that requires any of the specified roles.

    Usage:
        @router.post("/deploy")
        async def deploy(
            user: dict = Depends(get_current_user),
            _: bool = Depends(require_any_role(["developer", "admin"])),
        ):
            pass

    Args:
        roles: List of role names (any match succeeds)

    Returns:
        Dependency function that validates role
    """
    async def check_roles(user: dict = Depends(get_current_user)) -> bool:
        if not user_has_any_role(user, roles):
            raise HTTPException(
                status_code=403,
                detail=f"Requires one of roles: {', '.join(roles)}",
            )
        return True
    return check_roles


async def require_admin(user: dict = Depends(get_current_user)) -> dict:
    """Dependency that requires admin role.

    Usage:
        @router.delete("/dangerous")
        async def delete_all(user: dict = Depends(require_admin)):
            pass

    Args:
        user: Current authenticated user

    Returns:
        User dict if admin, raises 403 otherwise
    """
    if not user_has_role(user, "admin"):
        raise HTTPException(
            status_code=403,
            detail="Admin access required",
        )
    return user


def check_resource_ownership(
    user: dict,
    resource_user_id: str | UUID | None,
    allow_admin: bool = True,
) -> bool:
    """Check if user owns a resource or is admin.

    Args:
        user: Current authenticated user
        resource_user_id: User ID of the resource owner (can be UUID or string)
        allow_admin: If True, admins can access any resource

    Returns:
        True if user can access the resource

    Raises:
        HTTPException: If user cannot access the resource
    """
    user_id = user.get("sub")
    roles = get_user_roles(user)

    # Admin bypass if allowed
    if allow_admin and "admin" in roles:
        return True

    # Check ownership - normalize both to strings for comparison
    if resource_user_id:
        # Convert UUID to string if needed for proper comparison
        resource_id_str = str(resource_user_id)
        if resource_id_str != user_id:
            raise HTTPException(
                status_code=403,
                detail="Not authorized to access this resource",
            )

    return True
