"""Vector Store database connection and schema management."""

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
        _pool = await asyncpg.create_pool(
            DB_URL,
            min_size=2,
            max_size=10,
            init=_init_connection,
        )
        await _run_migrations(_pool)
        logger.info("Database pool created and migrations applied")
        return _pool


async def _init_connection(conn: asyncpg.Connection):
    """Register pgvector type on each new connection."""
    await register_vector(conn)


async def _run_migrations(pool: asyncpg.Pool):
    """Apply SQL migration files in order."""
    migration_files = sorted(SCHEMA_DIR.glob("[0-9]*.sql"))
    async with pool.acquire() as conn:
        for migration_file in migration_files:
            sql = migration_file.read_text()
            logger.info("Applying migration: %s", migration_file.name)
            await conn.execute(sql)


async def close_pool():
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        logger.info("Database pool closed")
