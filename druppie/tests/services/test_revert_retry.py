"""Tests for RevertService.retry_nested_subagent_run.

Verifies the retry behavior for nested subagent runs:
- Later siblings are DELETED (not reset to PENDING)
- Descendants of target and siblings are recursively cleaned up
- Parent chain is properly reset (done() TC deleted, subagents() TC cleared)
- Deeply nested subsubagents work correctly
"""

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4, UUID

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
    run.created_at = datetime.now(timezone.utc)
    return run


def _make_revert_service(execution_repo=None, session_repo=None, mcp_http=None):
    execution_repo = execution_repo or MagicMock()
    session_repo = session_repo or MagicMock()
    mcp_http = mcp_http or AsyncMock()
    return RevertService(execution_repo, session_repo, mcp_http)


def _patch_no_parent_chain(svc):
    """Patch _reset_parent_chain_for_retry as a no-op (for tests not testing it)."""
    return patch.object(svc, "_reset_parent_chain_for_retry")


class TestRetryDeletesLaterSiblings:
    """BUG: Retry first of 3 subagents -> later 2 should be DELETED, not PENDING."""

    @pytest.mark.asyncio
    async def test_later_siblings_are_deleted_not_reset(self):
        parent_run_id = uuid4()
        session_id = uuid4()

        target = _make_run(parent_run_id=parent_run_id, agent_id="test_builder")
        sibling_2 = _make_run(parent_run_id=parent_run_id, agent_id="developer")
        sibling_3 = _make_run(parent_run_id=parent_run_id, agent_id="test_executor")

        repo = MagicMock()
        repo.get_by_id_for_session.return_value = target
        repo.get_children_after.return_value = [sibling_2, sibling_3]
        repo.db = MagicMock()

        svc = _make_revert_service(execution_repo=repo)

        with patch.object(svc, "_collect_descendants", return_value=[]), \
             _patch_no_parent_chain(svc):
            await svc.retry_nested_subagent_run(session_id, target.id, planned_prompt="New prompt")

        delete_calls = repo.delete_runs_fully.call_args_list
        deleted_ids = set()
        for call in delete_calls:
            for run_id in call[0][0]:
                deleted_ids.add(run_id)

        assert sibling_2.id in deleted_ids
        assert sibling_3.id in deleted_ids
        assert target.id not in deleted_ids

    @pytest.mark.asyncio
    async def test_only_target_is_reset_to_pending(self):
        parent_run_id = uuid4()
        target = _make_run(parent_run_id=parent_run_id, agent_id="test_builder")
        sibling = _make_run(parent_run_id=parent_run_id, agent_id="developer")

        repo = MagicMock()
        repo.get_by_id_for_session.return_value = target
        repo.get_children_after.return_value = [sibling]
        repo.db = MagicMock()

        svc = _make_revert_service(execution_repo=repo)

        with patch.object(svc, "_collect_descendants", return_value=[]), \
             _patch_no_parent_chain(svc):
            await svc.retry_nested_subagent_run(uuid4(), target.id)

        repo.reset_runs_to_pending.assert_called_once_with([target.id])

    @pytest.mark.asyncio
    async def test_clear_artifacts_only_for_target(self):
        parent_run_id = uuid4()
        target = _make_run(parent_run_id=parent_run_id, agent_id="test_builder")
        sibling = _make_run(parent_run_id=parent_run_id, agent_id="developer")

        repo = MagicMock()
        repo.get_by_id_for_session.return_value = target
        repo.get_children_after.return_value = [sibling]
        repo.db = MagicMock()

        svc = _make_revert_service(execution_repo=repo)

        with patch.object(svc, "_collect_descendants", return_value=[]), \
             _patch_no_parent_chain(svc):
            await svc.retry_nested_subagent_run(uuid4(), target.id)

        repo.clear_execution_artifacts.assert_called_once_with([target.id])


