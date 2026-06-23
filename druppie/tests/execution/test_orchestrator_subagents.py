"""Tests for orchestrator subagent completion and parent resume flow."""

import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4, UUID

import pytest

from druppie.domain.common import AgentRunStatus
from druppie.execution.orchestrator import Orchestrator


def _make_orchestrator():
    return Orchestrator(
        session_repo=MagicMock(),
        execution_repo=MagicMock(),
        project_repo=MagicMock(),
        question_repo=MagicMock(),
    )


def _make_db_mock(query_results=None):
    db = MagicMock()
    query_chain = MagicMock()
    if query_results is not None:
        query_chain.all.return_value = query_results
        query_chain.first.return_value = query_results[0] if query_results else None
    else:
        query_chain.all.return_value = []
        query_chain.first.return_value = None
    query_chain.filter.return_value = query_chain
    query_chain.order_by.return_value = query_chain
    db.query.return_value = query_chain
    return db, query_chain


def _make_sibling(status: str, agent_id: str = "child_agent", sibling_id=None, error_message=None):
    sibling = MagicMock()
    sibling.id = sibling_id or uuid4()
    sibling.agent_id = agent_id
    sibling.status = status
    sibling.error_message = error_message
    sibling.parent_run_id = uuid4()
    sibling.spawning_tool_call_id = uuid4()
    return sibling


def _make_tool_call(
    tool_name="subagents",
    status="paused",
    tc_id=None,
    result=None,
):
    tc = MagicMock()
    tc.id = tc_id or uuid4()
    tc.tool_name = tool_name
    tc.status = status
    tc.result = result
    return tc


class TestAllSiblingsCompleted:
    def test_returns_true_when_all_siblings_completed(self):
        orch = _make_orchestrator()
        siblings = [
            _make_sibling(status="completed", agent_id="child_a"),
            _make_sibling(status="completed", agent_id="child_b"),
            _make_sibling(status="completed", agent_id="child_c"),
        ]
        db, query_chain = _make_db_mock(siblings)
        orch.execution_repo.db = db

        result = orch._all_siblings_completed(uuid4(), uuid4())

        assert result is True

    def test_returns_true_when_all_siblings_terminal_mixed_statuses(self):
        orch = _make_orchestrator()
        siblings = [
            _make_sibling(status="completed"),
            _make_sibling(status="failed"),
            _make_sibling(status="cancelled"),
        ]
        db, query_chain = _make_db_mock(siblings)
        orch.execution_repo.db = db

        result = orch._all_siblings_completed(uuid4(), uuid4())

        assert result is True

    def test_returns_false_when_sibling_running(self):
        orch = _make_orchestrator()
        siblings = [
            _make_sibling(status="completed"),
            _make_sibling(status="running"),
        ]
        db, query_chain = _make_db_mock(siblings)
        orch.execution_repo.db = db

        result = orch._all_siblings_completed(uuid4(), uuid4())

        assert result is False

    def test_returns_false_when_sibling_paused_hitl(self):
        orch = _make_orchestrator()
        siblings = [
            _make_sibling(status="completed"),
            _make_sibling(status="paused_hitl"),
        ]
        db, query_chain = _make_db_mock(siblings)
        orch.execution_repo.db = db

        result = orch._all_siblings_completed(uuid4(), uuid4())

        assert result is False

    def test_returns_false_when_sibling_paused_tool(self):
        orch = _make_orchestrator()
        siblings = [
            _make_sibling(status="failed"),
            _make_sibling(status="paused_tool"),
        ]
        db, query_chain = _make_db_mock(siblings)
        orch.execution_repo.db = db

        result = orch._all_siblings_completed(uuid4(), uuid4())

        assert result is False

    def test_returns_true_when_no_siblings(self):
        orch = _make_orchestrator()
        db, query_chain = _make_db_mock([])
        orch.execution_repo.db = db

        result = orch._all_siblings_completed(uuid4(), uuid4())

        assert result is True

    def test_returns_false_when_sibling_paused_sandbox(self):
        orch = _make_orchestrator()
        siblings = [
            _make_sibling(status="completed"),
            _make_sibling(status="paused_sandbox"),
        ]
        db, query_chain = _make_db_mock(siblings)
        orch.execution_repo.db = db

        result = orch._all_siblings_completed(uuid4(), uuid4())

        assert result is False

    def test_returns_false_when_sibling_pending(self):
        orch = _make_orchestrator()
        siblings = [
            _make_sibling(status="completed"),
            _make_sibling(status="pending"),
        ]
        db, query_chain = _make_db_mock(siblings)
        orch.execution_repo.db = db

        result = orch._all_siblings_completed(uuid4(), uuid4())

        assert result is False


