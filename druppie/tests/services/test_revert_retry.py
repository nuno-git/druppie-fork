"""Tests for RevertService.retry_nested_subagent_run.

Verifies tree-based sibling detection using spawning_tool_call_id:
- Siblings from the SAME spawning_tool_call_id (parallel batch) → KEPT
- Siblings from LATER spawning_tool_call_id (sequential) → SUPERSEDED regardless of status
- Descendants of superseded siblings are also marked superseded
- Parent chain is properly reset
"""

from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from druppie.domain.common import AgentRunStatus
from druppie.services.revert_service import RevertService


def _make_run(
    run_id=None,
    parent_run_id=None,
    agent_id="agent",
    status="completed",
    spawning_tool_call_id=None,
    planned_prompt="",
    session_id=None,
    created_at=None,
):
    run = MagicMock()
    run.id = run_id or uuid4()
    run.parent_run_id = parent_run_id
    run.agent_id = agent_id
    run.status = status
    run.spawning_tool_call_id = spawning_tool_call_id
    run.planned_prompt = planned_prompt
    run.session_id = session_id or uuid4()
    run.sequence_number = 1
    run.error_message = None
    run.iteration_count = 0
    run.completed_at = datetime.now(timezone.utc)
    run.created_at = created_at or datetime.now(timezone.utc)
    return run


def _make_tc(tc_id=None, created_at=None):
    tc = MagicMock()
    tc.id = tc_id or uuid4()
    tc.created_at = created_at or datetime.now(timezone.utc)
    return tc


def _make_mock_db(children, tc_map):
    """Create a mock DB session that returns children and tool calls."""
    db = MagicMock()

    def query_filter_chain(model):
        chain = MagicMock()

        def filter_fn(*args, **kwargs):
            return chain

        chain.filter = filter_fn

        if model.__name__ == "AgentRun":
            chain.all.return_value = children
        elif model.__name__ == "ToolCall":
            chain.first.side_effect = lambda: None
        return chain

    db.query.side_effect = query_filter
    return db


def _make_revert_service(execution_repo=None, session_repo=None, mcp_http=None):
    execution_repo = execution_repo or MagicMock()
    session_repo = session_repo or MagicMock()
    mcp_http = mcp_http or AsyncMock()
    return RevertService(execution_repo, session_repo, mcp_http)


def _patch_no_parent_chain(svc):
    return patch.object(svc, "_reset_parent_chain_for_retry")


def _collect_superseded_ids(repo):
    superseded = set()
    for call in repo.mark_runs_superseded.call_args_list:
        for run_id in call[0][0]:
            superseded.add(run_id)
    return superseded


