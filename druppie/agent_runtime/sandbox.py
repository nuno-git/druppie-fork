"""Sandbox warm pool and resolver helpers.

Maintains a pool of pre-started sandbox containers for fast agent startup.
The sandbox_resolver factory creates closures for resolving git scopes to MCP connections.
"""

from __future__ import annotations

import asyncio
import time
from typing import Awaitable, Callable

from druppie.agent_runtime.tools.mcp import MCPConnection


class SandboxWarmPool:
    """Pre-warmed sandbox container pool.

    Maintains a configurable number of warm containers per git scope.
    Containers are created on demand and recycled after a timeout.
    """

    def __init__(
        self,
        pool_size: int = 3,
        recycle_timeout_s: int = 3600,
        create_fn: Callable[[str], Awaitable[MCPConnection]] | None = None,
    ) -> None:
        self.pool_size = pool_size
        self.recycle_timeout_s = recycle_timeout_s
        self._create_fn = create_fn
        self._pools: dict[str, list[tuple[MCPConnection, float]]] = {}
        self._lock = asyncio.Lock()

    async def get_container(self, git_scope: str) -> MCPConnection:
        """Get a warm container, or create one if pool empty."""
        async with self._lock:
            if git_scope in self._pools and self._pools[git_scope]:
                conn, _ = self._pools[git_scope].pop(0)
                return conn

        if self._create_fn:
            return await self._create_fn(git_scope)
        raise RuntimeError(f"No create_fn configured and pool empty for {git_scope}")

    async def release_container(self, connection: MCPConnection) -> None:
        """Stop and discard a used container (pool creates fresh ones)."""
        pass

    async def warm_up(self, git_scope: str) -> None:
        """Pre-warm the pool for a given git scope."""
        if not self._create_fn:
            return
        async with self._lock:
            if git_scope not in self._pools:
                self._pools[git_scope] = []
            current = len(self._pools[git_scope])
            for _ in range(self.pool_size - current):
                conn = await self._create_fn(git_scope)
                self._pools[git_scope].append((conn, time.time()))

    async def recycle_idle(self) -> int:
        """Recycle containers idle beyond recycle_timeout_s. Returns count recycled."""
        now = time.time()
        recycled = 0
        async with self._lock:
            for scope in list(self._pools.keys()):
                pool = self._pools[scope]
                fresh = []
                for conn, created_at in pool:
                    if now - created_at > self.recycle_timeout_s:
                        recycled += 1
                    else:
                        fresh.append((conn, created_at))
                self._pools[scope] = fresh
        return recycled


def make_sandbox_resolver(
    pool: SandboxWarmPool,
) -> Callable[[str], Awaitable[MCPConnection]]:
    """Create a sandbox_resolver closure from a warm pool.

    The resolver is a closure that the runtime passes to subagent spawning
    so child agents can get sandbox connections when needed.

    Returns:
        Async callable: sandbox_resolver(git_scope: str) -> MCPConnection
    """
    async def sandbox_resolver(git_scope: str) -> MCPConnection:
        return await pool.get_container(git_scope)

    return sandbox_resolver
