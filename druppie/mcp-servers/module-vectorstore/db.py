"""Vector Store database connection and schema management.

Self-initialising: on first connection the module creates the pgvector
extension, applies schema migrations, and registers the vector type on
every pooled connection.  No manual database setup is required — only a
running PostgreSQL instance with the pgvector image.
"""

import asyncio
import logging
import os
from pathlib import Path

import asyncpg
from pgvector.asyncpg import register_vector

logger = logging.getLogger("vectorstore-mcp.db")

_pool: asyncpg.Pool | None = None
_pool_lock = asyncio.Lock()

DB_URL = os.getenv(
    "MODULE_DB_URL",
    "postgresql://module_vectorstore:module_vectorstore_dev@module-vectorstore-db:5432/module_vectorstore",
)

SCHEMA_DIR = Path(__file__).parent / "v1" / "schema"


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is not None:
        return _pool
    async with _pool_lock:
        if _pool is not None:
            return _pool

        # 1. Bootstrap: create pgvector extension + run schema migrations
        #    via a bare connection *before* creating the pool.  The pool's
        #    init callback (register_vector) requires the extension to exist,
        #    so we must ensure it first.
        await _bootstrap_schema()

        # 2. Now the extension exists — safe to create the pool with
        #    register_vector on every connection.
        _pool = await asyncpg.create_pool(
            DB_URL,
            min_size=2,
            max_size=10,
            init=_init_connection,
        )
        logger.info("Database pool created (schema already applied)")
        return _pool


async def _bootstrap_schema():
    """Create the pgvector extension and apply migrations.

    Uses a single temporary connection so the pool (which needs the
    extension for register_vector) can be created afterwards.
    """
    conn = await asyncpg.connect(DB_URL)
    try:
        await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        logger.info("pgvector extension ensured")

        migration_files = sorted(SCHEMA_DIR.glob("[0-9]*.sql"))
        for migration_file in migration_files:
            sql = migration_file.read_text()
            logger.info("Applying migration: %s", migration_file.name)
            await conn.execute(sql)
    finally:
        await conn.close()


async def _init_connection(conn: asyncpg.Connection):
    """Register pgvector type on each new connection."""
    await register_vector(conn)


async def close_pool():
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        logger.info("Database pool closed")