class TestAllSiblingsCompletedStrVsValueBug:
    def test_db_string_completed_is_detected_as_terminal(self):
        terminal_statuses = {
            AgentRunStatus.COMPLETED.value,
            AgentRunStatus.FAILED.value,
            AgentRunStatus.CANCELLED.value,
        }
        db_status = "completed"
        assert db_status in terminal_statuses

    def test_db_string_failed_is_detected_as_terminal(self):
        terminal_statuses = {
            AgentRunStatus.COMPLETED.value,
            AgentRunStatus.FAILED.value,
            AgentRunStatus.CANCELLED.value,
        }
        db_status = "failed"
        assert db_status in terminal_statuses

    def test_str_enum_is_not_equal_to_value(self):
        assert str(AgentRunStatus.COMPLETED) != AgentRunStatus.COMPLETED.value
        assert str(AgentRunStatus.COMPLETED) == "AgentRunStatus.COMPLETED"
        assert AgentRunStatus.COMPLETED.value == "completed"

    def test_all_siblings_completed_with_db_string_values_not_enum_instances(self):
        orch = _make_orchestrator()
        sibling = MagicMock()
        sibling.id = uuid4()
        sibling.agent_id = "child"
        sibling.status = "completed"

        db, query_chain = _make_db_mock([sibling])
        orch.execution_repo.db = db

        result = orch._all_siblings_completed(uuid4(), uuid4())

        assert result is True

    def test_all_siblings_completed_db_string_running_not_terminal(self):
        orch = _make_orchestrator()
        sibling = MagicMock()
        sibling.id = uuid4()
        sibling.agent_id = "child"
        sibling.status = "running"

        db, query_chain = _make_db_mock([sibling])
        orch.execution_repo.db = db

        result = orch._all_siblings_completed(uuid4(), uuid4())

        assert result is False


