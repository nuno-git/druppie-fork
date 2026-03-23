"""Database connection and session management.

This module provides database setup and session management,
separated from models to avoid circular imports.
"""

import os
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

# Database URL from environment
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./druppie.db")

# Create engine with explicit pool settings to prevent connection exhaustion
# from concurrent background tasks (orchestrator, sandbox resume, watchdog).
# pool_size=10 + max_overflow=20 = 30 max connections. Sufficient for ~25
# concurrent sessions; increase if running more in parallel.
_is_sqlite = "sqlite" in DATABASE_URL
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if _is_sqlite else {},
    pool_pre_ping=True,  # Enable connection health checks
    **({} if _is_sqlite else {
        "pool_size": 10,
        "max_overflow": 20,
    }),
)

# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


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


def init_db() -> None:
    """Initialize database tables.

    Creates all tables defined in models if they don't exist.
    """
    from druppie.db.models import Base
    Base.metadata.create_all(bind=engine)
