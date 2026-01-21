"""Dependency injection for FastAPI routes."""

import os
from typing import Generator

from fastapi import Depends, HTTPException, Header
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from druppie.core.auth import get_auth_service, AuthService
from druppie.core.loop import get_main_loop, MainLoop
from druppie.db.models import Base

# Database setup
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./druppie.db")

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Create tables
Base.metadata.create_all(bind=engine)


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
