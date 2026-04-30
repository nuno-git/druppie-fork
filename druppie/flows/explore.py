"""Explore flow — investigates a codebase inside a sandbox.

Runs a single router agent that can spawn parallel explorer subagents.
"""

from __future__ import annotations

from .base import AgentResult, run_agent


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

    prompt = (
        f"## Question\n"
        f"{task_description}\n\n"
        f"Answer this by reading the repo (cloned at /workspace) directly with bash/read/grep/find, "
        f"and/or by calling spawn_subagents when you need several independent lookups at once. "
        f"When you have a solid answer, call the done tool with your answer as the message."
    )

    return await run_agent(
        "router",
        prompt,
        sandbox_launch=True,
        sandbox_image=sandbox_image,
        source_repo=source_repo,
        source_branch=source_branch,
        model=model,
        ingest_url=ingest_url,
        ingest_token=ingest_token,
    )