class TestRetryRecursiveDescendantCleanup:
    @pytest.mark.asyncio
    async def test_descendants_of_target_are_deleted(self):
        parent_run_id = uuid4()
        session_id = uuid4()
        target = _make_run(parent_run_id=parent_run_id, agent_id="dev_orchestrator")
        grandchild = _make_run(parent_run_id=target.id, agent_id="core_builder")

        repo = MagicMock()
        repo.get_by_id_for_session.return_value = target
        repo.get_children_after.return_value = []
        repo.db = MagicMock()

        svc = _make_revert_service(execution_repo=repo)

        with patch.object(svc, "_collect_descendants", return_value=[grandchild.id]), \
             _patch_no_parent_chain(svc):
            await svc.retry_nested_subagent_run(session_id, target.id)

        delete_calls = repo.delete_runs_fully.call_args_list
        deleted_ids = set()
        for call in delete_calls:
            for run_id in call[0][0]:
                deleted_ids.add(run_id)

        assert grandchild.id in deleted_ids

    @pytest.mark.asyncio
    async def test_descendants_of_later_siblings_are_deleted(self):
        parent_run_id = uuid4()
        session_id = uuid4()
        target = _make_run(parent_run_id=parent_run_id, agent_id="test_builder")
        sibling = _make_run(parent_run_id=parent_run_id, agent_id="developer")
        niece = _make_run(parent_run_id=sibling.id, agent_id="core_builder")

        repo = MagicMock()
        repo.get_by_id_for_session.return_value = target
        repo.get_children_after.return_value = [sibling]
        repo.db = MagicMock()

        svc = _make_revert_service(execution_repo=repo)

        def collect_descendants(run_id):
            if run_id == sibling.id:
                return [niece.id]
            return []

        with patch.object(svc, "_collect_descendants", side_effect=collect_descendants), \
             _patch_no_parent_chain(svc):
            await svc.retry_nested_subagent_run(session_id, target.id)

        delete_calls = repo.delete_runs_fully.call_args_list
        deleted_ids = set()
        for call in delete_calls:
            for run_id in call[0][0]:
                deleted_ids.add(run_id)

        assert niece.id in deleted_ids
        assert sibling.id in deleted_ids


class TestRetryParentChainReset:
    @pytest.mark.asyncio
    async def test_parent_done_toolcall_deleted(self):
        parent_run_id = uuid4()
        target = _make_run(parent_run_id=parent_run_id, agent_id="test_builder")

        parent_run = MagicMock()
        parent_run.id = parent_run_id
        parent_run.status = "completed"
        parent_run.parent_run_id = None
        parent_run.agent_id = "dev_orchestrator"

        subagents_tc = MagicMock()
        subagents_tc.id = uuid4()
        subagents_tc.tool_name = "subagents"
        subagents_tc.status = "completed"
        subagents_tc.result = '{"success": true}'
        subagents_tc.agent_run_id = parent_run_id

        repo = MagicMock()
        repo.get_by_id_for_session.return_value = target
        repo.get_children_after.return_value = []
        repo.db = MagicMock()

        from druppie.db.models.agent_run import AgentRun as AgentRunModel
        from druppie.db.models.tool_call import ToolCall as ToolCallModel

        run_query = MagicMock()
        run_query.filter.return_value = run_query
        run_query.first.return_value = parent_run

        tc_query_all = MagicMock()
        tc_query_all.filter.return_value = tc_query_all
        tc_query_all.delete.return_value = None

        tc_query_sub = MagicMock()
        tc_query_sub.filter.return_value = tc_query_sub
        tc_query_sub.order_by.return_value = tc_query_sub
        tc_query_sub.first.return_value = subagents_tc

        repo.db.query.side_effect = [run_query, tc_query_all, tc_query_sub]

        svc = _make_revert_service(execution_repo=repo)

        with patch.object(svc, "_collect_descendants", return_value=[]):
            await svc.retry_nested_subagent_run(uuid4(), target.id)

        assert subagents_tc.result is None
        assert subagents_tc.status == "executing"

    @pytest.mark.asyncio
    async def test_parent_status_reset_to_running(self):
        parent_run_id = uuid4()
        target = _make_run(parent_run_id=parent_run_id, agent_id="test_builder")

        parent_run = MagicMock()
        parent_run.id = parent_run_id
        parent_run.status = "completed"
        parent_run.completed_at = datetime.now(timezone.utc)
        parent_run.parent_run_id = None
        parent_run.agent_id = "dev_orchestrator"

        repo = MagicMock()
        repo.get_by_id_for_session.return_value = target
        repo.get_children_after.return_value = []
        repo.db = MagicMock()

        run_query = MagicMock()
        run_query.filter.return_value = run_query
        run_query.first.return_value = parent_run

        tc_query = MagicMock()
        tc_query.filter.return_value = tc_query
        tc_query.delete.return_value = None
        tc_query.order_by.return_value = tc_query
        tc_query.first.return_value = None

        repo.db.query.side_effect = [run_query, tc_query, tc_query]

        svc = _make_revert_service(execution_repo=repo)

        with patch.object(svc, "_collect_descendants", return_value=[]):
            await svc.retry_nested_subagent_run(uuid4(), target.id)

        assert parent_run.status == AgentRunStatus.RUNNING.value
        assert parent_run.completed_at is None


