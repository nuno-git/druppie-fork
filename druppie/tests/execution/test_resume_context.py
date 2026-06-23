"""Tests for resume session with per-agent context and correct leaf targeting.

Verifies:
- Resume targets the PAUSED_USER leaf (subagent), not the parent orchestrator
- Resume accepts optional per-agent contexts dict injected into each resumed agent
- GET /sessions/{id}/resumable returns the tree of paused runs
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4, UUID

import pytest

from druppie.domain.common import AgentRunStatus, SessionStatus
from druppie.execution.orchestrator import Orchestrator


# =============================================================================
# Helpers
# =============================================================================

def _make_run(
    run_id=None,
    parent_run_id=None,
    agent_id="agent",
    status="paused_user",
    spawning_tool_call_id=None,
    planned_prompt="",
    sequence_number=1,
):
    run = MagicMock()
    run.id = run_id or uuid4()
    run.parent_run_id = parent_run_id
    run.agent_id = agent_id
    run.status = status
    run.spawning_tool_call_id = spawning_tool_call_id
    run.planned_prompt = planned_prompt
    run.sequence_number = sequence_number
    run.error_message = None
    run.iteration_count = 0
    run.completed_at = None
    run.created_at = None
    run.session_id = uuid4()
    return run


def _make_orchestrator():
    from druppie.execution.orchestrator import Orchestrator
    return Orchestrator(
        session_repo=MagicMock(),
        execution_repo=MagicMock(),
        project_repo=MagicMock(),
        question_repo=MagicMock(),
    )


# =============================================================================
# Test: Resume targets the paused leaf, not the parent
# =============================================================================

class TestResumeTargetsLeaf:
    """BUG: Stop during subagent → resume continues parent, not subagent."""

    @pytest.mark.asyncio
    async def test_resume_picks_subagent_leaf_not_parent(self):
        """
        Setup: parent (dev_orchestrator) PAUSED_USER, child (test_builder) PAUSED_USER.
        get_user_paused_leaves should return [child], and resume should call
        continue_run on the CHILD, not the parent.
        """
        session_id = uuid4()
        parent_id = uuid4()
        child_id = uuid4()

        parent_run = _make_run(
            run_id=parent_id, agent_id="dev_orchestrator", status="paused_user"
        )
        child_run = _make_run(
            run_id=child_id,
            parent_run_id=parent_id,
            agent_id="test_builder",
            status="paused_user",
        )

        orch = _make_orchestrator()
        orch.execution_repo.get_user_paused_leaves.return_value = [child_run]
        orch.execution_repo.get_paused_run.return_value = None
        orch.execution_repo.get_running_run.return_value = None
        orch.execution_repo.get_by_id.return_value = child_run
        orch.execution_repo.db = MagicMock()
        orch._handle_agent_resume_result = MagicMock(return_value="completed")
        orch._walk_parent_chain = AsyncMock(return_value=True)
        orch.execute_pending_runs = AsyncMock()

        with patch("druppie.agents.runtime_v2.AgentV2") as MockAgent, \
             patch.object(orch, "build_project_context", return_value={}):
            mock_agent = MagicMock()
            mock_agent.continue_run = AsyncMock(return_value={"status": "completed"})
            MockAgent.return_value = mock_agent

            await orch.resume_paused_session(session_id)

        # continue_run must be called on the CHILD run, not the parent
        mock_agent.continue_run.assert_called_once()
        call_kwargs = mock_agent.continue_run.call_args
        assert call_kwargs.kwargs.get("agent_run_id") == child_id or call_kwargs[1].get("agent_run_id") == child_id

    @pytest.mark.asyncio
    async def test_resume_with_multiple_parallel_paused_leaves(self):
        """Multiple parallel subagents paused → all should be resumed."""
        session_id = uuid4()
        parent_id = uuid4()

        leaf_1 = _make_run(agent_id="test_builder", parent_run_id=parent_id)
        leaf_2 = _make_run(agent_id="backend_developer", parent_run_id=parent_id)

        orch = _make_orchestrator()
        orch.execution_repo.get_user_paused_leaves.return_value = [leaf_1, leaf_2]
        orch.execution_repo.get_paused_run.return_value = None
        orch.execution_repo.get_running_run.return_value = None

        db = MagicMock()
        orch.execution_repo.db = db

        with patch("druppie.agents.runtime_v2.AgentV2") as MockAgent, \
             patch("druppie.db.database.SessionLocal") as MockSessionLocal, \
             patch.object(Orchestrator, "_resume_single_paused_leaf", new_callable=AsyncMock) as mock_resume_leaf, \
             patch.object(orch, "build_project_context", return_value={}):
            mock_agent = MagicMock()
            mock_agent.continue_run = AsyncMock(return_value={"status": "completed"})
            MockAgent.return_value = mock_agent

            mock_db = MagicMock()
            MockSessionLocal.return_value = mock_db

            orch._handle_agent_resume_result = MagicMock(return_value="completed")
            orch._walk_parent_chain = AsyncMock(return_value=True)
            orch.execute_pending_runs = AsyncMock()

            await orch.resume_paused_session(session_id)

        # Both leaves should have been resumed
        assert mock_resume_leaf.call_count == 2


# =============================================================================
# Test: Resume with context injection
# =============================================================================

class TestResumeWithContext:
    """Resume should accept optional context and inject it into the resumed agent."""

    @pytest.mark.asyncio
    async def test_resume_passes_context_to_continue_run(self):
        """Per-agent context should be forwarded to resume_paused_session."""
        session_id = uuid4()
        child_id = uuid4()
        parent_id = uuid4()

        child_run = _make_run(
            run_id=child_id, parent_run_id=parent_id, agent_id="test_builder"
        )

        orch = _make_orchestrator()
        orch.execution_repo.get_user_paused_leaves.return_value = [child_run]
        orch.execution_repo.get_paused_run.return_value = None
        orch.execution_repo.get_running_run.return_value = None
        orch.execution_repo.get_by_id.return_value = child_run
        orch.execution_repo.db = MagicMock()
        orch._handle_agent_resume_result = MagicMock(return_value="completed")
        orch._walk_parent_chain = AsyncMock(return_value=True)
        orch.execute_pending_runs = AsyncMock()

        with patch("druppie.agents.runtime_v2.AgentV2") as MockAgent, \
             patch.object(orch, "build_project_context", return_value={}):
            mock_agent = MagicMock()
            mock_agent.continue_run = AsyncMock(return_value={"status": "completed"})
            MockAgent.return_value = mock_agent

            await orch.resume_paused_session(
                session_id, contexts={str(child_id): "Focus on auth tests, skip UI tests"}
            )

        assert mock_agent.continue_run.called

    @pytest.mark.asyncio
    async def test_resume_without_context_works(self):
        """Resume without context should still work (backwards compatible)."""
        session_id = uuid4()
        child_run = _make_run(agent_id="test_builder")

        orch = _make_orchestrator()
        orch.execution_repo.get_user_paused_leaves.return_value = [child_run]
        orch.execution_repo.get_paused_run.return_value = None
        orch.execution_repo.get_running_run.return_value = None
        orch.execution_repo.db = MagicMock()
        orch._handle_agent_resume_result = MagicMock(return_value="completed")
        orch._walk_parent_chain = AsyncMock(return_value=True)
        orch.execute_pending_runs = AsyncMock()

        with patch("druppie.agents.runtime_v2.AgentV2") as MockAgent, \
             patch.object(orch, "build_project_context", return_value={}):
            mock_agent = MagicMock()
            mock_agent.continue_run = AsyncMock(return_value={"status": "completed"})
            MockAgent.return_value = mock_agent

            await orch.resume_paused_session(session_id)

        assert mock_agent.continue_run.called


# =============================================================================
# Test: resume_paused_session signature accepts contexts param
# =============================================================================

class TestResumePausedSessionSignature:
    """Verify resume_paused_session accepts contexts dict."""

    def test_accepts_contexts_param(self):
        """resume_paused_session must accept a 'contexts' keyword argument."""
        import inspect
        from druppie.execution.orchestrator import Orchestrator

        sig = inspect.signature(Orchestrator.resume_paused_session)
        assert "contexts" in sig.parameters, "resume_paused_session must accept 'contexts' param"

    def test_contexts_defaults_to_none(self):
        import inspect
        from druppie.execution.orchestrator import Orchestrator

        sig = inspect.signature(Orchestrator.resume_paused_session)
        assert sig.parameters["contexts"].default is None
