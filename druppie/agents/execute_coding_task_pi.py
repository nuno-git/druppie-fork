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
VALID_FLOWS = {"tdd", "explore"}


def _default_git_provider_for(repo_target: str) -> str:
    return "github_app" if repo_target == "druppie_core" else "gitea"


async def _run_explore_flow(
    task: str,
    run_id: str,
    ingest_token: str,
    git_credentials: dict,
    git_provider: str,
    repo_owner: str,
    repo_name: str,
    source_branch: str | None,
) -> dict:
    import os
    from druppie.flows.explore import explore

    ingest_url = f"{os.getenv('DRUPPIE_INTERNAL_URL', 'http://localhost:8000')}/api/pi-agent-runs/{run_id}/events"
    sandbox_image = os.getenv("PI_AGENT_SANDBOX_IMAGE", "oneshot-sandbox:latest")

    if git_provider == "github_app":
        source_repo = f"https://github.com/{repo_owner}/{repo_name}.git"
    else:
        base = git_credentials.get("base_url") or os.getenv("GITEA_INTERNAL_URL", "")
        base = base.rstrip("/")
        source_repo = f"{base}/{repo_owner}/{repo_name}.git"

    agent_result = await explore(
        task_description=task,
        source_repo=source_repo,
        source_branch=source_branch,
        sandbox_image=sandbox_image,
        ingest_url=ingest_url,
        ingest_token=ingest_token,
    )

    return {
        "success": agent_result.success,
        "answer": agent_result.output or agent_result.summary,
        "exit_code": 0 if agent_result.success else 1,
    }


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

    flow: str = args.get("flow") or "tdd"
    if flow not in VALID_FLOWS:
        return {"success": False, "error": f"invalid flow {flow!r}; must be one of {sorted(VALID_FLOWS)}"}
    # Legacy `agent` field still accepted as an alias for `flow`, but we
    # prefer `flow`. Drop this once all callers migrate.
    legacy_agent = args.get("agent")
    if legacy_agent and legacy_agent not in ("null", None):
        if legacy_agent in VALID_FLOWS:
            flow = legacy_agent

    # Enforce per-caller flow constraint too.
    try:
        if definition and definition.sandbox_constraints:
            c = definition.sandbox_constraints
            if c.allowed_agents is not None:
                # Only apply if allowed_agents references actual flows — legacy
                # sandbox-agent names don't overlap with flow names so this is
                # a safe intersection test.
                flow_constraint = [a for a in c.allowed_agents if a in VALID_FLOWS]
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
        if flow == "explore":
            result = await _run_explore_flow(
                task=task,
                run_id=run_id,
                ingest_token=ingest_token,
                git_credentials=git_creds,
                git_provider=git_provider,
                repo_owner=repo_ctx.repo_owner,
                repo_name=repo_ctx.repo_name,
                source_branch=source_branch,
            )
        else:
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

    if flow == "explore":
        exit_code = 0 if result["success"] else 1
        summary = None
    else:
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

    # Keep the payload that's returned to the CALLING agent minimal —
    # agents don't need full phase/agent stats, token counts, or the
    # full journal, they need the answer / deliverables. The UI pulls
    # everything richer via /api/pi-agent-runs/by-tool-call/{id} directly.
    if flow == "explore":
        # Explore: return the answer. That's it.
        answer = _extract_explore_answer(summary)
        return {
            "success": pi_success,
            "run_id": run_id,
            "pi_coding_run_id": str(row.id),
            "answer": answer,
            **({"error": error_message} if error_message else {}),
        }

    # TDD: return agent summaries AND deliverables (branch, PR, commits).
    # The summaries give the calling agent context about what each agent did.
    summaries = _extract_agent_summaries(summary)

    return {
        "success": pi_success,
        "run_id": run_id,
        "pi_coding_run_id": str(row.id),
        "summaries": summaries,
        "deliverables": {
            "pr_url": row.pr_url,
            "branch": summary.get("push", {}).get("branch") or row.branch_name,
            "commits": [
                {"sha": c.get("sha"), "message": c.get("message")}
                for c in (summary.get("commits") or [])
            ],
        },
        **({"error": error_message} if error_message else {}),
    }


def _extract_explore_answer(summary: dict) -> str:
    """Return ONLY the router's final answer for an explore run.

    pi_agent's explore flow records each router attempt's end-of-turn
    message as a narrative keyed "router/attempt-N". We take the LAST
    non-empty one — that's the attempt that actually produced a
    synthesised answer (earlier empty attempts triggered retries).
    Explorer reports are an internal artifact, not the deliverable.
    """
    narratives = summary.get("narratives") or []
    router_attempts = [
        n for n in narratives
        if (n.get("agent") or "").startswith("router")
        and (n.get("text") or "").strip()
    ]
    if router_attempts:
        return router_attempts[-1]["text"].strip()
    return ""


def _extract_agent_summaries(summary: dict) -> dict[str, str]:
    """Extract agent summaries from the run summary.

    pi_agent's TDD flow records each agent's summary as a narrative.
    We extract these and return them as a map of agent name to summary.

    The summary section is identified by the agent name (e.g., "analyst",
    "planner", "wave-orchestrator", "verifier", "pr-author").
    """
    narratives = summary.get("narratives") or []
    summaries: dict[str, str] = {}

    # Agents that produce summaries in the TDD flow
    agent_names = ["analyst", "planner", "wave-orchestrator", "verifier", "pr-author"]

    for agent_name in agent_names:
        # Find the last narrative from this agent
        agent_narratives = [
            n for n in narratives
            if (n.get("agent") or "").startswith(agent_name)
            and (n.get("text") or "").strip()
        ]
        if agent_narratives:
            # Extract the summary section from the narrative text
            # The narrative may have ## Summary section or be the summary itself
            text = agent_narratives[-1]["text"]
            summary_match = text.split("## Summary")[1].split("##")[0].strip() if "## Summary" in text else text.strip()
            summaries[agent_name] = summary_match

    return summaries
