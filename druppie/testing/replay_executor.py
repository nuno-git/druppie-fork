"""Replay executor — executes tool calls from YAML through the real pipeline.

In replay mode, tool calls defined in session YAML fixtures are executed
against real MCP servers and builtin tools, just like a real agent workflow.
The only difference: the tool calls come from YAML instead of an LLM deciding them.

This means:
- builtin:set_intent creates real projects + Gitea repos
- coding:list_dir actually lists files
- coding:make_design actually creates files
- Everything shows up in the session exactly like a real run

The executor respects:
- Per-tool-call `execute` overrides (True/False)
- Global blocklist from replay_config.yaml
- Error handling strategy (mock/fail/skip)
"""
from __future__ import annotations

import logging
from uuid import UUID, uuid4

from sqlalchemy.orm import Session as DbSession

from druppie.db.models import AgentRun, Message, Session, ToolCall
from druppie.db.models.base import utcnow
from druppie.testing.replay_config import ReplayConfig
from druppie.testing.seed_ids import fixture_uuid
from druppie.testing.seed_schema import SessionFixture, ToolCallFixture

logger = logging.getLogger(__name__)


class ReplayExecutor:
    """Executes tool calls from YAML through the real orchestrator pipeline."""

    def __init__(self, replay_config: ReplayConfig, db: DbSession):
        self.config = replay_config
        self._db = db

    def should_execute(self, tool_call: ToolCallFixture) -> bool:
        """Check per-call override > blocklist > default (execute)."""
        if tool_call.execute is not None:
            return tool_call.execute
        return tool_call.tool not in self.config.blocklist

    def get_mock_result(self, tool_call: ToolCallFixture) -> str:
        """Get mock result: YAML result > config default > generic."""
        if tool_call.result:
            return tool_call.result
        default = self.config.default_results.get(tool_call.tool)
        if default:
            return default
        return '{"status": "ok", "message": "mocked"}'

    async def _execute_real(
        self,
        tool_call: ToolCallFixture,
        session_id: UUID,
        agent_run_id: UUID,
    ) -> tuple[str, str]:
        """Execute a tool call through the real ToolExecutor.

        Returns (result_string, status_string).
        """
        # Create ToolCall DB record — ToolExecutor loads it by ID
        tc_record = ToolCall(
            id=uuid4(),
            session_id=session_id,
            agent_run_id=agent_run_id,
            mcp_server=tool_call.mcp_server,
            tool_name=tool_call.tool_name,
            arguments=tool_call.arguments,
            status="pending",
            created_at=utcnow(),
        )
        self._db.add(tc_record)
        self._db.flush()

        from druppie.core.mcp_config import MCPConfig
        from druppie.execution.mcp_http import MCPHttp
        from druppie.execution.tool_executor import ToolExecutor

        mcp_config = MCPConfig()
        mcp_http = MCPHttp(mcp_config)
        executor = ToolExecutor(self._db, mcp_http, mcp_config)
        result_status = await executor.execute(tc_record.id)

        # Refresh to get updated fields
        self._db.refresh(tc_record)
        return tc_record.result or "", result_status

    async def execute_tool_call(
        self,
        tool_call: ToolCallFixture,
        session_id: UUID,
        agent_run_id: UUID,
    ) -> tuple[str, str, bool]:
        """Execute a single tool call. Returns (result, status, was_real)."""

        if not self.should_execute(tool_call):
            mock_result = self.get_mock_result(tool_call)
            logger.info("Replay mock: %s", tool_call.tool)

            # Create a DB record for the mocked tool call
            tc_record = ToolCall(
                id=uuid4(),
                session_id=session_id,
                agent_run_id=agent_run_id,
                mcp_server=tool_call.mcp_server,
                tool_name=tool_call.tool_name,
                arguments=tool_call.arguments,
                status=tool_call.status or "completed",
                result=mock_result,
                error_message=tool_call.error_message,
                created_at=utcnow(),
            )
            self._db.add(tc_record)
            self._db.flush()
            return mock_result, "completed", False

        try:
            result, status = await self._execute_real(
                tool_call, session_id, agent_run_id,
            )
            logger.info("Replay executed: %s -> %s", tool_call.tool, status)
            return result, status, True

        except Exception as e:
            if self.config.on_error == "fail":
                raise
            elif self.config.on_error == "skip":
                logger.warning("Replay skip: %s error: %s", tool_call.tool, e)
                return "", "skipped", False
            else:  # "mock"
                logger.warning("Replay mock (on_error): %s failed: %s", tool_call.tool, e)
                mock_result = self.get_mock_result(tool_call)
                # Still create a DB record
                tc_record = ToolCall(
                    id=uuid4(),
                    session_id=session_id,
                    agent_run_id=agent_run_id,
                    mcp_server=tool_call.mcp_server,
                    tool_name=tool_call.tool_name,
                    arguments=tool_call.arguments,
                    status="failed",
                    result=mock_result,
                    error_message=str(e),
                    created_at=utcnow(),
                )
                self._db.add(tc_record)
                self._db.flush()
                return mock_result, "failed", False

    async def replay_session(
        self,
        fixture: SessionFixture,
        user_id: UUID,
        gitea_url: str | None = None,
    ) -> dict:
        """Replay all tool calls in a session fixture.

        Creates a bare session, then executes each tool call through the real
        pipeline. Side effects (project creation, Gitea repos, file writes)
        happen naturally through the tool calls — just like a real workflow.

        The session view will show every tool call and its result.
        """
        meta = fixture.metadata
        session_id = fixture_uuid(meta.id)

        # Create bare session — NO project, NO intent pre-set
        # These will be created by the tool calls (e.g. set_intent creates the project)
        session = Session(
            id=session_id,
            user_id=user_id,
            title=meta.title,
            status="active",  # Start as active, tools will update it
            language=meta.language,
            created_at=utcnow(),
        )
        self._db.add(session)
        self._db.flush()

        msg_seq = 0

        # Add fixture messages (user message first — this is what the "user said")
        for msg_fix in fixture.messages:
            self._db.add(Message(
                id=fixture_uuid(meta.id, "msg", msg_seq),
                session_id=session_id,
                role=msg_fix.role,
                content=msg_fix.content,
                agent_id=msg_fix.agent_id,
                sequence_number=msg_seq,
                created_at=utcnow(),
            ))
            msg_seq += 1
        self._db.flush()

        # Replay each agent's tool calls in order
        for seq, agent_fix in enumerate(fixture.agents):
            agent_run = AgentRun(
                id=fixture_uuid(meta.id, "run", seq),
                session_id=session_id,
                agent_id=agent_fix.id,
                status="running",  # Start as running
                sequence_number=seq,
                planned_prompt=agent_fix.planned_prompt,
                created_at=utcnow(),
            )
            self._db.add(agent_run)
            self._db.flush()

            for tc in agent_fix.tool_calls:
                result, status, was_real = await self.execute_tool_call(
                    tc, session_id, agent_run.id,
                )

                # Create a message so it shows in the session timeline
                result_preview = (result or "")[:500]
                label = "executed" if was_real else "mocked"
                self._db.add(Message(
                    id=fixture_uuid(meta.id, "msg", msg_seq),
                    session_id=session_id,
                    agent_run_id=agent_run.id,
                    role="tool",
                    content=f"[{label}] **{tc.tool}**({', '.join(f'{k}={v}' for k, v in tc.arguments.items())})\n\n→ {result_preview}",
                    agent_id=agent_fix.id,
                    tool_name=tc.tool,
                    sequence_number=msg_seq,
                    created_at=utcnow(),
                ))
                msg_seq += 1

                # Handle outcome blocks (file creation in Gitea)
                if tc.outcome and gitea_url:
                    from druppie.testing.seed_loader import _replay_outcome
                    _replay_outcome(tc.outcome, fixture, self._db, gitea_url)

            # Update agent run status
            agent_run.status = agent_fix.status
            self._db.flush()

            # Summary message
            executed_count = sum(1 for tc in agent_fix.tool_calls if self.should_execute(tc))
            mocked_count = len(agent_fix.tool_calls) - executed_count
            self._db.add(Message(
                id=fixture_uuid(meta.id, "msg", msg_seq),
                session_id=session_id,
                agent_run_id=agent_run.id,
                role="assistant",
                content=f"Agent **{agent_fix.id}** completed — {executed_count} tool calls executed, {mocked_count} mocked",
                agent_id=agent_fix.id,
                sequence_number=msg_seq,
                created_at=utcnow(),
            ))
            msg_seq += 1

        # Update session status to match fixture
        session.status = meta.status
        self._db.flush()

        # Get project_id if one was created by set_intent
        self._db.refresh(session)
        project_id = session.project_id

        return {
            "session_id": str(session_id),
            "project_id": str(project_id) if project_id else None,
        }
