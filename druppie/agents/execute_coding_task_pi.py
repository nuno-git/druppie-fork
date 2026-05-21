"""Dispatcher for the execute_coding_task_pi built-in tool.

Resolves repo context + credentials the same way execute_coding_task does
today (reusing GitHub App service and Gitea sandbox-user creation), creates
a PiCodingRun row, registers an ingest token, spawns pi_agent as a Node
subprocess, and returns the summary to the caller agent.

Runs inside the druppie backend container (node + docker.io already present).
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

import structlog

from druppie.agents.pi_agent_runner import PiAgentRunner, generate_ingest_token
from druppie.api.routes.pi_agent import register_ingest_token, revoke_ingest_token
from druppie.db.models.pi_coding_run import PiCodingRun

if TYPE_CHECKING:
    from druppie.repositories.execution import ExecutionRepository

logger = structlog.get_logger()

VALID_REPO_TARGETS = {"project", "druppie_core"}
VALID_GIT_PROVIDERS = {"github_app", "gitea"}

PI_AGENT_ROOT = Path(os.getenv("PI_AGENT_ROOT", "/app/pi_agent"))


def _discover_primary_agents() -> set[str]:
    """Scan pi_agent/.pi/agents/*.md for agents with `primary: true` in frontmatter."""
    agents_dir = PI_AGENT_ROOT / ".pi" / "agents"
    primary: set[str] = set()
    if not agents_dir.is_dir():
        logger.warning("pi_agent_agents_dir_not_found", path=str(agents_dir))
        return primary
    for md_file in sorted(agents_dir.glob("*.md")):
        try:
            text = md_file.read_text(encoding="utf-8")
        except Exception:
            continue
        # Simple frontmatter parser: extract YAML between --- markers
        if not text.startswith("---"):
            continue
        end = text.find("---", 3)
        if end == -1:
            continue
        frontmatter = text[3:end].strip()
        # Check for primary: true (handles both "primary: true" and "primary:  true")
        if "primary: true" in frontmatter or "primary:  true" in frontmatter:
            # Extract the name field
            for line in frontmatter.split("\n"):
                line = line.strip()
                if line.startswith("name:"):
                    agent_name = line.split(":", 1)[1].strip()
                    if agent_name:
                        primary.add(agent_name)
                        break
    return primary


def _default_git_provider_for(repo_target: str) -> str:
    return "github_app" if repo_target == "druppie_core" else "gitea"


async def _resolve_github_credentials(repo_owner: str, repo_name: str) -> dict:
    """GitHub App creds are already in env (GITHUB_APP_ID / _INSTALLATION_ID /
    _PRIVATE_KEY_PATH, configured in docker-compose.yml and mounted via
    /app/secrets/). pi_agent's github/app.ts reads exactly those names and
    mints its own installation token per run — so we do NOT mint here.

    Minting on the Python side (and passing GITHUB_TOKEN) would shadow the App
    vars and force pi_agent into PAT-mode. Just return a marker; the env vars
    are inherited through os.environ in PiAgentRunner._build_env.
    """
    if not os.getenv("GITHUB_APP_ID") or not os.getenv("GITHUB_APP_INSTALLATION_ID"):
        raise ValueError(
            "GITHUB_APP_ID / GITHUB_APP_INSTALLATION_ID not set in backend env — "
            "cannot run execute_coding_task_pi with git_provider=github_app"
        )
    return {"provider": "github_app"}


async def _resolve_gitea_credentials(repo_owner: str, repo_name: str, run_id: str) -> tuple[dict, str | None]:
    from druppie.opencode.gitea_credentials import create_sandbox_git_user
    creds = await create_sandbox_git_user(
        sandbox_session_id=run_id,
        repo_owner=repo_owner,
        repo_name=repo_name,
    )
    return creds, creds.get("username")


def _resolve_llm_credentials() -> dict:
    return {
        "anthropic_api_key": os.getenv("ANTHROPIC_API_KEY", ""),
        "zai_api_key": os.getenv("ZAI_API_KEY", ""),
    }


async def execute_coding_task_pi(
    args: dict,
    session_id: UUID,
    agent_run_id: UUID,
    execution_repo: "ExecutionRepository",
    tool_call_id: UUID | None = None,
) -> dict:
    """Synchronously run the pi_agent orchestrator; return its summary.

    Unlike execute_coding_task (which offloads to a control-plane webhook),
    this tool is in-process: the caller agent awaits the subprocess and
    receives the full RunSummary as the tool output.
    """
    task: str = args.get("task", "")
    if not task:
        return {"success": False, "error": "task is required"}

    raw_repo_target: str | None = args.get("repo_target")
    repo_target = raw_repo_target or "project"
    if repo_target not in VALID_REPO_TARGETS:
        return {"success": False, "error": f"invalid repo_target {repo_target!r}"}

    # Enforce per-caller sandbox_constraints (same pattern as the legacy
    # execute_coding_task — defense in depth on top of schema narrowing).
    try:
        from druppie.agents.runtime import Agent as AgentLoader
        agent_run = execution_repo.get_by_id(agent_run_id)
        if agent_run and agent_run.agent_id:
            definition = AgentLoader._load_definition(agent_run.agent_id)
            if definition and definition.sandbox_constraints:
                c = definition.sandbox_constraints
                if c.allowed_repo_targets is not None and repo_target not in c.allowed_repo_targets:
                    return {
                        "success": False,
                        "error": (
                            f"Agent '{definition.id}' can only use repo targets {c.allowed_repo_targets} — "
                            f"got {repo_target!r}"
                        ),
                    }
    except Exception:
        definition = None

    # Derived from repo_target; the LLM never picks this. Kept as a column
    # on PiCodingRun for observability but not part of the tool schema.
    git_provider: str = _default_git_provider_for(repo_target)

    primary_agents: set[str] = _discover_primary_agents()
    if not primary_agents:
        logger.warning("no_primary_agents_found", pi_agent_root=str(PI_AGENT_ROOT))

    flow: str = args.get("flow") or "planner"
    if flow not in primary_agents:
        return {"success": False, "error": f"invalid flow {flow!r}; must be one of {sorted(primary_agents)}"}
    # Legacy `agent` field still accepted as an alias for `flow`, but we
    # prefer `flow`. Drop this once all callers migrate.
    legacy_agent = args.get("agent")
    if legacy_agent and legacy_agent not in ("null", None):
        if legacy_agent in primary_agents:
            flow = legacy_agent

    # Enforce per-caller flow constraint too.
    try:
        if definition and definition.sandbox_constraints:
            c = definition.sandbox_constraints
            if c.allowed_agents is not None:
                flow_constraint = [a for a in c.allowed_agents if a in primary_agents]
                if flow_constraint and flow not in flow_constraint:
                    return {
                        "success": False,
                        "error": (
                            f"Agent '{definition.id}' can only use pi_agent flows {flow_constraint} — "
                            f"got {flow!r}"
                        ),
                    }
    except Exception:
        pass
    # source_branch is NOT an LLM-facing argument. The branch is determined
    # by the repo_target (druppie_core → colab-dev; project → repo's default
    # branch from Gitea). If we ever need to override, do it here based on
    # server-side context, never from LLM args.
    source_branch: str | None = (
        "colab-dev" if repo_target == "druppie_core" else None
    )

    from druppie.opencode.repo_context import resolve_repo_context
    from druppie.repositories import SessionRepository

    db = execution_repo.db
    session_repo = SessionRepository(db)
    session = session_repo.get_by_id(session_id)
    if not session:
        return {"success": False, "error": f"session {session_id} not found"}
    if not session.user_id:
        return {"success": False, "error": "session has no user_id"}

    try:
        repo_ctx = resolve_repo_context(repo_target, session_id, db)
    except ValueError as e:
        return {"success": False, "error": str(e)}

    run_id = uuid.uuid4().hex

    gitea_user_id: str | None = None
    if git_provider == "github_app":
        git_creds = await _resolve_github_credentials(repo_ctx.repo_owner, repo_ctx.repo_name)
    else:
        git_creds, gitea_user_id = await _resolve_gitea_credentials(
            repo_ctx.repo_owner, repo_ctx.repo_name, run_id
        )

    llm_creds = _resolve_llm_credentials()

    row = PiCodingRun(
        run_id=run_id,
        session_id=session_id,
        user_id=session.user_id,
        tool_call_id=tool_call_id,
        task_prompt=task,
        agent_name=flow,
        repo_target=repo_target,
        git_provider=git_provider,
        repo_owner=repo_ctx.repo_owner,
        repo_name=repo_ctx.repo_name,
        status="running",
        events=json.dumps([]),
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    ingest_token = generate_ingest_token()
    register_ingest_token(run_id, ingest_token)

    try:
        runner = PiAgentRunner(
            run_id=run_id,
            task_prompt=task,
            agent_name=flow,
            repo_target=repo_target,
            git_provider=git_provider,
            repo_owner=repo_ctx.repo_owner,
            repo_name=repo_ctx.repo_name,
            git_credentials=git_creds,
            llm_credentials=llm_creds,
            source_branch=source_branch,
        )
        result = await runner.run(ingest_token)
    finally:
        revoke_ingest_token(run_id)
        if gitea_user_id:
            try:
                from druppie.opencode.gitea_credentials import delete_sandbox_git_user
                await delete_sandbox_git_user(gitea_user_id)
            except Exception as e:
                logger.warning("pi_agent_gitea_cleanup_failed", run_id=run_id, error=str(e))

    summary = result.get("summary")
    exit_code = result["exit_code"]

    # Under druppie (ingest mode) pi_agent's journal.close() posts the summary
    # straight to /api/pi-agent-runs/{run_id}/summary instead of writing
    # summary.json to disk — so runner._load_summary() returns None. Fall
    # back to the DB row, which was just updated by that ingest.
    if summary is None:
        db.refresh(row)
        if row.summary:
            try:
                summary = json.loads(row.summary)
            except (ValueError, TypeError):
                summary = None

    row.exit_code = exit_code
    row.stdout_tail = result.get("stdout_tail")
    row.stderr_tail = result.get("stderr_tail")
    if summary is not None:
        # Only persist if not already ingested (avoid a pointless re-write).
        if not row.summary:
            row.summary = json.dumps(summary)
        if not row.status or row.status == "running":
            row.status = "succeeded" if summary.get("success") else "failed"
        if (summary.get("pr") or {}).get("url"):
            row.pr_url = summary["pr"]["url"]
            row.pr_number = (summary.get("pr") or {}).get("number")
    else:
        row.status = "failed" if exit_code != 0 else "succeeded"
    if row.status in ("succeeded", "failed") and row.completed_at is None:
        row.completed_at = datetime.now(timezone.utc)
    db.add(row)
    db.commit()

    if summary is None:
        return {
            "success": exit_code == 0,
            "run_id": run_id,
            "pi_coding_run_id": str(row.id),
            "error": (
                f"pi_agent exited {exit_code} without summary — neither "
                f"summary.json on disk nor the ingested DB row had one. "
                f"Check the event journal on the PiCodingRun for partial progress."
            ),
            "stderr_tail": result.get("stderr_tail", "")[-2000:],
        }

    pi_success = bool(summary.get("success"))

    # When pi_agent completed but reported success=false, build a concrete
    # error message from summary.errors so the caller agent isn't left
    # with "Tool call failed: None".
    error_message: str | None = None
    if not pi_success:
        err_list = [e for e in (summary.get("errors") or []) if e]
        error_message = "; ".join(err_list[:5]) if err_list else (
            f"pi_agent flow={flow} completed but reported success=false "
            f"with no specific errors. See PiCodingRun events for context."
        )

    # Build a unified response. For router/explore flows the answer is
    # the key deliverable (a concise narrative); for planner/coding flows
    # the agent summaries and git deliverables are what matters. Both are
    # returned together — the caller can pick what it needs.
    answer = _extract_primary_answer(summary, flow)
    summaries = _extract_agent_summaries(summary)

    # Fallback: if summary lacks push/PR data, check the stdout variables
    # (_branch, _pr_url are set by run-agent.ts after git ops).
    variables = result.get("variables", {})
    branch = (summary.get("push") or {}).get("branch") or row.branch_name
    if not branch:
        branch = variables.get("_branch")
    pr_url = row.pr_url
    if not pr_url:
        pr_url = variables.get("_pr_url")

    return {
        "success": pi_success,
        "run_id": run_id,
        "pi_coding_run_id": str(row.id),
        "answer": answer,
        "summaries": summaries,
        "deliverables": {
            "pr_url": pr_url,
            "branch": branch,
            "commits": [
                {"sha": c.get("sha"), "message": c.get("message")}
                for c in (summary.get("commits") or [])
            ],
        },
        **({"error": error_message} if error_message else {}),
    }


def _extract_primary_answer(summary: dict, primary_agent: str) -> str:
    """Return the primary agent's final narrative as the answer.

    For router/explore flows the answer is a synthesised text answer.
    For planner/coding flows the answer is the planner's build summary.
    We take the LAST non-empty narrative from the primary agent.
    """
    narratives = summary.get("narratives") or []
    agent_attempts = [
        n for n in narratives
        if (n.get("agent") or "").startswith(primary_agent)
        and (n.get("text") or "").strip()
    ]
    if agent_attempts:
        return agent_attempts[-1]["text"].strip()
    return ""


def _extract_agent_summaries(summary: dict) -> dict[str, str]:
    """Extract agent summaries from the run summary.

    Dynamically discovers which agents produced narratives and extracts
    their final message as a summary. The summary section is identified
    by the agent name prefix in each narrative key.
    """
    narratives = summary.get("narratives") or []
    summaries: dict[str, str] = {}

    # Dynamically discover which agents ran from the narratives
    # Each narrative key is like "router/attempt-1", "planner/attempt-0", etc.
    discovered_agents: set[str] = set()
    for n in narratives:
        agent_key = (n.get("agent") or "").split("/")[0]
        if agent_key:
            discovered_agents.add(agent_key)

    for agent_name in sorted(discovered_agents):
        agent_narratives = [
            n for n in narratives
            if (n.get("agent") or "").startswith(agent_name)
            and (n.get("text") or "").strip()
        ]
        if agent_narratives:
            text = agent_narratives[-1]["text"]
            summary_text = text.split("## Summary")[1].split("##")[0].strip() if "## Summary" in text else text.strip()
            summaries[agent_name] = summary_text

    return summaries
