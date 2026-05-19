"""
Warm pool — pre-created sandbox containers ready for instant assignment.

Containers are created in the background and kept idle. When an agent needs a
sandbox, the pool hands out a warm container immediately instead of waiting
for container creation (~2-5s). Used containers are discarded (never recycled
back into the pool) for security isolation.
"""

import asyncio
import logging
import time

from . import config
from .manager import ContainerError, create_container_manager

log = logging.getLogger(__name__)


class SandboxWarmPool:
    def __init__(
        self,
        pool_size: int | None = None,
        recycle_timeout_s: int | None = None,
    ) -> None:
        self.pool_size = pool_size or config.POOL_SIZE
        self.recycle_timeout_s = recycle_timeout_s or config.POOL_RECYCLE_SECONDS
        self._pools: dict[str, list[tuple[str, float]]] = {}
        self._manager = create_container_manager()
        self._lock = asyncio.Lock()
        self._bg_tasks: set[asyncio.Task] = set()

    async def get_or_create(
        self, sandbox_id: str, git_scope: str, env_vars: dict[str, str]
    ) -> str:
        """Get a warm container or create a new one."""
        async with self._lock:
            pool = self._pools.get(git_scope, [])
            while pool:
                container_id, created_at = pool.pop(0)
                if time.time() - created_at > self.recycle_timeout_s:
                    self._bg_tasks.add(
                        asyncio.create_task(self._safe_stop(container_id))
                    )
                    continue
                if await self._manager.is_running(container_id):
                    log.info("Reusing warm container %s for %s", container_id, git_scope)
                    return container_id
                log.warning("Warm container %s not running, discarding", container_id)

        log.info("No warm container available for %s, creating new", git_scope)
        return await self._manager.create(sandbox_id, env_vars)

    async def release(self, container_id: str) -> None:
        """Stop and discard a used container."""
        await self._safe_stop(container_id)

    async def warm_up(self, git_scope: str, count: int | None = None) -> None:
        """Pre-create containers for a git scope."""
        count = count or self.pool_size
        async with self._lock:
            current = len(self._pools.get(git_scope, []))
            needed = max(0, count - current)

        if needed == 0:
            return

        log.info("Warming up %d containers for %s", needed, git_scope)

        async def _create_one(idx: int) -> None:
            sandbox_id = f"warm-{git_scope}-{idx}-{int(time.time())}"
            try:
                cid = await self._manager.create(sandbox_id, env_vars={})
                async with self._lock:
                    self._pools.setdefault(git_scope, []).append(
                        (cid, time.time())
                    )
                log.debug("Warmed container %s for %s", cid, git_scope)
            except ContainerError:
                log.exception("Failed to warm container %d for %s", idx, git_scope)

        await asyncio.gather(*[_create_one(i) for i in range(needed)])

    async def drain(self, git_scope: str | None = None) -> None:
        """Stop all warm containers, optionally filtered by git_scope."""
        scopes = [git_scope] if git_scope else list(self._pools.keys())
        for scope in scopes:
            async with self._lock:
                containers = self._pools.pop(scope, [])
            for cid, _ in containers:
                await self._safe_stop(cid)

    async def _safe_stop(self, container_id: str) -> None:
        try:
            await self._manager.stop(container_id)
        except ContainerError:
            log.warning("Failed to stop container %s", container_id, exc_info=True)