class TestRetryDeeplyNested:
    @pytest.mark.asyncio
    async def test_retry_subsubagent_resets_grandparent(self):
        """
        Tree: grandparent -> parent -> target

        Retrying target must reset parent AND grandparent to RUNNING.
        """
        session_id = uuid4()
        grandparent_id = uuid4()
        parent_id = uuid4()
        target_id = uuid4()

        target = _make_run(
            run_id=target_id, parent_run_id=parent_id, agent_id="core_builder",
            planned_prompt="Do the thing",
        )

        parent_run = MagicMock()
        parent_run.id = parent_id
        parent_run.status = "completed"
        parent_run.completed_at = datetime.now(timezone.utc)
        parent_run.parent_run_id = grandparent_id
        parent_run.agent_id = "dev_orchestrator"

        grandparent_run = MagicMock()
        grandparent_run.id = grandparent_id
        grandparent_run.status = "completed"
        grandparent_run.completed_at = datetime.now(timezone.utc)
        grandparent_run.parent_run_id = None
        grandparent_run.agent_id = "planner"

        repo = MagicMock()
        repo.get_by_id_for_session.return_value = target
        repo.get_children_after.return_value = []
        repo.db = MagicMock()

        # db.query is called multiple times in _reset_parent_chain_for_retry:
        # Iteration 1 (parent): query(AgentRun) -> parent, query(ToolCall) delete, query(ToolCall) subagents
        # Iteration 2 (grandparent): query(AgentRun) -> grandparent, query(ToolCall) delete, query(ToolCall) subagents
        # We need to provide 6 query results: [parent_run, tc_del_1, tc_sub_1, grandparent, tc_del_2, tc_sub_2]

        run_q1 = MagicMock()
        run_q1.filter.return_value = run_q1
        run_q1.first.return_value = parent_run

        tc_del = MagicMock()
        tc_del.filter.return_value = tc_del
        tc_del.delete.return_value = None

        tc_sub_1 = MagicMock()
        tc_sub_1.filter.return_value = tc_sub_1
        tc_sub_1.order_by.return_value = tc_sub_1
        tc_sub_1.first.return_value = None

        run_q2 = MagicMock()
        run_q2.filter.return_value = run_q2
        run_q2.first.return_value = grandparent_run

        tc_sub_2 = MagicMock()
        tc_sub_2.filter.return_value = tc_sub_2
        tc_sub_2.order_by.return_value = tc_sub_2
        tc_sub_2.first.return_value = None

        repo.db.query.side_effect = [run_q1, tc_del, tc_sub_1, run_q2, tc_del, tc_sub_2]

        svc = _make_revert_service(execution_repo=repo)

        with patch.object(svc, "_collect_descendants", return_value=[]):
            await svc.retry_nested_subagent_run(session_id, target_id)

        assert parent_run.status == AgentRunStatus.RUNNING.value
        assert grandparent_run.status == AgentRunStatus.RUNNING.value
        assert parent_run.completed_at is None
        assert grandparent_run.completed_at is None


