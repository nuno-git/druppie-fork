"""Tests for get_user_paused_leaves — finding leaf-most PAUSED_USER runs."""

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from druppie.domain.common import AgentRunStatus
from druppie.repositories.execution_repository import ExecutionRepository


def _make_run(
    run_id=None,
    parent_run_id=None,
    status="paused_user",
    agent_id="agent",
):
    run = MagicMock()
    run.id = run_id or uuid4()
    run.parent_run_id = parent_run_id
    run.status = status
    run.agent_id = agent_id
    run.session_id = uuid4()
    run.spawning_tool_call_id = None
    run.sequence_number = None
    run.planned_prompt = ""
    run.error_message = None
    run.iteration_count = 0
    run.prompt_tokens = 0
    run.completion_tokens = 0
    run.total_tokens = 0
    run.started_at = None
    run.completed_at = None
    run.created_at = None
    return run


def _make_repo(paused_runs):
    """Create an ExecutionRepository with mocked DB returning given paused_runs."""
    db = MagicMock()
    query_chain = MagicMock()
    query_chain.filter.return_value = query_chain
    query_chain.all.return_value = paused_runs
    db.query.return_value = query_chain

    repo = ExecutionRepository.__new__(ExecutionRepository)
    repo.db = db
    repo._to_summary = lambda r: r
    return repo


class TestGetUserPausedLeaves:
    def test_no_paused_runs_returns_empty(self):
        repo = _make_repo([])
        result = repo.get_user_paused_leaves(uuid4())
        assert result == []

    def test_single_paused_run_returns_it(self):
        session_id = uuid4()
        run_a = _make_run(agent_id="A")
        repo = _make_repo([run_a])
        result = repo.get_user_paused_leaves(session_id)
        assert result == [run_a]

    def test_linear_chain_returns_deepest(self):
        run_a = _make_run(agent_id="A")
        run_b = _make_run(agent_id="B", parent_run_id=run_a.id)
        run_c = _make_run(agent_id="C", parent_run_id=run_b.id)
        repo = _make_repo([run_a, run_b, run_c])
        result = repo.get_user_paused_leaves(uuid4())
        assert result == [run_c]

    def test_parallel_children_returns_both(self):
        run_a = _make_run(agent_id="A")
        run_b = _make_run(agent_id="B", parent_run_id=run_a.id)
        run_c = _make_run(agent_id="C", parent_run_id=run_a.id)
        repo = _make_repo([run_a, run_b, run_c])
        result = repo.get_user_paused_leaves(uuid4())
        assert set(r.id for r in result) == {run_b.id, run_c.id}

    def test_mixed_tree_returns_all_leaves(self):
        run_a = _make_run(agent_id="A")
        run_b = _make_run(agent_id="B", parent_run_id=run_a.id)
        run_c = _make_run(agent_id="C", parent_run_id=run_a.id)
        run_d = _make_run(agent_id="D", parent_run_id=run_c.id)
        run_e = _make_run(agent_id="E", parent_run_id=run_c.id)
        repo = _make_repo([run_a, run_b, run_c, run_d, run_e])
        result = repo.get_user_paused_leaves(uuid4())
        assert set(r.id for r in result) == {run_b.id, run_d.id, run_e.id}

    def test_deep_parallel_tree_returns_all_leaves(self):
        run_a = _make_run(agent_id="A")
        run_b = _make_run(agent_id="B", parent_run_id=run_a.id)
        run_c = _make_run(agent_id="C", parent_run_id=run_a.id)
        run_d = _make_run(agent_id="D", parent_run_id=run_b.id)
        run_e = _make_run(agent_id="E", parent_run_id=run_b.id)
        run_f = _make_run(agent_id="F", parent_run_id=run_c.id)
        run_g = _make_run(agent_id="G", parent_run_id=run_c.id)
        repo = _make_repo([run_a, run_b, run_c, run_d, run_e, run_f, run_g])
        result = repo.get_user_paused_leaves(uuid4())
        assert set(r.id for r in result) == {run_d.id, run_e.id, run_f.id, run_g.id}

    def test_partially_paused_skips_non_paused_children(self):
        run_a = _make_run(agent_id="A")
        run_b = _make_run(agent_id="B", parent_run_id=run_a.id, status="completed")
        run_c = _make_run(agent_id="C", parent_run_id=run_a.id)
        # Only A and C are paused — B is completed so not in the paused list
        repo = _make_repo([run_a, run_c])
        result = repo.get_user_paused_leaves(uuid4())
        # A has paused child C → skip A. C has no paused children → leaf
        assert result == [run_c]

    def test_sibling_groups_from_different_tool_calls(self):
        run_a = _make_run(agent_id="A")
        run_b = _make_run(agent_id="B", parent_run_id=run_a.id)
        run_c = _make_run(agent_id="C", parent_run_id=run_a.id)
        run_d = _make_run(agent_id="D", parent_run_id=run_a.id)
        repo = _make_repo([run_a, run_b, run_c, run_d])
        result = repo.get_user_paused_leaves(uuid4())
        assert set(r.id for r in result) == {run_b.id, run_c.id, run_d.id}

    def test_get_user_paused_run_returns_first_leaf(self):
        run_a = _make_run(agent_id="A")
        run_b = _make_run(agent_id="B", parent_run_id=run_a.id)
        run_c = _make_run(agent_id="C", parent_run_id=run_a.id)
        repo = _make_repo([run_a, run_b, run_c])
        result = repo.get_user_paused_run(uuid4())
        assert result in [run_b, run_c]
