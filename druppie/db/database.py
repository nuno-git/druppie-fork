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

# pool_size=30 + max_overflow=50 = 80 max connections per worker process.
# Generous to absorb frontend burst loads (page refresh + parallel polling
# while long-running agent tasks hold a connection). Default timeout raised
# to 60s so short-lived burst requests queue instead of crashing.
_is_sqlite = "sqlite" in DATABASE_URL
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if _is_sqlite else {},
    pool_pre_ping=True,
    **({} if _is_sqlite else {
        "pool_size": 30,
        "max_overflow": 50,
        "pool_recycle": 3600,
        "pool_timeout": 60,
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
