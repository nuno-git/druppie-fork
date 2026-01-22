"""Database migrations for Druppie platform.

Simple migration system that tracks applied migrations and runs them on startup.
Each migration is a function that takes a SQLAlchemy connection and applies changes.
"""

import structlog
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError, ProgrammingError

logger = structlog.get_logger()


def ensure_migrations_table(engine: Engine) -> None:
    """Create the migrations tracking table if it doesn't exist."""
    # First check if table exists
    table_exists = False
    with engine.connect() as conn:
        try:
            conn.execute(text("SELECT 1 FROM _migrations LIMIT 1"))
            table_exists = True
        except (OperationalError, ProgrammingError):
            # Table doesn't exist
            conn.rollback()  # Clear any failed transaction state

    if not table_exists:
        # Create the table in a new connection
        with engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS _migrations (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR(255) NOT NULL UNIQUE,
                    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))
            conn.commit()
            logger.info("migrations_table_created")


def migration_applied(engine: Engine, name: str) -> bool:
    """Check if a migration has already been applied."""
    with engine.connect() as conn:
        result = conn.execute(
            text("SELECT 1 FROM _migrations WHERE name = :name"),
            {"name": name}
        )
        return result.fetchone() is not None


def mark_migration_applied(engine: Engine, name: str) -> None:
    """Mark a migration as applied."""
    with engine.connect() as conn:
        conn.execute(
            text("INSERT INTO _migrations (name) VALUES (:name)"),
            {"name": name}
        )
        conn.commit()