class TestPatchPausedSubagentsToolCall:
    def test_patches_completed_children_as_success(self):
        orch = _make_orchestrator()
        tc_id = uuid4()
        parent_run_id = uuid4()
        session_id = uuid4()

        paused_tc = _make_tool_call(tc_id=tc_id)

        children = [
            _make_sibling(status="completed", agent_id="child_a"),
            _make_sibling(status="completed", agent_id="child_b"),
        ]

        db = MagicMock()

        tc_query = MagicMock()
        tc_query.filter.return_value = tc_query
        tc_query.order_by.return_value = tc_query
        tc_query.first.return_value = paused_tc

        child_query = MagicMock()
        child_query.filter.return_value = child_query
        child_query.all.return_value = children

        db.query.side_effect = [tc_query, child_query]
        orch.execution_repo.db = db

        orch._patch_paused_subagents_tool_call(parent_run_id, session_id)

        result_data = json.loads(paused_tc.result)
        assert result_data["success"] is True
        assert len(result_data["data"]) == 2
        assert result_data["data"][0]["status"] == "success"
        assert result_data["data"][1]["status"] == "success"
        assert paused_tc.status == "completed"

    def test_patches_failed_children_as_error(self):
        orch = _make_orchestrator()
        tc_id = uuid4()
        parent_run_id = uuid4()
        session_id = uuid4()

        paused_tc = _make_tool_call(tc_id=tc_id)

        children = [
            _make_sibling(status="completed", agent_id="child_a"),
            _make_sibling(status="failed", agent_id="child_b", error_message="boom"),
        ]

        db = MagicMock()

        tc_query = MagicMock()
        tc_query.filter.return_value = tc_query
        tc_query.order_by.return_value = tc_query
        tc_query.first.return_value = paused_tc

        child_query = MagicMock()
        child_query.filter.return_value = child_query
        child_query.all.return_value = children

        db.query.side_effect = [tc_query, child_query]
        orch.execution_repo.db = db

        orch._patch_paused_subagents_tool_call(parent_run_id, session_id)

        result_data = json.loads(paused_tc.result)
        assert result_data["success"] is True
        assert result_data["data"][0]["status"] == "success"
        assert result_data["data"][1]["status"] == "error"
        assert result_data["data"][1]["error"] == "boom"

    def test_noop_when_no_paused_tool_call(self):
        orch = _make_orchestrator()
        parent_run_id = uuid4()
        session_id = uuid4()

        db = MagicMock()
        tc_query = MagicMock()
        tc_query.filter.return_value = tc_query
        tc_query.order_by.return_value = tc_query
        tc_query.first.return_value = None
        db.query.return_value = tc_query
        orch.execution_repo.db = db

        orch._patch_paused_subagents_tool_call(parent_run_id, session_id)

        db.commit.assert_not_called()

    def test_patches_cancelled_children_as_error(self):
        orch = _make_orchestrator()
        tc_id = uuid4()
        parent_run_id = uuid4()
        session_id = uuid4()

        paused_tc = _make_tool_call(tc_id=tc_id)

        children = [
            _make_sibling(status="cancelled", agent_id="child_x"),
        ]

        db = MagicMock()

        tc_query = MagicMock()
        tc_query.filter.return_value = tc_query
        tc_query.order_by.return_value = tc_query
        tc_query.first.return_value = paused_tc

        child_query = MagicMock()
        child_query.filter.return_value = child_query
        child_query.all.return_value = children

        db.query.side_effect = [tc_query, child_query]
        orch.execution_repo.db = db

        orch._patch_paused_subagents_tool_call(parent_run_id, session_id)

        result_data = json.loads(paused_tc.result)
        assert result_data["data"][0]["status"] == "error"

    def test_child_agent_id_included_in_result(self):
        orch = _make_orchestrator()
        tc_id = uuid4()
        parent_run_id = uuid4()
        session_id = uuid4()

        paused_tc = _make_tool_call(tc_id=tc_id)

        children = [
            _make_sibling(status="completed", agent_id="planner"),
        ]

        db = MagicMock()

        tc_query = MagicMock()
        tc_query.filter.return_value = tc_query
        tc_query.order_by.return_value = tc_query
        tc_query.first.return_value = paused_tc

        child_query = MagicMock()
        child_query.filter.return_value = child_query
        child_query.all.return_value = children

        db.query.side_effect = [tc_query, child_query]
        orch.execution_repo.db = db

        orch._patch_paused_subagents_tool_call(parent_run_id, session_id)

        result_data = json.loads(paused_tc.result)
        assert result_data["data"][0]["agent"] == "planner"

    def test_commits_after_patch(self):
        orch = _make_orchestrator()
        tc_id = uuid4()
        parent_run_id = uuid4()
        session_id = uuid4()

        paused_tc = _make_tool_call(tc_id=tc_id)

        children = [
            _make_sibling(status="completed"),
        ]

        db = MagicMock()

        tc_query = MagicMock()
        tc_query.filter.return_value = tc_query
        tc_query.order_by.return_value = tc_query
        tc_query.first.return_value = paused_tc

        child_query = MagicMock()
        child_query.filter.return_value = child_query
        child_query.all.return_value = children

        db.query.side_effect = [tc_query, child_query]
        orch.execution_repo.db = db

        orch._patch_paused_subagents_tool_call(parent_run_id, session_id)

        db.commit.assert_called_once()


