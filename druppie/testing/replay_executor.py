"""Replay executor — executes tool calls from YAML through the real pipeline.

In replay mode, tool calls defined in session YAML fixtures are executed
against real MCP servers (or the orchestrator for builtin tools) instead
of being inserted as static DB records.

The executor respects:
- Per-tool-call `execute` overrides (True/False)
- Global blocklist from replay_config.yaml
- Error handling strategy (mock/fail/skip)
"""
from __future__ import annotations

import logging
from uuid import UUID, uuid4

from sqlalchemy.orm import Session as DbSession

from druppie.db.models import AgentRun, Session, ToolCall
from druppie.db.models.base import utcnow
from druppie.testing.replay_config import ReplayConfig
from druppie.testing.seed_schema import AgentRunFixture, SessionFixture, ToolCallFixture

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

    async def execute_tool_call(
        self,
        tool_call: ToolCallFixture,
        session_id: UUID,
        agent_run_id: UUID,
        agent_id: str,
    ) -> str:
        """Execute a single tool call through the orchestrator, or return mock.

        For MCP tools, this calls the real MCP server via MCPHttp.
        For builtin tools, this calls the builtin handler.
        For blocklisted/mocked tools, returns the mock result.
        """
        if not self.should_execute(tool_call):
            logger.info(
                "Replay mock: %s (blocklisted or execute=false)", tool_call.tool
            )
            return self.get_mock_result(tool_call)

        try:
            # Create a ToolCall DB record so the executor has something to work with
            tc_record = ToolCall(
                id=uuid4(),
                agent_run_id=agent_run_id,
                mcp_server=tool_call.mcp_server,
                tool_name=tool_call.tool_name,
                arguments=tool_call.arguments,
                status="pending",
                created_at=utcnow(),
            )
            self._db.add(tc_record)
            self._db.flush()

            # Import here to avoid circular imports
            from druppie.core.mcp_config import MCPConfig
            from druppie.core.mcp_http import MCPHttp
            from druppie.execution.tool_executor import ToolExecutor

            mcp_config = MCPConfig()
            mcp_http = MCPHttp(mcp_config)
            executor = ToolExecutor(self._db, mcp_http, mcp_config)
            result_status = await executor.execute(tc_record.id)

            # Refresh to get updated result
            self._db.refresh(tc_record)
            result = tc_record.result or ""
            logger.info(
                "Replay executed: %s -> %s (%s)",
                tool_call.tool, result_status, result[:100],
            )
            return result

        except Exception as e:
            if self.config.on_error == "fail":
                raise
            elif self.config.on_error == "skip":
                logger.warning("Replay skip: %s error: %s", tool_call.tool, e)
                return ""
            else:  # "mock" (default)
                logger.warning(
                    "Replay mock (on_error): %s failed: %s", tool_call.tool, e
                )
                return self.get_mock_result(tool_call)

    async def replay_session(
        self,
        fixture: SessionFixture,
        user_id: UUID,
        gitea_url: str | None = None,
    ) -> dict:
        """Replay all tool calls in a session fixture.

        1. Create session + agent_run DB records
        2. Execute each tool call in order
        3. Return session info dict
        """
        from druppie.testing.seed_ids import fixture_uuid
        from druppie.testing.seed_loader import (
            _create_gitea_repo,
            _replay_outcome,
        )

        meta = fixture.metadata
        session_id = fixture_uuid(meta.id, str(user_id))

        # Create session record
        session = Session(
            id=session_id,
            user_id=user_id,
            title=meta.title,
            status=meta.status,
            intent=meta.intent,
            language=meta.language,
            created_at=utcnow(),
        )
        self._db.add(session)
        self._db.flush()

        # Create project if needed
        project_id = None
        if meta.project_name:
            from druppie.db.models import Project

            project_id = fixture_uuid(f"{meta.id}-project", str(user_id))
            repo_info = None
            if gitea_url:
                repo_info = _create_gitea_repo(meta.project_name, gitea_url)

            project = Project(
                id=project_id,
                name=meta.project_name,
                owner_id=user_id,
                description=f"Test project: {meta.title}",
                repo_name=repo_info["repo_name"] if repo_info else meta.project_name,
                repo_owner=repo_info["repo_owner"] if repo_info else "druppie_admin",
                repo_url=repo_info["repo_url"] if repo_info else None,
                clone_url=repo_info["clone_url"] if repo_info else None,
                created_at=utcnow(),
            )
            self._db.add(project)
            session.project_id = project_id
            self._db.flush()

        # Replay each agent's tool calls
        for seq, agent_fix in enumerate(fixture.agents):
            agent_run = AgentRun(
                id=fixture_uuid(f"{meta.id}-{agent_fix.id}", str(user_id)),
                session_id=session_id,
                agent_id=agent_fix.id,
                status=agent_fix.status,
                sequence_number=seq,
                error_message=agent_fix.error_message,
                planned_prompt=agent_fix.planned_prompt,
                created_at=utcnow(),
            )
            self._db.add(agent_run)
            self._db.flush()

            for tc in agent_fix.tool_calls:
                result = await self.execute_tool_call(
                    tc, session_id, agent_run.id, agent_fix.id,
                )
                # Update the tool call result if it was mocked
                if not self.should_execute(tc):
                    tc_record = ToolCall(
                        id=uuid4(),
                        agent_run_id=agent_run.id,
                        mcp_server=tc.mcp_server,
                        tool_name=tc.tool_name,
                        arguments=tc.arguments,
                        status=tc.status,
                        result=result,
                        error_message=tc.error_message,
                        created_at=utcnow(),
                    )
                    self._db.add(tc_record)
                    self._db.flush()

                # Handle outcome blocks (Gitea file creation)
                if tc.outcome and gitea_url:
                    _replay_outcome(tc.outcome, fixture, self._db, gitea_url)

        self._db.commit()
        return {
            "session_id": str(session_id),
            "project_id": str(project_id) if project_id else None,
        }
