"""Dependency injection for FastAPI routes."""

import os
from typing import Generator

from fastapi import Depends, HTTPException, Header
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

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
    """Get database session."""
    db = SessionLocal()
    try:
        yield db
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
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY", "druppie-internal-key")


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
