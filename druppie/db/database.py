"""Database connection and session management.

This module provides database setup and session management,
separated from models to avoid circular imports.
"""

import logging
import os
from typing import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

logger = logging.getLogger(__name__)

# Database URL from environment
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./druppie.db")

# Create engine with explicit pool settings to prevent connection exhaustion
# from concurrent background tasks (orchestrator, sandbox resume, watchdog).
# pool_size=20 + max_overflow=30 = 50 max connections. Each session uses
# ~2 connections (orchestrator + webhook/resume), plus watchdog + API handlers.
# PostgreSQL default max_connections=100, so 50 leaves headroom.
_is_sqlite = "sqlite" in DATABASE_URL
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if _is_sqlite else {},
    pool_pre_ping=True,  # Enable connection health checks
    **({} if _is_sqlite else {
        "pool_size": 20,
        "max_overflow": 30,
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
    """Initialize database tables and sync schema.

    Creates tables that don't exist, then adds any columns present
    in the SQLAlchemy models but missing from the live database.
    This prevents the need for a full DB reset when columns are
    added to existing models.
    """
    from druppie.db.models import Base

    Base.metadata.create_all(bind=engine)
    _sync_missing_columns(Base)


def _sync_missing_columns(Base) -> None:
    """Add columns that exist in models but are missing from the DB."""
    insp = inspect(engine)
    existing_tables = insp.get_table_names()

    for table_name, table in Base.metadata.tables.items():
        if table_name not in existing_tables:
            continue

        db_columns = {col["name"] for col in insp.get_columns(table_name)}
        for col in table.columns:
            if col.name in db_columns:
                continue
            col_type = col.type.compile(dialect=engine.dialect)
            sql = f'ALTER TABLE {table_name} ADD COLUMN {col.name} {col_type}'
            logger.info("schema_sync: %s", sql)
            with engine.begin() as conn:
                conn.execute(text(sql))