class TestWalkParentChain:
    @pytest.mark.asyncio
    async def test_returns_true_when_no_parent(self):
        orch = _make_orchestrator()
        db = MagicMock()

        completed_run = MagicMock()
        completed_run.parent_run_id = None

        result = await orch._walk_parent_chain(uuid4(), completed_run, db)

        assert result is True

    @pytest.mark.asyncio
    async def test_returns_true_breaks_chain_when_parent_not_paused(self):
        orch = _make_orchestrator()
        db = MagicMock()

        completed_run = MagicMock()
        completed_run.parent_run_id = uuid4()
        completed_run.spawning_tool_call_id = uuid4()
        completed_run.id = uuid4()

        parent_run = MagicMock()
        parent_run.id = uuid4()
        parent_run.status = "running"
        parent_run.agent_id = "developer"

        orch.execution_repo.get_by_id.return_value = parent_run

        result = await orch._walk_parent_chain(uuid4(), completed_run, db)

        assert result is True
        orch.execution_repo.update_status.assert_not_called()

    @pytest.mark.asyncio
    async def test_returns_false_when_siblings_not_done(self):
        orch = _make_orchestrator()
        db = MagicMock()

        parent_run_id = uuid4()
        completed_run = MagicMock()
        completed_run.parent_run_id = parent_run_id
        completed_run.spawning_tool_call_id = uuid4()
        completed_run.id = uuid4()

        parent_run = MagicMock()
        parent_run.id = parent_run_id
        parent_run.status = "paused_hitl"
        parent_run.agent_id = "developer"

        orch.execution_repo.get_by_id.return_value = parent_run

        siblings = [
            _make_sibling(status="completed"),
            _make_sibling(status="running"),
        ]
        _, query_chain = _make_db_mock(siblings)
        orch.execution_repo.db = db
        db.query.return_value = query_chain

        result = await orch._walk_parent_chain(uuid4(), completed_run, db)

        assert result is False
        orch.execution_repo.update_status.assert_not_called()

    @pytest.mark.asyncio
    async def test_resumes_parent_when_all_siblings_done(self):
        orch = _make_orchestrator()
        db = MagicMock()

        parent_run_id = uuid4()
        session_id = uuid4()
        spawning_tc_id = uuid4()

        completed_run = MagicMock()
        completed_run.parent_run_id = parent_run_id
        completed_run.spawning_tool_call_id = spawning_tc_id
        completed_run.id = uuid4()

        parent_run = MagicMock()
        parent_run.id = parent_run_id
        parent_run.status = "paused_hitl"
        parent_run.agent_id = "developer"
        parent_run.parent_run_id = None

        orch.execution_repo.get_by_id.return_value = parent_run

        siblings = [
            _make_sibling(status="completed"),
        ]
        _, query_chain = _make_db_mock(siblings)
        orch.execution_repo.db = db


        tc_query = MagicMock()
        tc_query.filter.return_value = tc_query
        tc_query.order_by.return_value = tc_query
        tc_query.first.return_value = _make_tool_call(tc_id=spawning_tc_id)

        child_query = MagicMock()
        child_query.filter.return_value = child_query
        child_query.all.return_value = siblings

        db.query.side_effect = [query_chain, tc_query, child_query]

        with patch("druppie.agents.runtime_v2.AgentV2") as MockAgent:
            mock_agent_instance = MagicMock()
            mock_agent_instance.continue_run = AsyncMock(return_value={"status": "completed"})
            MockAgent.return_value = mock_agent_instance

            orch._handle_agent_resume_result = MagicMock(return_value="completed")

            result = await orch._walk_parent_chain(session_id, completed_run, db)

        assert result is True
        orch.execution_repo.update_status.assert_called_once()
        db.commit.assert_called()

    @pytest.mark.asyncio
    async def test_returns_false_when_parent_repauses(self):
        orch = _make_orchestrator()
        db = MagicMock()

        parent_run_id = uuid4()
        session_id = uuid4()
        spawning_tc_id = uuid4()

        completed_run = MagicMock()
        completed_run.parent_run_id = parent_run_id
        completed_run.spawning_tool_call_id = spawning_tc_id
        completed_run.id = uuid4()

        parent_run = MagicMock()
        parent_run.id = parent_run_id
        parent_run.status = "paused_hitl"
        parent_run.agent_id = "developer"
        parent_run.parent_run_id = None

        orch.execution_repo.get_by_id.return_value = parent_run

        siblings = [
            _make_sibling(status="completed"),
        ]
        _, query_chain = _make_db_mock(siblings)
        orch.execution_repo.db = db

        tc_query = MagicMock()
        tc_query.filter.return_value = tc_query
        tc_query.order_by.return_value = tc_query
        tc_query.first.return_value = _make_tool_call(tc_id=spawning_tc_id)

        child_query = MagicMock()
        child_query.filter.return_value = child_query
        child_query.all.return_value = siblings

        db.query.side_effect = [query_chain, tc_query, child_query]

        with patch("druppie.agents.runtime_v2.AgentV2") as MockAgent:
            mock_agent_instance = MagicMock()
            mock_agent_instance.continue_run = AsyncMock(return_value={"status": "paused_tool"})
            MockAgent.return_value = mock_agent_instance

            orch._handle_agent_resume_result = MagicMock(return_value="paused_tool")

            result = await orch._walk_parent_chain(session_id, completed_run, db)

        assert result is False

    @pytest.mark.asyncio
    async def test_stops_chain_when_parent_not_found(self):
        orch = _make_orchestrator()
        db = MagicMock()

        completed_run = MagicMock()
        completed_run.parent_run_id = uuid4()
        completed_run.spawning_tool_call_id = uuid4()
        completed_run.id = uuid4()

        orch.execution_repo.get_by_id.return_value = None

        result = await orch._walk_parent_chain(uuid4(), completed_run, db)

        assert result is True
