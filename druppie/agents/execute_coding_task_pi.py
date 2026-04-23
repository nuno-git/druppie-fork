"""Dispatcher for the execute_coding_task_pi built-in tool.

Resolves repo context + credentials the same way execute_coding_task does
today (reusing GitHub App service and Gitea sandbox-user creation), creates
a PiCodingRun row, registers an ingest token, spawns pi_agent as a Node
subprocess, and returns the summary to the caller agent.

Runs inside the druppie backend container (node + docker.io already present).
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
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
    import os
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
    return creds, creds.get("user_id")


def _resolve_llm_credentials() -> dict:
    import os
    return {
        "anthropic_api_key": os.getenv("ANTHROPIC_API_KEY", ""),
        "zai_api_key": os.getenv("ZAI_API_KEY", ""),
    }


async def execute_coding_task_pi(
    args: dict,
    session_id: UUID,
    agent_run_id: UUID,
    execution_repo: "ExecutionRepository",
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

    git_provider: str = args.get("git_provider") or _default_git_provider_for(repo_target)
    if git_provider not in VALID_GIT_PROVIDERS:
        return {"success": False, "error": f"invalid git_provider {git_provider!r}"}

    agent_name: str | None = args.get("agent")
    source_branch: str | None = args.get("source_branch")

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
        task_prompt=task,
        agent_name=agent_name,
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

    runner = PiAgentRunner(
        run_id=run_id,
        task_prompt=task,
        agent_name=agent_name,
        repo_target=repo_target,
        git_provider=git_provider,
        repo_owner=repo_ctx.repo_owner,
        repo_name=repo_ctx.repo_name,
        git_credentials=git_creds,
        llm_credentials=llm_creds,
        source_branch=source_branch,
    )

    try:
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

    row.exit_code = exit_code
    row.stdout_tail = result.get("stdout_tail")
    row.stderr_tail = result.get("stderr_tail")
    if summary is not None:
        row.summary = json.dumps(summary)
        row.status = "succeeded" if summary.get("success") else "failed"
        if summary.get("pr", {}).get("url"):
            row.pr_url = summary["pr"]["url"]
            row.pr_number = summary["pr"].get("number")
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
            "error": f"pi_agent exited {exit_code} without summary",
            "stderr_tail": result.get("stderr_tail", "")[-2000:],
        }

    narrative = _build_narrative(summary)

    return {
        "success": bool(summary.get("success")),
        "run_id": run_id,
        "pi_coding_run_id": str(row.id),
        # Human-readable aggregate so the caller agent can reason about
        # what pi_agent actually DID (not just stats). Each pi_agent
        # subagent's own end-of-turn text gets trimmed and concatenated.
        "narrative": narrative,
        "summary": summary,
        "pr_url": row.pr_url,
        "branch": summary.get("push", {}).get("branch") or row.branch_name,
        "commits": summary.get("commits", []),
        "phases": summary.get("phases", []),
    }


def _build_narrative(summary: dict) -> str:
    """Collapse summary.narratives[] into a single scannable block.

    Shape of each narrative item: {agent, iteration, text}. We group by
    agent (preserving order) and prefix with a header so the caller can
    see which subagent said what.
    """
    items = summary.get("narratives") or []
    if not items:
        return ""
    parts: list[str] = []
    for item in items:
        agent = item.get("agent", "?")
        iteration = item.get("iteration", 0)
        text = (item.get("text") or "").strip()
        if not text:
            continue
        header = f"[{agent}" + (f" i{iteration}]" if iteration else "]")
        parts.append(f"{header}\n{text}")
    return "\n\n".join(parts)