class TestTreeBasedSiblingDetection:
    """Siblings detected via spawning_tool_call_id, not timestamps."""

    @pytest.mark.asyncio
    async def test_parallel_sibling_same_tc_is_kept(self):
        parent_run_id = uuid4()
        session_id = uuid4()
        tc_id = uuid4()
        base_time = datetime.now(timezone.utc)

        target = _make_run(
            parent_run_id=parent_run_id, agent_id="test_builder",
            spawning_tool_call_id=tc_id, created_at=base_time,
        )
        parallel = _make_run(
            parent_run_id=parent_run_id, agent_id="developer",
            spawning_tool_call_id=tc_id, created_at=base_time,
        )

        tc = _make_tc(tc_id=tc_id, created_at=base_time)

        repo = MagicMock()
        repo.get_by_id_for_session.return_value = target
        repo._to_summary.side_effect = lambda r: r
        repo.db = MagicMock()
        repo.db.query.return_value.filter.return_value.all.return_value = [target, parallel]
        repo.db.query.return_value.filter.return_value.first.return_value = tc

        svc = _make_revert_service(execution_repo=repo)

        with patch.object(svc, "_collect_descendants", return_value=[]), \
             _patch_no_parent_chain(svc):
            result = await svc.retry_nested_subagent_run(session_id, target.id)

        superseded = _collect_superseded_ids(repo)
        assert parallel.id not in superseded
        assert target.id in superseded  # target is superseded (a new copy replaces it)

    @pytest.mark.asyncio
    async def test_sequential_sibling_later_tc_is_superseded(self):
        parent_run_id = uuid4()
        session_id = uuid4()
        tc_1 = uuid4()
        tc_2 = uuid4()
        t1 = datetime.now(timezone.utc)
        t2 = t1 + timedelta(seconds=10)

        target = _make_run(
            parent_run_id=parent_run_id, agent_id="test_builder",
            spawning_tool_call_id=tc_1, created_at=t1,
        )
        later = _make_run(
            parent_run_id=parent_run_id, agent_id="developer",
            status="completed", spawning_tool_call_id=tc_2, created_at=t2,
        )

        tc_1_obj = _make_tc(tc_id=tc_1, created_at=t1)
        tc_2_obj = _make_tc(tc_id=tc_2, created_at=t2)

        repo = MagicMock()
        repo.get_by_id_for_session.return_value = target
        repo._to_summary.side_effect = lambda r: r

        tc_lookup = {tc_1: tc_1_obj, tc_2: tc_2_obj}
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = [target, later]
        db.query.return_value.filter.return_value.first.side_effect = lambda: None
        repo.db = db

        call_count = [0]
        def first_side_effect():
            call_count[0] += 1
            if call_count[0] == 1:
                return tc_1_obj
            return tc_2_obj
        db.query.return_value.filter.return_value.first.side_effect = first_side_effect

        svc = _make_revert_service(execution_repo=repo)

        with patch.object(svc, "_collect_descendants", return_value=[]), \
             _patch_no_parent_chain(svc):
            result = await svc.retry_nested_subagent_run(session_id, target.id)

        superseded = _collect_superseded_ids(repo)
        assert later.id in superseded
        assert str(later.id) in result["deleted_sibling_ids"]

    @pytest.mark.asyncio
    async def test_paused_sequential_sibling_is_superseded(self):
        parent_run_id = uuid4()
        session_id = uuid4()
        tc_1 = uuid4()
        tc_2 = uuid4()
        t1 = datetime.now(timezone.utc)
        t2 = t1 + timedelta(seconds=10)

        target = _make_run(
            parent_run_id=parent_run_id, agent_id="test_builder",
            spawning_tool_call_id=tc_1, created_at=t1,
        )
        paused = _make_run(
            parent_run_id=parent_run_id, agent_id="developer",
            status="paused_user", spawning_tool_call_id=tc_2, created_at=t2,
        )

        tc_1_obj = _make_tc(tc_id=tc_1, created_at=t1)
        tc_2_obj = _make_tc(tc_id=tc_2, created_at=t2)

        repo = MagicMock()
        repo.get_by_id_for_session.return_value = target
        repo._to_summary.side_effect = lambda r: r

        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = [target, paused]

        call_count = [0]
        def first_side_effect():
            call_count[0] += 1
            if call_count[0] == 1:
                return tc_1_obj
            return tc_2_obj
        db.query.return_value.filter.return_value.first.side_effect = first_side_effect
        repo.db = db

        svc = _make_revert_service(execution_repo=repo)

        with patch.object(svc, "_collect_descendants", return_value=[]), \
             _patch_no_parent_chain(svc):
            await svc.retry_nested_subagent_run(session_id, target.id)

        superseded = _collect_superseded_ids(repo)
        assert paused.id in superseded

    @pytest.mark.asyncio
    async def test_mixed_parallel_kept_sequential_superseded(self):
        parent_run_id = uuid4()
        session_id = uuid4()
        tc_1 = uuid4()
        tc_2 = uuid4()
        t1 = datetime.now(timezone.utc)
        t2 = t1 + timedelta(seconds=10)

        target = _make_run(parent_run_id=parent_run_id, agent_id="builder", spawning_tool_call_id=tc_1, created_at=t1)
        parallel = _make_run(parent_run_id=parent_run_id, agent_id="test_builder", spawning_tool_call_id=tc_1, created_at=t1)
        sequential = _make_run(parent_run_id=parent_run_id, agent_id="developer", status="paused_user", spawning_tool_call_id=tc_2, created_at=t2)

        tc_1_obj = _make_tc(tc_id=tc_1, created_at=t1)
        tc_2_obj = _make_tc(tc_id=tc_2, created_at=t2)

        repo = MagicMock()
        repo.get_by_id_for_session.return_value = target
        repo._to_summary.side_effect = lambda r: r

        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = [target, parallel, sequential]

        results = [tc_1_obj, tc_2_obj]
        idx = [0]
        def first_side_effect():
            val = results[idx[0]] if idx[0] < len(results) else results[-1]
            idx[0] += 1
            return val
        db.query.return_value.filter.return_value.first.side_effect = first_side_effect
        repo.db = db

        svc = _make_revert_service(execution_repo=repo)

        with patch.object(svc, "_collect_descendants", return_value=[]), \
             _patch_no_parent_chain(svc):
            result = await svc.retry_nested_subagent_run(session_id, target.id)

        superseded = _collect_superseded_ids(repo)
        assert parallel.id not in superseded
        assert sequential.id in superseded
        assert str(sequential.id) in result["deleted_sibling_ids"]
        assert "paused_sibling_ids" not in result

    @pytest.mark.asyncio
    async def test_target_reset_to_pending(self):
        parent_run_id = uuid4()
        session_id = uuid4()
        tc_id = uuid4()

        target = _make_run(parent_run_id=parent_run_id, agent_id="builder", spawning_tool_call_id=tc_id)
        tc_obj = _make_tc(tc_id=tc_id)

        repo = MagicMock()
        repo.get_by_id_for_session.return_value = target
        repo._to_summary.side_effect = lambda r: r

        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = [target]
        db.query.return_value.filter.return_value.first.return_value = tc_obj
        repo.db = db

        svc = _make_revert_service(execution_repo=repo)

        with patch.object(svc, "_collect_descendants", return_value=[]), \
             _patch_no_parent_chain(svc):
            await svc.retry_nested_subagent_run(session_id, target.id)

        repo.mark_runs_superseded.assert_any_call([target.id])
        repo.create_superseding_copies.assert_called_once_with([target])

    @pytest.mark.asyncio
    async def test_descendants_of_sequential_sibling_deleted(self):
        parent_run_id = uuid4()
        session_id = uuid4()
        tc_1 = uuid4()
        tc_2 = uuid4()
        t1 = datetime.now(timezone.utc)
        t2 = t1 + timedelta(seconds=10)
        grandchild_id = uuid4()

        target = _make_run(parent_run_id=parent_run_id, agent_id="builder", spawning_tool_call_id=tc_1, created_at=t1)
        sequential = _make_run(parent_run_id=parent_run_id, agent_id="developer", spawning_tool_call_id=tc_2, created_at=t2)

        tc_1_obj = _make_tc(tc_id=tc_1, created_at=t1)
        tc_2_obj = _make_tc(tc_id=tc_2, created_at=t2)

        repo = MagicMock()
        repo.get_by_id_for_session.return_value = target
        repo._to_summary.side_effect = lambda r: r

        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = [target, sequential]

        results = [tc_1_obj, tc_2_obj]
        idx = [0]
        def first_side_effect():
            val = results[idx[0]] if idx[0] < len(results) else results[-1]
            idx[0] += 1
            return val
        db.query.return_value.filter.return_value.first.side_effect = first_side_effect
        repo.db = db

        svc = _make_revert_service(execution_repo=repo)

        desc_map = {sequential.id: [grandchild_id]}
        with patch.object(svc, "_collect_descendants", side_effect=lambda rid: desc_map.get(rid, [])), \
             _patch_no_parent_chain(svc):
            await svc.retry_nested_subagent_run(session_id, target.id)

        superseded = _collect_superseded_ids(repo)
        assert sequential.id in superseded
        assert grandchild_id in superseded

    @pytest.mark.asyncio
    async def test_planned_prompt_updated(self):
        parent_run_id = uuid4()
        session_id = uuid4()
        tc_id = uuid4()
        new_run_id = uuid4()

        target = _make_run(parent_run_id=parent_run_id, agent_id="builder", spawning_tool_call_id=tc_id)
        tc_obj = _make_tc(tc_id=tc_id)

        repo = MagicMock()
        repo.get_by_id_for_session.return_value = target
        repo._to_summary.side_effect = lambda r: r
        repo.create_superseding_copies.return_value = {target.id: new_run_id}

        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = [target]
        db.query.return_value.filter.return_value.first.return_value = tc_obj
        repo.db = db

        svc = _make_revert_service(execution_repo=repo)

        with patch.object(svc, "_collect_descendants", return_value=[]), \
             _patch_no_parent_chain(svc):
            await svc.retry_nested_subagent_run(session_id, target.id, planned_prompt="New prompt")

        repo.update_planned_prompt.assert_called_once_with(new_run_id, "New prompt")

    @pytest.mark.asyncio
    async def test_no_paused_sibling_ids_in_result(self):
        parent_run_id = uuid4()
        session_id = uuid4()
        tc_id = uuid4()

        target = _make_run(parent_run_id=parent_run_id, agent_id="builder", spawning_tool_call_id=tc_id)
        tc_obj = _make_tc(tc_id=tc_id)

        repo = MagicMock()
        repo.get_by_id_for_session.return_value = target
        repo._to_summary.side_effect = lambda r: r

        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = [target]
        db.query.return_value.filter.return_value.first.return_value = tc_obj
        repo.db = db

        svc = _make_revert_service(execution_repo=repo)

        with patch.object(svc, "_collect_descendants", return_value=[]), \
             _patch_no_parent_chain(svc):
            result = await svc.retry_nested_subagent_run(session_id, target.id)

        assert "paused_sibling_ids" not in result
