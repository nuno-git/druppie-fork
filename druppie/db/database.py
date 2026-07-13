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

# ── Connection pool sizing ─────────────────────────────────────────
# Production math: (pool_size + max_overflow) * workers per pod * pods
#
# Example with defaults (10 + 15 = 25 per worker):
#   Docker dev  (--workers 1, 1 pod):  25 connections
#   Docker prod (--workers 1, 1 pod):  25 connections
#   K8s         (--workers 2, 3 pods): 150 connections
#
# PostgreSQL defaults to max_connections=100. If you increase workers
# or scale replicas, tune via env vars (see docker-compose.yml):
#   DB_POOL_SIZE, DB_MAX_OVERFLOW, DB_POOL_TIMEOUT
#
# For high-throughput K8s deployments, run PgBouncer in transaction
# mode (see docs/ADR-KUBERNETES.md §4.3).
# ────────────────────────────────────────────────────────────────────
_pool_size = int(os.getenv("DB_POOL_SIZE", "10"))
_max_overflow = int(os.getenv("DB_MAX_OVERFLOW", "15"))
_pool_timeout = int(os.getenv("DB_POOL_TIMEOUT", "30"))

_is_sqlite = "sqlite" in DATABASE_URL
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if _is_sqlite else {},
    pool_pre_ping=True,
    **({} if _is_sqlite else {
        "pool_size": _pool_size,
        "max_overflow": _max_overflow,
        "pool_recycle": 3600,
        "pool_timeout": _pool_timeout,
        "pool_use_lifo": True,
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
