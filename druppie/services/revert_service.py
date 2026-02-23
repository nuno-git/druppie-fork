"""Revert service - handles retry-from-run logic.

Reverts agent runs (target + subsequent), cleans up git state and DB records,
then recreates pending runs for re-execution.
"""

import json
from uuid import UUID

import structlog
from sqlalchemy.orm import Session as DBSessionType

from druppie.db.models import (
    AgentRun,
    Approval,
    LlmCall,
    LlmRetry,
    Message,
    Question,
    Session,
    ToolCall,
    ToolCallNormalization,
)
from druppie.domain.common import AgentRunStatus, SessionStatus

logger = structlog.get_logger()


class RevertService:
    """Handles reverting agent runs and preparing for retry."""

    def __init__(self, db: DBSessionType):
        self.db = db

    async def retry_from_run(
        self,
        session_id: UUID,
        target_agent_run_id: UUID,
    ) -> dict:
        """Revert target agent run and all subsequent runs, then recreate as pending.

        Steps:
        1. Validate session and agent run
        2. Collect runs to revert (target + subsequent by sequence_number)
        3. Analyze git side effects (commits, PRs)
        4. Revert git state via MCP
        5. Close open PRs
        6. Delete DB records in FK-safe order
        7. Recreate pending runs
        8. Reset session status

        Args:
            session_id: Session UUID
            target_agent_run_id: Agent run to retry from

        Returns:
            Dict with revert details

        Raises:
            ValueError: If validation fails
        """
        # Step 1: Validate
        session = self.db.query(Session).filter(Session.id == session_id).first()
        if not session:
            raise ValueError(f"Session {session_id} not found")
        # Note: session may already be ACTIVE if the API route set it before
        # spawning the background task. That's expected — the route validates
        # the original status before setting ACTIVE.

        target_run = self.db.query(AgentRun).filter(
            AgentRun.id == target_agent_run_id,
            AgentRun.session_id == session_id,
        ).first()
        if not target_run:
            raise ValueError(f"Agent run {target_agent_run_id} not found in session {session_id}")

        target_sequence = target_run.sequence_number
        if target_sequence is None:
            raise ValueError("Agent run has no sequence_number — cannot determine revert scope")

        logger.info(
            "retry_from_run_start",
            session_id=str(session_id),
            target_agent_run_id=str(target_agent_run_id),
            target_sequence=target_sequence,
        )

        # Step 2: Collect runs to revert
        runs_to_revert = (
            self.db.query(AgentRun)
            .filter(
                AgentRun.session_id == session_id,
                AgentRun.sequence_number >= target_sequence,
            )
            .order_by(AgentRun.sequence_number)
            .all()
        )

        if not runs_to_revert:
            raise ValueError("No runs found to revert")

        agent_run_ids = [r.id for r in runs_to_revert]

        logger.info(
            "runs_to_revert",
            count=len(runs_to_revert),
            agent_ids=[r.agent_id for r in runs_to_revert],
        )

        # Step 3: Analyze git side effects
        git_analysis = self._analyze_git_side_effects(
            session_id=session_id,
            agent_run_ids=agent_run_ids,
            target_sequence=target_sequence,
        )

        # Step 4: Revert git state
        if git_analysis["pre_run_commit_sha"]:
            await self._revert_git_state(
                session=session,
                target_commit=git_analysis["pre_run_commit_sha"],
            )

        # Step 5: Close open PRs
        for pr_number in git_analysis["pr_numbers"]:
            await self._close_pr(session=session, pr_number=pr_number)

        # Step 6: Save run info before deleting
        runs_info = [
            {
                "agent_id": r.agent_id,
                "planned_prompt": r.planned_prompt,
                "sequence_number": r.sequence_number,
            }
            for r in runs_to_revert
        ]

        # Step 7: Delete DB records in FK-safe order
        self._delete_records(session_id=session_id, agent_run_ids=agent_run_ids)

        # Step 8: Recreate pending runs
        new_run_ids = []
        for info in runs_info:
            new_run = AgentRun(
                session_id=session_id,
                agent_id=info["agent_id"],
                planned_prompt=info["planned_prompt"],
                sequence_number=info["sequence_number"],
                status=AgentRunStatus.PENDING.value,
            )
            self.db.add(new_run)
            self.db.flush()
            new_run_ids.append(str(new_run.id))

        # Step 9: Reset session
        session.status = SessionStatus.ACTIVE.value
        session.error_message = None
        self._recalculate_session_tokens(session)

        self.db.commit()

        logger.info(
            "retry_from_run_complete",
            session_id=str(session_id),
            reverted_count=len(runs_to_revert),
            new_pending_count=len(new_run_ids),
            git_reverted=bool(git_analysis["pre_run_commit_sha"]),
            prs_closed=len(git_analysis["pr_numbers"]),
        )

        return {
            "success": True,
            "reverted_runs": len(runs_to_revert),
            "new_pending_runs": len(new_run_ids),
            "git_reverted": bool(git_analysis["pre_run_commit_sha"]),
            "prs_closed": git_analysis["pr_numbers"],
            "warnings": git_analysis.get("warnings", []),
        }

    def _analyze_git_side_effects(
        self,
        session_id: UUID,
        agent_run_ids: list[UUID],
        target_sequence: int,
    ) -> dict:
        """Scan tool calls for git operations that need reverting.

        Returns:
            Dict with pre_run_commit_sha, commit_shas, pr_numbers, warnings
        """
        commit_shas = []
        pr_numbers = []
        warnings = []

        # Scan reverted runs for git operations
        tool_calls = (
            self.db.query(ToolCall)
            .filter(ToolCall.agent_run_id.in_(agent_run_ids))
            .all()
        )

        for tc in tool_calls:
            if tc.tool_name == "commit_and_push" and tc.result:
                result = self._parse_tool_result(tc.result)
                if result and result.get("commit_sha"):
                    commit_shas.append(result["commit_sha"])

            elif tc.tool_name == "create_pull_request" and tc.result:
                result = self._parse_tool_result(tc.result)
                if result and result.get("pr_number"):
                    pr_numbers.append(result["pr_number"])

            elif tc.tool_name == "merge_pull_request" and tc.status == "completed":
                warnings.append(
                    f"Agent run contains a merged PR — cannot safely revert merge. "
                    f"Tool call: {tc.id}"
                )

        # Find pre-run commit SHA from the last commit before the target sequence
        pre_run_commit_sha = None
        prior_tool_calls = (
            self.db.query(ToolCall)
            .join(AgentRun, ToolCall.agent_run_id == AgentRun.id)
            .filter(
                AgentRun.session_id == session_id,
                AgentRun.sequence_number < target_sequence,
                ToolCall.tool_name == "commit_and_push",
                ToolCall.status == "completed",
            )
            .order_by(ToolCall.created_at.desc())
            .first()
        )

        if prior_tool_calls and prior_tool_calls.result:
            result = self._parse_tool_result(prior_tool_calls.result)
            if result and result.get("commit_sha"):
                pre_run_commit_sha = result["commit_sha"]

        # If no prior commits but we have commits to revert,
        # we need to find the initial commit (before any agent work)
        if not pre_run_commit_sha and commit_shas:
            # Look for the very first commit_and_push in the entire session
            first_commit_tc = (
                self.db.query(ToolCall)
                .join(AgentRun, ToolCall.agent_run_id == AgentRun.id)
                .filter(
                    AgentRun.session_id == session_id,
                    ToolCall.tool_name == "commit_and_push",
                    ToolCall.status == "completed",
                )
                .order_by(ToolCall.created_at)
                .first()
            )
            if first_commit_tc and first_commit_tc.result:
                result = self._parse_tool_result(first_commit_tc.result)
                sha = result.get("commit_sha") if result else None
                if sha:
                    # We need the parent of this commit
                    # For now, use the first commit's SHA with ~1 notation
                    pre_run_commit_sha = f"{sha}~1"

        return {
            "pre_run_commit_sha": pre_run_commit_sha,
            "commit_shas": commit_shas,
            "pr_numbers": pr_numbers,
            "warnings": warnings,
        }

    def _parse_tool_result(self, result: str) -> dict | None:
        """Parse a tool call result string as JSON."""
        if not result:
            return None
        try:
            if isinstance(result, dict):
                return result
            return json.loads(result)
        except (json.JSONDecodeError, TypeError):
            return None

    async def _revert_git_state(self, session: Session, target_commit: str) -> None:
        """Call revert_to_commit MCP tool to reset git state."""
        from druppie.core.mcp_config import MCPConfig
        from druppie.execution.mcp_http import MCPHttp

        try:
            mcp_config = MCPConfig()
            mcp_http = MCPHttp(mcp_config)

            result = await mcp_http.call(
                server="coding",
                tool="revert_to_commit",
                args={
                    "target_commit": target_commit,
                    "session_id": str(session.id),
                },
                timeout_seconds=120.0,
            )

            if not result.get("success"):
                logger.warning(
                    "git_revert_failed",
                    session_id=str(session.id),
                    target_commit=target_commit,
                    error=result.get("error"),
                )
            else:
                logger.info(
                    "git_revert_success",
                    session_id=str(session.id),
                    previous_head=result.get("previous_head"),
                    new_head=result.get("new_head"),
                    force_pushed=result.get("force_pushed"),
                )

        except Exception as e:
            logger.warning(
                "git_revert_error",
                session_id=str(session.id),
                error=str(e),
            )

    async def _close_pr(self, session: Session, pr_number: int) -> None:
        """Call close_pull_request MCP tool."""
        from druppie.core.mcp_config import MCPConfig
        from druppie.execution.mcp_http import MCPHttp

        try:
            mcp_config = MCPConfig()
            mcp_http = MCPHttp(mcp_config)

            result = await mcp_http.call(
                server="coding",
                tool="close_pull_request",
                args={
                    "pr_number": pr_number,
                    "session_id": str(session.id),
                },
                timeout_seconds=30.0,
            )

            if result.get("success"):
                logger.info("closed_pr", pr_number=pr_number, session_id=str(session.id))
            else:
                logger.warning(
                    "close_pr_failed",
                    pr_number=pr_number,
                    error=result.get("error"),
                )

        except Exception as e:
            logger.warning("close_pr_error", pr_number=pr_number, error=str(e))

    def _delete_records(self, session_id: UUID, agent_run_ids: list[UUID]) -> None:
        """Delete all DB records for the given agent runs in FK-safe order."""
        # 1. ToolCallNormalization (FK -> tool_calls)
        tc_ids = [
            tc.id for tc in
            self.db.query(ToolCall.id).filter(ToolCall.agent_run_id.in_(agent_run_ids)).all()
        ]
        if tc_ids:
            self.db.query(ToolCallNormalization).filter(
                ToolCallNormalization.tool_call_id.in_(tc_ids)
            ).delete(synchronize_session="fetch")

        # 2. Approval (FK -> agent_runs, tool_calls)
        self.db.query(Approval).filter(
            Approval.agent_run_id.in_(agent_run_ids)
        ).delete(synchronize_session="fetch")

        # 3. Question (FK -> agent_runs)
        self.db.query(Question).filter(
            Question.agent_run_id.in_(agent_run_ids)
        ).delete(synchronize_session="fetch")

        # 4. ToolCall (FK -> agent_runs, llm_calls)
        if tc_ids:
            self.db.query(ToolCall).filter(
                ToolCall.id.in_(tc_ids)
            ).delete(synchronize_session="fetch")

        # 5. LlmRetry (FK -> llm_calls)
        llm_ids = [
            lc.id for lc in
            self.db.query(LlmCall.id).filter(LlmCall.agent_run_id.in_(agent_run_ids)).all()
        ]
        if llm_ids:
            self.db.query(LlmRetry).filter(
                LlmRetry.llm_call_id.in_(llm_ids)
            ).delete(synchronize_session="fetch")

        # 6. LlmCall (FK -> agent_runs)
        if llm_ids:
            self.db.query(LlmCall).filter(
                LlmCall.id.in_(llm_ids)
            ).delete(synchronize_session="fetch")

        # 7. Message — only messages WITH agent_run_id in the set
        self.db.query(Message).filter(
            Message.agent_run_id.in_(agent_run_ids)
        ).delete(synchronize_session="fetch")

        # 8. AgentRun — child runs first (parent_run_id)
        self.db.query(AgentRun).filter(
            AgentRun.parent_run_id.in_(agent_run_ids)
        ).delete(synchronize_session="fetch")

        # 9. AgentRun — the target + subsequent runs
        self.db.query(AgentRun).filter(
            AgentRun.id.in_(agent_run_ids)
        ).delete(synchronize_session="fetch")

        self.db.flush()

        logger.info(
            "records_deleted",
            agent_runs=len(agent_run_ids),
            tool_calls=len(tc_ids),
            llm_calls=len(llm_ids),
        )

    def _recalculate_session_tokens(self, session: Session) -> None:
        """Recalculate session token totals from remaining agent runs."""
        from sqlalchemy import func

        result = (
            self.db.query(
                func.coalesce(func.sum(AgentRun.prompt_tokens), 0),
                func.coalesce(func.sum(AgentRun.completion_tokens), 0),
                func.coalesce(func.sum(AgentRun.total_tokens), 0),
            )
            .filter(AgentRun.session_id == session.id)
            .first()
        )

        session.prompt_tokens = result[0]
        session.completion_tokens = result[1]
        session.total_tokens = result[2]
