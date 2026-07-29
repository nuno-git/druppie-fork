"""Database connection and session management.

This module provides database setup and session management,
separated from models to avoid circular imports.
"""

import os
from typing import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

# Database URL from environment
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./druppie.db")

# pool_size=5 + max_overflow=5 = 10 max connections per worker process.
# With 2 workers/pod × 3 pods = 6 processes × 10 = 60 connections.
# PostgreSQL default max_connections=100, so 60 leaves headroom.
_is_sqlite = "sqlite" in DATABASE_URL
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if _is_sqlite else {},
    pool_pre_ping=True,
    **({} if _is_sqlite else {
        "pool_size": 5,
        "max_overflow": 5,
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

    # Migration: fix model_overrides.updated_by FK to allow CASCADE on UPDATE
    # and SET NULL on DELETE. This prevents FK violations during user UUID
    # drift correction (e.g. after Keycloak DB reset).
    # Runs idempotently — safe to call on every startup.
    # Postgres-only: the query reads information_schema (absent on sqlite, used
    # by local/test runs), and sqlite can't ALTER a constraint anyway.
    if _is_sqlite:
        return
    with engine.connect() as conn:
        # Check if the constraint already has the correct rules
        result = conn.execute(
            text("""
            SELECT rc.update_rule, rc.delete_rule
            FROM information_schema.table_constraints tc
            JOIN information_schema.referential_constraints rc
              ON rc.constraint_name = tc.constraint_name
            WHERE tc.table_name = 'model_overrides'
              AND tc.constraint_type = 'FOREIGN KEY';
            """)
        ).fetchone()
        if result and (result.update_rule != 'CASCADE' or result.delete_rule != 'SET NULL'):
            conn.execute(text("ALTER TABLE model_overrides DROP CONSTRAINT model_overrides_updated_by_fkey"))
            conn.execute(
                text("""
                ALTER TABLE model_overrides ADD CONSTRAINT model_overrides_updated_by_fkey
                  FOREIGN KEY (updated_by) REFERENCES users(id)
                  ON UPDATE CASCADE ON DELETE SET NULL;
                """)
            )
            conn.commit()
