"""Regression test for ContextVar-based task-local DB session isolation in ToolExecutor.

Guards PR #284 (fix/tool-executor-db-race): ``_scoped_session()`` previously
mutated shared instance state (``self.db``), so concurrent tool executions
clobbered each other's DB session — the last task to enter its scope "won" and
every sibling silently used that session.

The fix uses a module-level ``ContextVar`` (``_task_db``). asyncio copies the
context when it creates each ``Task``, so every concurrent ``_scoped_session()``
scope sees its own session via ``_task_db.set(db)`` / ``_task_db.reset(token)``.

These tests FAIL if ``_scoped_session`` is reverted to mutating shared instance
state (the old race), because the concurrent scopes would collapse onto a single
shared session.
"""

import asyncio
from unittest.mock import MagicMock

import pytest

from druppie.execution.tool_executor import ToolExecutor, _task_db

# Number of concurrent scopes spawned by asyncio.gather. Must be > 1 to exercise
# cross-task isolation; kept modest to stay fast and deterministic.
NUM_CONCURRENT = 8


def _make_factory():
    """Return ``(session_factory, created)`` where each call yields a fresh mock.

    ``created`` captures every session the factory produces, in creation order,
    so tests can assert distinctness by object identity.
    """
    created: list[MagicMock] = []

    def factory() -> MagicMock:
        session = MagicMock(name=f"db-session-{len(created)}")
        created.append(session)
        return session

    return factory, created


def _make_executor(session_factory) -> ToolExecutor:
    """Build a ToolExecutor in factory mode with mocked MCP dependencies."""
    return ToolExecutor(
        db=None,
        mcp_http=MagicMock(),
        mcp_config=MagicMock(),
        session_factory=session_factory,
    )


class TestScopedSessionTaskIsolation:
    """Prove concurrent _scoped_session() scopes get distinct task-local sessions."""

    @pytest.mark.asyncio
    async def test_concurrent_scopes_get_distinct_sessions(self):
        """(c)+(d) Each concurrent scope sees its OWN session, stable across awaits."""
        factory, created = _make_factory()
        executor = _make_executor(factory)

        seen_at_entry: dict[int, MagicMock] = {}
        seen_after_yield: dict[int, MagicMock] = {}

        async def worker(task_index: int) -> None:
            # asyncio.gather wraps this coroutine in a Task, which copies the
            # context — so _task_db.set() inside _scoped_session only affects
            # this task. Under the old shared-state bug, self.db would be
            # clobbered by sibling tasks during the awaits below.
            with executor._scoped_session():
                seen_at_entry[task_index] = executor._active_db
                # Yield repeatedly so every sibling task enters its own scope
                # and assigns its session. If isolation were broken, the value
                # read after these yields would belong to another task.
                for _ in range(NUM_CONCURRENT):
                    await asyncio.sleep(0)
                seen_after_yield[task_index] = executor._active_db

        await asyncio.gather(*(worker(i) for i in range(NUM_CONCURRENT)))

        # (c) The factory produced exactly one fresh session per concurrent scope.
        assert len(created) == NUM_CONCURRENT

        # (c) Every scope observed a DISTINCT session at entry — no clobbering.
        entry_ids = {id(s) for s in seen_at_entry.values()}
        assert len(entry_ids) == NUM_CONCURRENT, "concurrent scopes shared a session"

        # The sessions seen at entry are exactly the ones the factory built.
        created_ids = {id(s) for s in created}
        assert entry_ids == created_ids

        # (d) _active_db stayed stable inside each scope across awaits and matched
        #     the entry value. Under the race bug these would collapse to the
        #     last-assigned shared session.
        after_yield_ids = set()
        for i in range(NUM_CONCURRENT):
            assert seen_at_entry[i] is seen_after_yield[i], (
                f"task {i}: _active_db changed mid-scope (session clobbered)"
            )
            after_yield_ids.add(id(seen_after_yield[i]))
        assert len(after_yield_ids) == NUM_CONCURRENT, (
            "concurrent scopes collapsed to a shared session after yielding"
        )

    @pytest.mark.asyncio
    async def test_each_factory_session_closed_on_scope_exit(self):
        """The finally block in _scoped_session closes every session exactly once."""
        factory, created = _make_factory()
        executor = _make_executor(factory)

        async def worker(_) -> None:
            with executor._scoped_session():
                await asyncio.sleep(0)

        await asyncio.gather(*(worker(i) for i in range(NUM_CONCURRENT)))

        assert len(created) == NUM_CONCURRENT
        for session in created:
            assert session.close.called, "scoped session was not closed on exit"

    @pytest.mark.asyncio
    async def test_task_db_reset_to_none_within_task_after_scope_exits(self):
        """(e) Within a task, _task_db reverts to None once the scope exits."""
        factory, _created = _make_factory()
        executor = _make_executor(factory)

        assert _task_db.get(None) is None  # baseline before entering

        with executor._scoped_session():
            # Inside the scope the task-local session is live.
            assert _task_db.get(None) is not None
            assert executor._active_db is _task_db.get(None)

        # Scope exited → reset(token) restored the prior (None) value, so there
        # is no leakage across sequential scopes within the same task.
        assert _task_db.get(None) is None
        # _active_db falls back to the instance db (None in factory mode).
        assert executor._active_db is None

    @pytest.mark.asyncio
    async def test_no_leakage_into_parent_context_after_concurrent_run(self):
        """(e) After asyncio.gather returns, the parent context's _task_db is None."""
        factory, _created = _make_factory()
        executor = _make_executor(factory)

        assert _task_db.get(None) is None  # parent baseline

        async def worker(_) -> None:
            with executor._scoped_session():
                # Inside the child task the task-local session is set.
                assert _task_db.get(None) is not None
                await asyncio.sleep(0)

        await asyncio.gather(*(worker(i) for i in range(NUM_CONCURRENT)))

        # No child task's _task_db value leaked into the parent context.
        assert _task_db.get(None) is None
        assert executor._active_db is None  # falls back to instance db

    @pytest.mark.asyncio
    async def test_non_factory_mode_is_noop(self):
        """Without a session_factory, _scoped_session never touches _task_db."""
        instance_db = MagicMock(name="instance-db")
        executor = ToolExecutor(
            db=instance_db,
            mcp_http=MagicMock(),
            mcp_config=MagicMock(),
            session_factory=None,
        )

        assert _task_db.get(None) is None

        with executor._scoped_session():
            # No task-local session set → _active_db falls back to instance db.
            assert _task_db.get(None) is None
            assert executor._active_db is instance_db

        assert _task_db.get(None) is None
        # The instance db was never closed (no-op scope owns no session).
        assert not instance_db.close.called
