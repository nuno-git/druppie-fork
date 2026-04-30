"""Base utilities for Python-based flow orchestration.

Provides `run_agent()` — a thin wrapper around the pi_agent Node.js CLI
that runs a SINGLE agent inside a sandbox and returns a structured result.
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger()

PI_AGENT_ROOT = Path(os.getenv("PI_AGENT_ROOT", "/app/pi_agent"))
PI_AGENT_CLI = PI_AGENT_ROOT / "dist" / "cli.js"


@dataclass
class AgentResult:
    """Result from a single agent run."""

    output: str
    summary: str
    variables: dict[str, Any]
    success: bool
    tool_calls_used: list[str] = field(default_factory=list)


async def run_agent(
    agent: str,
    prompt: str,
    *,
    sandbox_launch: bool = True,
    sandbox_image: str | None = None,
    source_repo: str | None = None,
    source_branch: str | None = None,
    model: str | None = None,
    max_turns: int = 40,
    work_dir: str | None = None,
    ingest_url: str | None = None,
    ingest_token: str | None = None,
) -> AgentResult:
    """Run a single agent via pi_agent subprocess.

    Spawns `node pi_agent/dist/cli.js run-agent ...` and parses JSON result.
    The agent runs inside a sandbox with done-tool enforcement.

    Args:
        agent: Agent name (must exist in .pi/agents/)
        prompt: The prompt to send to the agent
        sandbox_launch: Whether to launch a new sandbox (default True)
        sandbox_image: Docker image for sandbox
        source_repo: Git repo URL to clone into sandbox
        source_branch: Branch to clone
        model: LLM model to use
        max_turns: Max agent turns
        work_dir: Working directory (auto-created if not set)
        ingest_url: URL for journal event posting
        ingest_token: Auth token for journal events

    Returns:
        AgentResult with output, summary, variables, success
    """

    cmd = [
        "node",
        str(PI_AGENT_CLI),
        "run-agent",
        "--agent",
        agent,
        "--prompt",
        prompt,
    ]

    if sandbox_launch:
        cmd.append("--sandbox-launch")
    if sandbox_image:
        cmd.extend(["--sandbox-image", sandbox_image])
    if source_repo:
        cmd.extend(["--source-repo", source_repo])
    if source_branch:
        cmd.extend(["--source-branch", source_branch])
    if model:
        cmd.extend(["--model", model])
    if max_turns:
        cmd.extend(["--max-turns", str(max_turns)])
    if work_dir:
        cmd.extend(["--workdir", work_dir])

    env = os.environ.copy()
    if ingest_url:
        env["PI_AGENT_INGEST_URL"] = ingest_url
    if ingest_token:
        env["PI_AGENT_INGEST_TOKEN"] = ingest_token
    # LLM credentials — inherit from backend container env
    # (ZAI_API_KEY, ANTHROPIC_API_KEY, etc.)

    logger.info("run_agent_start", agent=agent, sandbox_launch=sandbox_launch)

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )

    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        error_msg = stderr.decode()[-2000:] if stderr else "unknown error"
        logger.error(
            "run_agent_failed",
            agent=agent,
            returncode=proc.returncode,
            stderr=error_msg[:500],
        )
        return AgentResult(
            output="",
            summary="",
            variables={},
            success=False,
        )

    # Parse JSON from the last line of stdout
    stdout_text = stdout.decode()
    try:
        # The JSON result is the last line — everything before is progress
        lines = stdout_text.strip().split("\n")
        result_json = json.loads(lines[-1])
        return AgentResult(
            output=result_json.get("output", ""),
            summary=result_json.get("summary", ""),
            variables=result_json.get("variables", {}),
            success=result_json.get("success", False),
            tool_calls_used=result_json.get("toolCallsUsed", []),
        )
    except (json.JSONDecodeError, IndexError) as e:
        logger.error(
            "run_agent_parse_failed",
            agent=agent,
            error=str(e),
            stdout=stdout_text[-500:],
        )
        return AgentResult(
            output=stdout_text,
            summary="",
            variables={},
            success=False,
        )
