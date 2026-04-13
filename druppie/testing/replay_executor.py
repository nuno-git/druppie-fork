"""Replay executor — executes tool calls from YAML through the real pipeline.

In replay mode, tool calls defined in session YAML fixtures are executed
against real MCP servers and builtin tools, just like a real agent workflow.
The only difference: the tool calls come from YAML instead of an LLM deciding them.

This means:
- builtin:set_intent creates real projects + Gitea repos
- coding:list_dir actually lists files
- coding:make_design actually creates files
- Everything shows up in the session exactly like a real run

Mocking is controlled per-step in the test YAML via `mock: true` + `mock_result`.
There is no global blocklist — each test decides what to mock.
"""
from __future__ import annotations

import logging
from uuid import UUID, uuid4

from sqlalchemy.orm import Session as DbSession

from druppie.db.models import AgentRun, LlmCall, Message, Session, ToolCall
from druppie.db.models.base import utcnow
from druppie.testing.seed_ids import fixture_uuid
from druppie.testing.seed_schema import SessionFixture, ToolCallFixture

logger = logging.getLogger(__name__)


class ReplayExecutor:
    """Executes tool calls from YAML through the real orchestrator pipeline."""

    def __init__(self, db: DbSession):
        self._db = db
        self._executor = None  # Cached ToolExecutor

    def _get_executor(self):
        """Get or create cached ToolExecutor."""
        if self._executor is None:
            from druppie.core.mcp_config import MCPConfig
            from druppie.execution.mcp_http import MCPHttp
            from druppie.execution.tool_executor import ToolExecutor

            mcp_config = MCPConfig()
            mcp_http = MCPHttp(mcp_config)
            self._executor = ToolExecutor(self._db, mcp_http, mcp_config)
        return self._executor

    def should_execute(self, tool_call: ToolCallFixture) -> bool:
        """Execute by default. Mock only when `mock: true` (execute=False)."""
        if tool_call.execute is not None:
            return tool_call.execute
        return True

    def get_mock_result(self, tool_call: ToolCallFixture) -> str:
        """Get mock result from YAML."""
        if tool_call.result:
            return tool_call.result
        return '{"status": "ok", "message": "mocked"}'

    async def _execute_real(
        self,
        tool_call: ToolCallFixture,
        session_id: UUID,
        agent_run_id: UUID,
        approval_action: dict | None = None,
    ) -> tuple[str, str]:
        """Execute a tool call through the real ToolExecutor.

        If the tool requires approval and approval_action is provided,
        it will be auto-approved/rejected after the approval gate.

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

        executor = self._get_executor()
        result_status = await executor.execute(tc_record.id)

        # Handle approval gate
        if result_status == "waiting_approval":
            result_status = await self._handle_approval(
                tc_record, approval_action,
            )

        # Refresh to get updated fields
        self._db.refresh(tc_record)
        return tc_record.result or "", result_status

    async def _handle_approval(
        self,
        tc_record: ToolCall,
        approval_action: dict | None,
    ) -> str:
        """Handle an approval gate during replay.

        If approval_action specifies approved/rejected, resolve the approval
        and continue (or stop) execution accordingly.
        """
        from druppie.db.models import Approval

        # Find the pending approval for this tool call
        approval = (
            self._db.query(Approval)
            .filter(
                Approval.tool_call_id == tc_record.id,
                Approval.status == "pending",
            )
            .first()
        )

        if not approval:
            logger.warning("No pending approval found for tool call %s", tc_record.id)
            return "waiting_approval"

        action = approval_action or {}
        status = action.get("status", "approved")

        if status == "rejected":
            # Reject the approval
            approval.status = "rejected"
            approval.rejection_reason = action.get("reason", "Rejected by test")
            approval.resolved_at = utcnow()
            self._db.flush()
            self._db.commit()

            # Let executor handle the rejection
            executor = self._get_executor()
            result_status = await executor.execute_after_approval(approval.id)
            return result_status
        else:
            # Approve and continue execution
            # Find or create the approving user
            from druppie.db.models import User
            approver_name = action.get("by")
            if approver_name:
                approver = self._db.query(User).filter(User.username == approver_name).first()
                approval.resolved_by = approver.id if approver else None
            else:
                # Use session owner as approver
                from druppie.db.models import Session as SessionModel
                session = self._db.query(SessionModel).filter(SessionModel.id == tc_record.session_id).first()
                approval.resolved_by = session.user_id if session else None

            approval.status = "approved"
            approval.resolved_at = utcnow()
            self._db.flush()
            self._db.commit()

            # Continue execution after approval
            executor = self._get_executor()
            result_status = await executor.execute_after_approval(approval.id)
            return result_status

    async def execute_tool_call(
        self,
        tool_call: ToolCallFixture,
        session_id: UUID,
        agent_run_id: UUID,
        approval_action: dict | None = None,
    ) -> tuple[str, str, bool]:
        """Execute a single tool call. Returns (result, status, was_real).

        approval_action: if the tool needs approval, how to resolve it.
            {"status": "approved", "by": "architect"} or {"status": "rejected", "reason": "..."}
        """

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
                approval_action=approval_action,
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
        # Force the Gitea singleton to create a fresh AsyncClient bound to
        # the current event loop (test thread uses its own loop)
        import druppie.core.gitea as _gitea_mod
        gitea_client = _gitea_mod.get_gitea_client()
        gitea_client._client = None

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
        self._db.commit()

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
        self._db.commit()

        # Replay each agent's tool calls in order
        for seq, agent_fix in enumerate(fixture.agents):
            agent_run = AgentRun(
                id=fixture_uuid(meta.id, "run", seq),
                session_id=session_id,
                agent_id=agent_fix.id,
                status="running",
                sequence_number=seq,
                planned_prompt=agent_fix.planned_prompt,
                created_at=utcnow(),
            )
            self._db.add(agent_run)
            self._db.flush()

            # Create a fake LlmCall so tool calls show in inspect view
            # (the frontend expects ToolCalls nested under LlmCalls)
            llm_call = LlmCall(
                id=fixture_uuid(meta.id, "run", seq, "llm"),
                session_id=session_id,
                agent_run_id=agent_run.id,
                provider="replay",
                model="replay",
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
                duration_ms=0,
                response_tool_calls=[
                    {"name": tc.tool, "arguments": tc.arguments}
                    for tc in agent_fix.tool_calls
                ],
                created_at=utcnow(),
            )
            self._db.add(llm_call)
            self._db.flush()

            for tc_idx, tc in enumerate(agent_fix.tool_calls):
                result, status, was_real = await self.execute_tool_call(
                    tc, session_id, agent_run.id,
                    approval_action=tc.approval_action,
                )

                # Link the ToolCall record to the fake LlmCall
                # (ToolExecutor creates the record; we update it after)
                tc_records = (
                    self._db.query(ToolCall)
                    .filter(
                        ToolCall.agent_run_id == agent_run.id,
                        ToolCall.mcp_server == tc.mcp_server,
                        ToolCall.tool_name == tc.tool_name,
                    )
                    .order_by(ToolCall.created_at.desc())
                    .all()
                )
                if tc_records:
                    tc_records[0].llm_call_id = llm_call.id
                    tc_records[0].tool_call_index = tc_idx

                # Commit after each tool call to release DB locks
                # so API requests aren't blocked during the test
                self._db.commit()

                # Handle outcome blocks (file creation in Gitea for execute_coding_task)
                if tc.outcome and gitea_url:
                    self._create_outcome_files(tc.outcome, gitea_url, session_id)

            # Update agent run status
            agent_run.status = agent_fix.status
            self._db.commit()

        # Update session status to match fixture
        session.status = meta.status
        self._db.commit()

        # Get project_id if one was created by set_intent
        self._db.refresh(session)
        project_id = session.project_id

        return {
            "session_id": str(session_id),
            "project_id": str(project_id) if project_id else None,
        }

    def _create_outcome_files(
        self,
        outcome: dict,
        gitea_url: str,
        session_id: UUID,
    ) -> None:
        """Create files in Gitea for execute_coding_task outcomes.

        The outcome dict has: files (list of {path, content}),
        optional commit_message, optional branch.
        """
        import base64
        import os

        import httpx

        from druppie.db.models import Session as SessionModel

        files = outcome.get("files", [])
        if not files:
            return

        # Find the repo from the session's project
        session = self._db.query(SessionModel).filter(SessionModel.id == session_id).first()
        if not session or not session.project_id:
            logger.warning("No project for session %s — skipping outcome files", session_id)
            return

        from druppie.db.models import Project
        project = self._db.query(Project).filter(Project.id == session.project_id).first()
        if not project or not project.repo_owner or not project.repo_name:
            logger.warning("No repo for project — skipping outcome files")
            return

        repo_owner = project.repo_owner
        repo_name = project.repo_name

        client = httpx.Client(
            base_url=gitea_url,
            auth=(
                os.getenv("GITEA_ADMIN_USER", "gitea_admin"),
                os.getenv("GITEA_ADMIN_PASSWORD", "GiteaAdmin123"),
            ),
            timeout=30,
        )

        commit_msg = outcome.get("commit_message", "Automated commit")
        branch = outcome.get("branch")

        try:
            for f in files:
                path = f.get("path", "")
                content = f.get("content", "")
                if not path or not content:
                    continue

                encoded = base64.b64encode(content.encode()).decode()

                # Check if file exists (need SHA for update)
                r = client.get(f"/api/v1/repos/{repo_owner}/{repo_name}/contents/{path}")

                body: dict = {
                    "content": encoded,
                    "message": commit_msg or f"Add {path}",
                }
                if branch:
                    body["branch"] = branch

                if r.status_code == 200:
                    body["sha"] = r.json()["sha"]
                    r = client.put(
                        f"/api/v1/repos/{repo_owner}/{repo_name}/contents/{path}",
                        json=body,
                    )
                else:
                    r = client.post(
                        f"/api/v1/repos/{repo_owner}/{repo_name}/contents/{path}",
                        json=body,
                    )

                if r.status_code in (200, 201):
                    logger.info("Created file %s in %s/%s", path, repo_owner, repo_name)
                else:
                    logger.warning(
                        "Failed to create %s in %s/%s: %s",
                        path, repo_owner, repo_name, r.status_code,
                    )
        finally:
            client.close()
