"""Revert service - handles retry-from-run logic.

Resets agent runs to PENDING and clears their execution artifacts
so the orchestrator can re-execute them.
"""

import json
import re
from typing import TYPE_CHECKING
from uuid import UUID

import structlog

from druppie.db.models.project import Project as ProjectModel
from druppie.domain.common import SessionStatus
from druppie.repositories.execution_repository import ExecutionRepository
from druppie.repositories.session_repository import SessionRepository

if TYPE_CHECKING:
    from druppie.execution.mcp_http import MCPHttp

logger = structlog.get_logger()


class RevertService:
    """Handles reverting agent runs and preparing for retry."""

    def __init__(
        self,
        execution_repo: ExecutionRepository,
        session_repo: SessionRepository,
        mcp_http: "MCPHttp",
    ):
        self.execution_repo = execution_repo
        self.session_repo = session_repo
        self.mcp_http = mcp_http

    async def retry_from_run(
        self,
        session_id: UUID,
        target_agent_run_id: UUID,
        planned_prompt: str | None = None,
    ) -> dict:
        """Retry from a specific agent run.

        Resets the target run and all subsequent runs to PENDING,
        clears their execution artifacts, and reverts git side effects.

        If a planner is in the revert set, make_plan() will naturally
        cancel the stale PENDING runs and create fresh ones when it re-runs.

        Args:
            session_id: Session UUID
            target_agent_run_id: Agent run to retry from
            planned_prompt: Optional edited prompt for the target run

        Returns:
            Dict with revert details
        """
        # Step 1: Validate
        session = self.session_repo.get_by_id(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")

        target_summary = self.execution_repo.get_by_id_for_session(
            target_agent_run_id, session_id
        )
        if not target_summary:
            raise ValueError(f"Agent run {target_agent_run_id} not found in session {session_id}")

        target_sequence = target_summary.sequence_number
        if target_sequence is None:
            raise ValueError("Agent run has no sequence_number — cannot determine revert scope")

        logger.info(
            "retry_from_run_start",
            session_id=str(session_id),
            target_agent_run_id=str(target_agent_run_id),
            target_sequence=target_sequence,
        )

        # Step 2: Collect all runs at or after target
        all_runs_after = self.execution_repo.get_runs_from_sequence(
            session_id, target_sequence
        )

        if not all_runs_after:
            raise ValueError("No runs found to revert")

        # Step 3: Split into runs to RESET vs runs to DELETE
        #
        # Two boundaries matter:
        # A) Turn boundary: if there's a user message after target_sequence,
        #    all runs at or after that message belong to a later turn and
        #    must be DELETED (they'll never re-run — the user message is gone).
        # B) Planner boundary (within same turn): runs after the first planner
        #    were created by make_plan and will be recreated when planner re-runs.
        next_user_msg = self.execution_repo.get_user_message_after_sequence(
            session_id, target_sequence
        )
        turn_boundary_seq = next_user_msg.sequence_number if next_user_msg else None

        # Separate same-turn runs from later-turn runs
        if turn_boundary_seq is not None:
            same_turn_runs = [r for r in all_runs_after if r.sequence_number < turn_boundary_seq]
            later_turn_runs = [r for r in all_runs_after if r.sequence_number >= turn_boundary_seq]
        else:
            same_turn_runs = all_runs_after
            later_turn_runs = []

        # Within the same turn, apply planner boundary logic
        first_planner_seq = None
        for run in same_turn_runs:
            if run.agent_id == "planner":
                first_planner_seq = run.sequence_number
                break

        if first_planner_seq is not None:
            runs_to_reset = [r for r in same_turn_runs if r.sequence_number <= first_planner_seq]
            runs_to_delete = [r for r in same_turn_runs if r.sequence_number > first_planner_seq] + later_turn_runs
        else:
            runs_to_reset = same_turn_runs
            runs_to_delete = later_turn_runs

        all_run_ids = [r.id for r in all_runs_after]
        reset_ids = [r.id for r in runs_to_reset]
        delete_ids = [r.id for r in runs_to_delete]

        logger.info(
            "runs_to_revert",
            reset=[(r.agent_id, r.sequence_number) for r in runs_to_reset],
            delete=[(r.agent_id, r.sequence_number) for r in runs_to_delete],
        )

        # Step 4: Analyze and revert git side effects
        git_analysis = self._analyze_git_side_effects(
            session_id=session_id,
            agent_run_ids=all_run_ids,
            target_sequence=target_sequence,
        )

        if git_analysis["pre_run_commit_sha"]:
            # Look up repo info from the session's project so the MCP coding
            # server can clone/fetch the right Gitea repo before resetting.
            repo_name = None
            repo_owner = None
            if session.project_id:
                project = self.session_repo.db.query(ProjectModel).filter_by(
                    id=session.project_id
                ).first()
                if project:
                    repo_name = project.repo_name
                    repo_owner = project.repo_owner

            await self._revert_git_state(
                session_id=session_id,
                target_commit=git_analysis["pre_run_commit_sha"],
                repo_name=repo_name,
                repo_owner=repo_owner,
            )

        for pr_number in git_analysis["pr_numbers"]:
            await self._close_pr(session_id=session_id, pr_number=pr_number)

        # Step 5: Clear artifacts and reset/delete runs
        # Clear artifacts for runs we're resetting (keep the AgentRun row)
        self.execution_repo.clear_execution_artifacts(reset_ids)

        # Fully delete planner-created runs (artifacts + AgentRun rows)
        self.execution_repo.delete_runs_fully(delete_ids)

        # Step 5b: Clean up orphan messages (e.g. from create_message tool)
        self.execution_repo.delete_orphan_messages(session_id, target_sequence)

        # Step 6: Reset the kept runs to PENDING
        self.execution_repo.reset_runs_to_pending(reset_ids)

        # Step 6b: Strip accumulated context from non-target runs.
        # When agents run, done() prepends "PREVIOUS AGENT SUMMARY" and
        # set_intent() prepends "INTENT/PROJECT_ID" to the next run's prompt.
        # On retry these need stripping so re-running agents can add them fresh.
        prompt_updates = {}
        for run in runs_to_reset:
            if run.id != target_agent_run_id and run.planned_prompt:
                stripped = self._strip_accumulated_context(run.planned_prompt)
                if stripped != run.planned_prompt:
                    prompt_updates[run.id] = stripped

        # Step 6c: Apply edited planned_prompt to target run only
        if planned_prompt is not None:
            prompt_updates[target_agent_run_id] = planned_prompt

        if prompt_updates:
            self.execution_repo.update_planned_prompt_batch(prompt_updates)

        # Step 7: Reset session (status already set to ACTIVE by lock_for_retry)
        self.session_repo.clear_error_message(session_id)
        self.session_repo.recalculate_token_totals(session_id)

        self.execution_repo.commit()

        logger.info(
            "retry_from_run_complete",
            session_id=str(session_id),
            reset_count=len(runs_to_reset),
            deleted_count=len(runs_to_delete),
            git_reverted=bool(git_analysis["pre_run_commit_sha"]),
            prs_closed=len(git_analysis["pr_numbers"]),
        )

        return {
            "success": True,
            "reset_runs": len(runs_to_reset),
            "deleted_runs": len(runs_to_delete),
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
        """Scan tool calls for git operations that need reverting."""
        commit_shas = []
        pr_numbers = []
        warnings = []

        tool_calls = self.execution_repo.get_tool_calls_for_runs(agent_run_ids)

        for tc in tool_calls:
            if tc.tool_name == "run_git" and tc.result:
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
        prior_tool_call = self.execution_repo.get_last_commit_before_sequence(
            session_id, target_sequence
        )

        if prior_tool_call and prior_tool_call.result:
            result = self._parse_tool_result(prior_tool_call.result)
            if result and result.get("commit_sha"):
                pre_run_commit_sha = result["commit_sha"]

        # If no prior commits but we have commits to revert,
        # find the parent of the first commit in the session
        if not pre_run_commit_sha and commit_shas:
            first_commit_tc = self.execution_repo.get_first_commit_in_session(session_id)
            if first_commit_tc and first_commit_tc.result:
                result = self._parse_tool_result(first_commit_tc.result)
                sha = result.get("commit_sha") if result else None
                if sha:
                    pre_run_commit_sha = f"{sha}~1"

        return {
            "pre_run_commit_sha": pre_run_commit_sha,
            "commit_shas": commit_shas,
            "pr_numbers": pr_numbers,
            "warnings": warnings,
        }

    @staticmethod
    def _parse_tool_result(result: str) -> dict | None:
        """Parse a tool call result string as JSON."""
        if not result:
            return None
        try:
            if isinstance(result, dict):
                return result
            return json.loads(result)
        except (json.JSONDecodeError, TypeError):
            return None

    async def _revert_git_state(
        self,
        session_id: UUID,
        target_commit: str,
        repo_name: str | None = None,
        repo_owner: str | None = None,
    ) -> None:
        """Call revert_to_commit MCP tool to reset git state.

        Raises RuntimeError if the revert fails — callers must not proceed
        with re-execution when git state hasn't been reverted.
        """
        args: dict = {
            "target_commit": target_commit,
            "session_id": str(session_id),
        }
        if repo_name:
            args["repo_name"] = repo_name
        if repo_owner:
            args["repo_owner"] = repo_owner

        result = await self.mcp_http.call(
            server="coding",
            tool="_internal_revert_to_commit",
            args=args,
            timeout_seconds=120.0,
        )

        if not result.get("success"):
            error = result.get("error", "unknown error")
            logger.error(
                "git_revert_failed",
                session_id=str(session_id),
                target_commit=target_commit,
                error=error,
            )
            raise RuntimeError(f"Git revert failed: {error}")

        logger.info(
            "git_revert_success",
            session_id=str(session_id),
            previous_head=result.get("previous_head"),
            new_head=result.get("new_head"),
            force_pushed=result.get("force_pushed"),
        )

    async def _close_pr(self, session_id: UUID, pr_number: int) -> None:
        """Call close_pull_request MCP tool."""
        try:
            result = await self.mcp_http.call(
                server="coding",
                tool="_internal_close_pull_request",
                args={
                    "pr_number": pr_number,
                    "session_id": str(session_id),
                },
                timeout_seconds=30.0,
            )

            if result.get("success"):
                logger.info("closed_pr", pr_number=pr_number, session_id=str(session_id))
            else:
                logger.warning(
                    "close_pr_failed",
                    pr_number=pr_number,
                    error=result.get("error"),
                )

        except Exception as e:
            logger.warning("close_pr_error", pr_number=pr_number, error=str(e))

    @staticmethod
    def _strip_accumulated_context(prompt: str) -> str:
        """Strip accumulated PREVIOUS AGENT SUMMARY and INTENT/PROJECT_ID blocks.

        These blocks are prepended by done() and set_intent() during agent
        execution. On retry they must be removed so re-running agents can
        add fresh versions without duplication.
        """
        changed = True
        while changed:
            changed = False

            # Strip "PREVIOUS AGENT SUMMARY:\n...\n\n---\n\n"
            if prompt.startswith("PREVIOUS AGENT SUMMARY:"):
                separator = "\n\n---\n\n"
                idx = prompt.find(separator)
                if idx != -1:
                    prompt = prompt[idx + len(separator):]
                    changed = True

            # Strip "INTENT: ...\nPROJECT_ID: ...\n\n"
            match = re.match(r"^INTENT: .+\nPROJECT_ID: .+\n\n", prompt)
            if match:
                prompt = prompt[match.end():]
                changed = True

        return prompt
