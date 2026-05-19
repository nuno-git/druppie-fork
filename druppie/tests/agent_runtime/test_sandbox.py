"""Tests for druppie.agent_runtime.sandbox."""


import pytest

from druppie.agent_runtime.sandbox import SandboxWarmPool, make_sandbox_resolver
from druppie.agent_runtime.tools.mcp import MCPConnection


def _make_mock_conn(git_scope: str) -> MCPConnection:
    return MCPConnection(
        server_name=f"sandbox-{git_scope}",
        endpoint=f"http://sandbox-{git_scope}:9001",
        tools=[{"name": "read_file", "parameters": {}}],
    )


class TestSandboxWarmPool:
    @pytest.mark.asyncio
    async def test_get_container_from_pool(self):
        conn = _make_mock_conn("current_project")
        pool = SandboxWarmPool(pool_size=1)
        pool._pools["current_project"] = [(conn, 0)]

        result = await pool.get_container("current_project")
        assert result is conn
        assert len(pool._pools["current_project"]) == 0

    @pytest.mark.asyncio
    async def test_get_container_creates_new(self):
        created = []

        async def create_fn(scope):
            c = _make_mock_conn(scope)
            created.append(c)
            return c

        pool = SandboxWarmPool(create_fn=create_fn)
        result = await pool.get_container("current_project")
        assert len(created) == 1
        assert result is created[0]

    @pytest.mark.asyncio
    async def test_get_container_no_create_fn_raises(self):
        pool = SandboxWarmPool()
        with pytest.raises(RuntimeError, match="No create_fn"):
            await pool.get_container("current_project")

    @pytest.mark.asyncio
    async def test_release_container(self):
        conn = _make_mock_conn("current_project")
        pool = SandboxWarmPool()
        await pool.release_container(conn)

    @pytest.mark.asyncio
    async def test_warm_up(self):
        created = []

        async def create_fn(scope):
            c = _make_mock_conn(scope)
            created.append(c)
            return c

        pool = SandboxWarmPool(pool_size=3, create_fn=create_fn)
        await pool.warm_up("current_project")
        assert len(created) == 3
        assert len(pool._pools["current_project"]) == 3

    @pytest.mark.asyncio
    async def test_recycle_idle(self):
        import time
        old_conn = _make_mock_conn("old")
        new_conn = _make_mock_conn("new")
        pool = SandboxWarmPool(recycle_timeout_s=1)
        pool._pools["test"] = [
            (old_conn, time.time() - 100),
            (new_conn, time.time()),
        ]

        recycled = await pool.recycle_idle()
        assert recycled == 1
        assert len(pool._pools["test"]) == 1
        assert pool._pools["test"][0][0] is new_conn


class TestMakeSandboxResolver:
    @pytest.mark.asyncio
    async def test_resolver_returns_from_pool(self):
        conn = _make_mock_conn("current_project")
        pool = SandboxWarmPool(pool_size=1)
        pool._pools["current_project"] = [(conn, 0)]

        resolver = make_sandbox_resolver(pool)
        result = await resolver("current_project")
        assert result is conn