def column_exists(engine: Engine, table: str, column: str) -> bool:
    """Check if a column exists in a table."""
    with engine.connect() as conn:
        # Try SQLite method first
        try:
            result = conn.execute(text(f"PRAGMA table_info({table})"))
            columns = [row[1] for row in result.fetchall()]
            return column in columns
        except Exception:
            pass

        # Try PostgreSQL method
        try:
            result = conn.execute(text("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = :table AND column_name = :column
            """), {"table": table, "column": column})
            return result.fetchone() is not None
        except Exception:
            pass

    return False


# =============================================================================
# MIGRATIONS
# =============================================================================

def migrate_001_add_agent_id_to_approvals(engine: Engine) -> None:
    """Add agent_id column to approvals table.

    This column tracks which agent requested the approval.
    """
    migration_name = "001_add_agent_id_to_approvals"

    if migration_applied(engine, migration_name):
        return

    # Check if column already exists (in case table was recreated)
    if column_exists(engine, "approvals", "agent_id"):
        mark_migration_applied(engine, migration_name)
        logger.info("migration_skipped_column_exists", migration=migration_name)
        return

    with engine.connect() as conn:
        try:
            conn.execute(text("""
                ALTER TABLE approvals
                ADD COLUMN agent_id VARCHAR(255)
            """))
            conn.commit()
        except (OperationalError, ProgrammingError) as e:
            if "already exists" in str(e):
                conn.rollback()
                logger.info("migration_column_already_exists", migration=migration_name)
            else:
                raise

    mark_migration_applied(engine, migration_name)
    logger.info("migration_applied", migration=migration_name)


def migrate_002_add_agent_state_to_approvals(engine: Engine) -> None:
    """Add agent_state column to approvals table.

    This column stores the full LangGraph state for resuming after approval.
    """
    migration_name = "002_add_agent_state_to_approvals"

    if migration_applied(engine, migration_name):
        return

    # Check if column already exists
    if column_exists(engine, "approvals", "agent_state"):
        mark_migration_applied(engine, migration_name)
        logger.info("migration_skipped_column_exists", migration=migration_name)
        return

    with engine.connect() as conn:
        try:
            # JSON type for SQLite is just TEXT, PostgreSQL has native JSON
            conn.execute(text("""
                ALTER TABLE approvals
                ADD COLUMN agent_state TEXT
            """))
            conn.commit()
        except (OperationalError, ProgrammingError) as e:
            if "already exists" in str(e):
                conn.rollback()
                logger.info("migration_column_already_exists", migration=migration_name)
            else:
                raise

    mark_migration_applied(engine, migration_name)
    logger.info("migration_applied", migration=migration_name)


def migrate_003_add_project_workspace_to_sessions(engine: Engine) -> None:
    """Add project_id and workspace_id columns to sessions table.

    These columns enable sessions to be linked to specific projects and workspaces,
    allowing for better organization and filtering of sessions.
    """
    migration_name = "003_add_project_workspace_to_sessions"

    if migration_applied(engine, migration_name):
        return

    with engine.connect() as conn:
        # Add project_id column if it doesn't exist
        if not column_exists(engine, "sessions", "project_id"):
            try:
                conn.execute(text("""
                    ALTER TABLE sessions
                    ADD COLUMN project_id VARCHAR(36)
                """))
                conn.commit()
                logger.info("migration_column_added", migration=migration_name, column="project_id")
            except (OperationalError, ProgrammingError) as e:
                if "already exists" in str(e):
                    conn.rollback()
                    logger.info("migration_column_already_exists", migration=migration_name, column="project_id")
                else:
                    raise

        # Add workspace_id column if it doesn't exist
        if not column_exists(engine, "sessions", "workspace_id"):
            try:
                conn.execute(text("""
                    ALTER TABLE sessions
                    ADD COLUMN workspace_id VARCHAR(36)
                """))
                conn.commit()
                logger.info("migration_column_added", migration=migration_name, column="workspace_id")
            except (OperationalError, ProgrammingError) as e:
                if "already exists" in str(e):
                    conn.rollback()
                    logger.info("migration_column_already_exists", migration=migration_name, column="workspace_id")
                else:
                    raise

        # Create indexes for the new columns (SQLite compatible)
        # Note: SQLite doesn't support IF NOT EXISTS for CREATE INDEX, so we try/except
        try:
            conn.execute(text("""
                CREATE INDEX ix_sessions_project_id ON sessions (project_id)
            """))
            conn.commit()
        except (OperationalError, ProgrammingError):
            conn.rollback()  # Index already exists

        try:
            conn.execute(text("""
                CREATE INDEX ix_sessions_workspace_id ON sessions (workspace_id)
            """))
            conn.commit()
        except (OperationalError, ProgrammingError):
            conn.rollback()  # Index already exists

    mark_migration_applied(engine, migration_name)
    logger.info("migration_applied", migration=migration_name)


def migrate_004_add_token_usage_to_sessions(engine: Engine) -> None:
    """Add token usage tracking columns to sessions table.

    These columns track LLM token usage for transparency:
    - prompt_tokens: Tokens used for prompts
    - completion_tokens: Tokens used for completions
    - total_tokens: Total tokens used
    """
    migration_name = "004_add_token_usage_to_sessions"

    if migration_applied(engine, migration_name):
        return

    columns_to_add = [
        ("prompt_tokens", "INTEGER DEFAULT 0"),
        ("completion_tokens", "INTEGER DEFAULT 0"),
        ("total_tokens", "INTEGER DEFAULT 0"),
    ]

    with engine.connect() as conn:
        for col_name, col_type in columns_to_add:
            if not column_exists(engine, "sessions", col_name):
                try:
                    conn.execute(text(f"""
                        ALTER TABLE sessions
                        ADD COLUMN {col_name} {col_type}
                    """))
                    conn.commit()
                    logger.info("migration_column_added", migration=migration_name, column=col_name)
                except (OperationalError, ProgrammingError) as e:
                    if "already exists" in str(e):
                        conn.rollback()
                        logger.info("migration_column_already_exists", migration=migration_name, column=col_name)
                    else:
                        raise

    mark_migration_applied(engine, migration_name)
    logger.info("migration_applied", migration=migration_name)


# List of all migrations in order
MIGRATIONS = [
    migrate_001_add_agent_id_to_approvals,
    migrate_002_add_agent_state_to_approvals,
    migrate_003_add_project_workspace_to_sessions,
    migrate_004_add_token_usage_to_sessions,
]


def run_migrations(engine: Engine) -> None:
    """Run all pending migrations."""
    ensure_migrations_table(engine)

    applied_count = 0
    for migration in MIGRATIONS:
        migration_name = migration.__name__.replace("migrate_", "")
        try:
            migration(engine)
            applied_count += 1
        except Exception as e:
            logger.error(
                "migration_failed",
                migration=migration_name,
                error=str(e),
            )
            raise

    logger.info("migrations_complete", applied=applied_count, total=len(MIGRATIONS))
