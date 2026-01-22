"""Dependency injection for FastAPI routes.

Provides common dependencies for FastAPI route handlers including:
- Database sessions
- Authentication and authorization
- Main execution loop
"""

import os
from functools import wraps
from typing import Callable, Generator

from fastapi import Depends, HTTPException, Header
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
import structlog

logger = structlog.get_logger()

from druppie.core.auth import get_auth_service, AuthService
from druppie.core.loop import get_main_loop, MainLoop
from druppie.db.models import Base
from druppie.db.migrations import run_migrations

# Database setup
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./druppie.db")

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Create tables (only creates if they don't exist)
Base.metadata.create_all(bind=engine)

# Run migrations (adds new columns to existing tables)
run_migrations(engine)


def get_db() -> Generator[Session, None, None]:
    """Get database session with proper cleanup.

    Ensures transactions are rolled back on errors and connections
    are properly closed to prevent connection pool exhaustion.
    """
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_loop() -> MainLoop:
    """Get the main execution loop."""
    return get_main_loop()


def get_auth() -> AuthService:
    """Get the authentication service."""
    return get_auth_service()


async def get_current_user(
    authorization: str | None = Header(None),
    auth: AuthService = Depends(get_auth),
) -> dict:
    """Get current user from JWT token.

    Returns user info dict or raises 401 if not authenticated.
    """
    user = auth.validate_request(authorization)
    if not user:
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing authentication token",
        )
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
    resource_user_id: str | None,
    allow_admin: bool = True,
) -> bool:
    """Check if user owns a resource or is admin.

    Args:
        user: Current authenticated user
        resource_user_id: User ID of the resource owner
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

    # Check ownership
    if resource_user_id and resource_user_id != user_id:
        raise HTTPException(
            status_code=403,
            detail="Not authorized to access this resource",
        )

    return True
