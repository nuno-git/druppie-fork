"""Explore flow — investigates a codebase inside a sandbox.

Runs a single router agent that can spawn parallel explorer subagents.
Retries up to 3 times if the router produces empty output.
"""

from __future__ import annotations

import structlog

from .base import AgentResult, run_agent

logger = structlog.get_logger()

MAX_ROUTER_ATTEMPTS = 3


async def explore(
    task_description: str,
    *,
    source_repo: str | None = None,
    source_branch: str | None = None,
    sandbox_image: str | None = None,
    model: str | None = None,
    ingest_url: str | None = None,
    ingest_token: str | None = None,
) -> AgentResult:
    """Run the explore flow.

    Args:
        task_description: What to investigate
        source_repo: Git repo to clone into sandbox
        source_branch: Branch to clone
        sandbox_image: Sandbox Docker image
        model: LLM model override
        ingest_url: URL for journal events
        ingest_token: Auth token for journal

    Returns:
        AgentResult with the investigation answer
    """

    prompt = (
        f"## Question\n"
        f"{task_description}\n\n"
        f"Answer this by reading the repo (cloned at /workspace) directly with bash/read/grep/find, "
        f"and/or by calling spawn_parallel_explorers when you need several independent lookups at once. "
        f"When you have a solid answer, call the done tool with your answer as the message."
    )

    for attempt in range(1, MAX_ROUTER_ATTEMPTS + 1):
        current_prompt = (
            prompt
            if attempt == 1
            else (
                f"Retry {attempt}/{MAX_ROUTER_ATTEMPTS} — your previous attempt ended without a final answer.\n\n"
                f"## Original question\n{task_description}\n\n"
                f"You MUST call the done tool with your answer. Do not call any other tools — "
                f"just synthesise your answer and call done."
            )
        )

        result = await run_agent(
            "router",
            current_prompt,
            sandbox_launch=True,
            sandbox_image=sandbox_image,
            source_repo=source_repo,
            source_branch=source_branch,
            model=model,
            ingest_url=ingest_url,
            ingest_token=ingest_token,
        )

        if not result.success:
            logger.warning(
                "explore_router_failed",
                attempt=attempt,
                error=result.output[:200],
            )
            break  # Hard error, don't retry

        if result.output.strip() or result.summary.strip():
            logger.info("explore_success", attempt=attempt)
            return result

        logger.warning("explore_router_empty", attempt=attempt)

    return AgentResult(
        output="",
        summary="",
        variables={},
        success=False,
    )