class TestRetryPlannedPrompt:
    @pytest.mark.asyncio
    async def test_edited_prompt_applied_to_target(self):
        parent_run_id = uuid4()
        target = _make_run(parent_run_id=parent_run_id, agent_id="test_builder")

        repo = MagicMock()
        repo.get_by_id_for_session.return_value = target
        repo.get_children_after.return_value = []
        repo.db = MagicMock()

        svc = _make_revert_service(execution_repo=repo)

        with patch.object(svc, "_collect_descendants", return_value=[]), \
             _patch_no_parent_chain(svc):
            await svc.retry_nested_subagent_run(
                uuid4(), target.id, planned_prompt="Updated prompt"
            )

        repo.update_planned_prompt.assert_called_once_with(target.id, "Updated prompt")

    @pytest.mark.asyncio
    async def test_prompt_extracted_from_toolcall_when_empty(self):
        parent_run_id = uuid4()
        spawning_tc_id = uuid4()
        target = _make_run(
            parent_run_id=parent_run_id,
            agent_id="test_builder",
            spawning_tool_call_id=spawning_tc_id,
            planned_prompt="",
        )

        repo = MagicMock()
        repo.get_by_id_for_session.return_value = target
        repo.get_children_after.return_value = []
        repo.db = MagicMock()

        svc = _make_revert_service(execution_repo=repo)

        with patch.object(svc, "_collect_descendants", return_value=[]), \
             patch.object(svc, "_extract_subagent_prompt", return_value="Extracted prompt"), \
             _patch_no_parent_chain(svc):
            await svc.retry_nested_subagent_run(uuid4(), target.id)

        repo.update_planned_prompt.assert_called_once_with(target.id, "Extracted prompt")

    @pytest.mark.asyncio
    async def test_existing_prompt_preserved_when_not_empty(self):
        parent_run_id = uuid4()
        target = _make_run(
            parent_run_id=parent_run_id,
            agent_id="test_builder",
            planned_prompt="Original prompt",
        )

        repo = MagicMock()
        repo.get_by_id_for_session.return_value = target
        repo.get_children_after.return_value = []
        repo.db = MagicMock()

        svc = _make_revert_service(execution_repo=repo)

        with patch.object(svc, "_collect_descendants", return_value=[]), \
             _patch_no_parent_chain(svc):
            await svc.retry_nested_subagent_run(uuid4(), target.id)

        repo.update_planned_prompt.assert_not_called()


class TestCollectDescendants:
    def test_no_children_returns_empty(self):
        svc = _make_revert_service()
        svc.execution_repo.db = MagicMock()

        chain = MagicMock()
        chain.filter.return_value = chain
        chain.all.return_value = []
        svc.execution_repo.db.query.return_value = chain

        result = svc._collect_descendants(uuid4())
        assert result == []

    def test_collects_direct_children(self):
        svc = _make_revert_service()
        svc.execution_repo.db = MagicMock()

        child1 = MagicMock()
        child1.id = uuid4()
        child1.parent_run_id = uuid4()
        child2 = MagicMock()
        child2.id = uuid4()
        child2.parent_run_id = uuid4()

        call_count = [0]

        def filter_side_effect(*args, **kwargs):
            result_chain = MagicMock()
            result_chain.order_by.return_value = result_chain
            call_count[0] += 1
            if call_count[0] == 1:
                result_chain.all.return_value = [child1, child2]
            else:
                result_chain.all.return_value = []
            return result_chain

        chain = MagicMock()
        chain.filter.side_effect = filter_side_effect
        svc.execution_repo.db.query.return_value = chain

        result = svc._collect_descendants(uuid4())
        assert child1.id in result
        assert child2.id in result

    def test_collects_grandchildren(self):
        svc = _make_revert_service()
        svc.execution_repo.db = MagicMock()

        child = MagicMock()
        child.id = uuid4()
        child.parent_run_id = uuid4()
        grandchild = MagicMock()
        grandchild.id = uuid4()
        grandchild.parent_run_id = uuid4()

        call_count = [0]

        def filter_side_effect(*args, **kwargs):
            result_chain = MagicMock()
            result_chain.order_by.return_value = result_chain
            call_count[0] += 1
            if call_count[0] == 1:
                result_chain.all.return_value = [child]
            elif call_count[0] == 2:
                result_chain.all.return_value = [grandchild]
            else:
                result_chain.all.return_value = []
            return result_chain

        chain = MagicMock()
        chain.filter.side_effect = filter_side_effect
        svc.execution_repo.db.query.return_value = chain

        result = svc._collect_descendants(uuid4())
        assert child.id in result
        assert grandchild.id in result
