"""Subprocess runner for the vendored pi_agent (execute_coding_task_pi).

The pi_agent is a Node/TypeScript orchestrator copied into ``pi_agent/`` at
the repo root. Each run spawns ``node pi_agent/dist/cli.js run-agent --agent <name> --prompt <text>``
as a child of the druppie backend container and streams its journal events
back over HTTP to ``/api/pi-agent-runs/{run_id}/events`` (see
``druppie/api/routes/pi_agent.py``). When the child exits it writes a
``summary.json`` which we ingest into the ``PiCodingRun`` row.

Parallelism: every call spawns an independent Node subprocess; inside each
subprocess pi_agent spawns its own sysbox/kata sandbox container. N concurrent
execute_coding_task_pi calls = N node processes + N sandboxes.

The backend container already has node + npm + docker.io (see Dockerfile),
so no extra container is required. If that ever changes, this module is the
only switch point: swap ``asyncio.create_subprocess_exec`` for a call into a
dedicated ``pi-agent`` container.
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import tempfile
import signal
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4
from typing import Dict

import structlog

logger = structlog.get_logger()

# Registry to track running processes for cancellation
_RUNNING_PROCESSES: Dict[str, asyncio.subprocess.Process] = {}

PI_AGENT_ROOT = Path(os.getenv("PI_AGENT_ROOT", "/app/pi_agent"))
PI_AGENT_CLI = PI_AGENT_ROOT / "dist" / "cli.js"
PI_AGENT_SESSIONS_DIR = Path(os.getenv("PI_AGENT_SESSIONS_DIR", "/app/pi_agent_sessions"))
DRUPPIE_INTERNAL_URL = os.getenv("DRUPPIE_INTERNAL_URL", "http://localhost:8000")

# Cap stdout/stderr kept in DB so a runaway log doesn't blow up Postgres.
_TAIL_BYTES = 64 * 1024


# ═══════════════════════════════════════════════════════════════════════════════
# Process Registry - for cancellation
# ═══════════════════════════════════════════════════════════════════════════════

def register_process(run_id: str, proc: asyncio.subprocess.Process) -> None:
    """Register a running process so it can be cancelled later."""
    _RUNNING_PROCESSES[run_id] = proc
    logger.info("pi_agent_process_registered", run_id=run_id, pid=proc.pid)


def unregister_process(run_id: str) -> None:
    """Unregister a process (call when it completes)."""
    _RUNNING_PROCESSES.pop(run_id, None)
    logger.info("pi_agent_process_unregistered", run_id=run_id)


async def stop_run(run_id: str) -> dict:
    """Stop a running pi_agent process.

    Attempts graceful termination first, then force kills if needed.

    Returns:
        Dict with success status and message
    """
    proc = _RUNNING_PROCESSES.get(run_id)
    if not proc:
        return {
            "success": False,
            "message": f"No running process found for run_id: {run_id}",
        }

    try:
        # Try graceful termination first
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=5.0)
            unregister_process(run_id)
            return {
                "success": True,
                "message": f"Process {run_id} terminated gracefully",
            }
        except asyncio.TimeoutError:
            # Force kill if graceful termination didn't work
            proc.kill()
            await proc.wait()
            unregister_process(run_id)
            return {
                "success": True,
                "message": f"Process {run_id} killed (didn't respond to SIGTERM)",
            }
    except Exception as e:
        logger.error("failed_to_stop_pi_agent_process", run_id=run_id, error=str(e))
        return {
            "success": False,
            "message": f"Failed to stop process {run_id}: {str(e)}",
        }


def list_running_runs() -> list[str]:
    """List all currently running pi_agent run IDs."""
    return list(_RUNNING_PROCESSES.keys())


class PiAgentRunner:
    """Launches a pi_agent Node subprocess, ingests its summary, updates the DB row."""

    def __init__(
        self,
        run_id: str,
        task_prompt: str,
        agent_name: str | None,
        repo_target: str,
        git_provider: str,
        repo_owner: str,
        repo_name: str,
        git_credentials: dict,
        llm_credentials: dict,
        source_branch: str | None = None,
        sandbox_image: str | None = None,
    ):
        self.run_id = run_id
        self.task_prompt = task_prompt
        self.agent_name = agent_name
        self.repo_target = repo_target
        self.git_provider = git_provider
        self.repo_owner = repo_owner
        self.repo_name = repo_name
        self.git_credentials = git_credentials
        self.llm_credentials = llm_credentials
        self.source_branch = source_branch
        self.sandbox_image = sandbox_image or os.getenv("PI_AGENT_SANDBOX_IMAGE", "oneshot-sandbox:latest")

        PI_AGENT_SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        self.session_dir = PI_AGENT_SESSIONS_DIR / run_id
        self.session_dir.mkdir(parents=True, exist_ok=True)

    def _write_task_file(self) -> Path:
        task_spec = {
            "description": self.task_prompt,
            "language": "typescript",
        }
        task_path = self.session_dir / "task.json"
        task_path.write_text(json.dumps(task_spec))
        return task_path

    def _build_env(self, ingest_token: str) -> dict:
        env = os.environ.copy()
        env["PI_AGENT_RUN_ID"] = self.run_id
        env["PI_AGENT_INGEST_URL"] = f"{DRUPPIE_INTERNAL_URL}/api/pi-agent-runs/{self.run_id}/events"
        env["PI_AGENT_INGEST_TOKEN"] = ingest_token
        env["PI_AGENT_GIT_PROVIDER"] = self.git_provider
        env["PI_AGENT_REPO_TARGET"] = self.repo_target

        if self.git_provider == "github_app":
            # pi_agent's github/app.ts reads GITHUB_APP_ID, GITHUB_APP_INSTALLATION_ID,
            # GITHUB_APP_PRIVATE_KEY_PATH directly from env. Those vars are already
            # set on the backend container (docker-compose.yml) and the PEM is
            # bind-mounted at /app/secrets/github-app-private-key.pem. Inherited
            # here via os.environ.copy() — no extra wiring needed.
            env.pop("GITHUB_TOKEN", None)  # don't let a PAT shadow App auth
        elif self.git_provider == "gitea":
            env["GITEA_BASE_URL"] = self.git_credentials.get("base_url", os.getenv("GITEA_INTERNAL_URL", ""))
            env["GITEA_USERNAME"] = self.git_credentials.get("username", "")
            env["GITEA_TOKEN"] = self.git_credentials.get("password", "")
        else:
            raise ValueError(f"Unsupported git_provider: {self.git_provider}")

        if self.llm_credentials.get("anthropic_api_key"):
            env["ANTHROPIC_API_KEY"] = self.llm_credentials["anthropic_api_key"]
        if self.llm_credentials.get("zai_api_key"):
            env["ZAI_API_KEY"] = self.llm_credentials["zai_api_key"]

        env["PI_AGENT_SANDBOX_IMAGE"] = self.sandbox_image
        # Default the sandbox runtime to sysbox-runc for dev/single-tenant hosts
        # (Kata requires nested virt and explicit install). Overridable by
        # setting ONESHOT_SANDBOX_RUNTIME in the backend container's env —
        # prod hosts with Kata registered just pin it there.
        env.setdefault("ONESHOT_SANDBOX_RUNTIME", "sysbox-runc")
        # Attach each spawned sandbox to the same docker network as the
        # backend container. pi_agent then talks to the sandbox by container
        # name on the internal bridge — no port publishing, no 127.0.0.1
        # games across container boundaries. Backend must be on this network
        # too (docker-compose.yml wires it).
        env.setdefault("PI_AGENT_SANDBOX_NETWORK", "druppie-new-network")
        # Bundle output via a named volume mounted on both backend and each
        # sandbox. Host bind-mounts don't work when pi_agent runs inside
        # backend (the path is resolved against the host fs, which doesn't
        # have the in-container temp dir).
        env.setdefault("PI_AGENT_BUNDLE_VOLUME", "druppie_pi_agent_bundles")
        return env

    async def run(self, ingest_token: str) -> dict:
        self._write_task_file()  # kept for backward compat; CLI no longer reads it
        env = self._build_env(ingest_token)

        repo_url = self._build_repo_url()

        agent_name = self.agent_name
        if agent_name == "tdd":
            agent_name = "planner"
        elif agent_name == "explore":
            agent_name = "router"

        cmd = [
            "node", str(PI_AGENT_CLI),
            "run-agent",
            "--agent", agent_name,
            "--prompt", self.task_prompt,
            "--workdir", str(self.session_dir),
            "--sandbox-launch",
            "--source-repo", repo_url,
        ]
        if self.source_branch:
            cmd += ["--source-branch", self.source_branch]
        if self.sandbox_image:
            cmd += ["--sandbox-image", self.sandbox_image]
        if self.llm_credentials.get("zai_api_key"):
            cmd += ["--glm-key", self.llm_credentials["zai_api_key"]]
        elif self.llm_credentials.get("anthropic_api_key"):
            cmd += ["--api-key", self.llm_credentials["anthropic_api_key"]]

        push_token = self.git_credentials.get("password") or self.git_credentials.get("token")
        if push_token:
            cmd += ["--push-token", push_token]

        cmd += ["--ingest-url", env.get("PI_AGENT_INGEST_URL", "")]
        cmd += ["--ingest-token", ingest_token]
        cmd += ["--ingest-run-id", self.run_id]

        logger.info("pi_agent_subprocess_start", run_id=self.run_id, cmd=cmd[:3])
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            cwd=str(PI_AGENT_ROOT),
        )

        # Register the process so it can be cancelled
        register_process(self.run_id, proc)

        try:
            stdout_b, stderr_b = await proc.communicate()
            exit_code = proc.returncode or 0

            stdout_text = stdout_b.decode("utf-8", errors="replace") if stdout_b else ""
            stderr_tail = stderr_b[-_TAIL_BYTES:].decode("utf-8", errors="replace") if stderr_b else ""

            # Parse SingleAgentResult from stdout (always available)
            stdout_result = self._parse_stdout_result(stdout_text)

            # Try to load rich RunSummary from disk (journal.close() writes it)
            summary = self._load_summary()

            # If no disk summary, construct a basic one from stdout
            if summary is None and stdout_result is not None:
                summary = {
                    "success": stdout_result.get("success", False),
                    "errors": [] if stdout_result.get("success") else [
                        stdout_result.get("output", "Agent reported failure")[:500]
                    ],
                    "narratives": [],
                    "commits": [],
                    "push": None,
                    "pr": None,
                }
            elif summary is None:
                if exit_code != 0:
                    summary = {
                        "success": False,
                        "errors": [f"Agent exited with code {exit_code}"],
                        "narratives": [],
                        "commits": [],
                        "push": None,
                        "pr": None,
                    }
                else:
                    summary = {
                        "success": False,
                        "errors": ["Agent exited with code 0 but produced no summary"],
                        "narratives": [],
                        "commits": [],
                        "push": None,
                        "pr": None,
                    }

            stdout_tail = stdout_text[-_TAIL_BYTES:]

            logger.info(
                "pi_agent_subprocess_exit",
                run_id=self.run_id,
                exit_code=exit_code,
                has_summary=summary is not None,
            )

            return {
                "exit_code": exit_code,
                "summary": summary,
                "stdout_tail": stdout_tail,
                "stderr_tail": stderr_tail,
                "variables": (stdout_result or {}).get("variables", {}),
            }
        finally:
            # Always unregister the process, even on error
            unregister_process(self.run_id)

    def _build_repo_url(self) -> str:
        """Plain HTTPS URL — pi_agent's source-clone.ts calls
        injectTokenIntoHttpsUrl(url, token) to weave in auth just before cloning,
        using the token it mints (GitHub) or reads from env (Gitea)."""
        if self.git_provider == "github_app":
            return f"https://github.com/{self.repo_owner}/{self.repo_name}.git"
        base = self.git_credentials.get("base_url") or os.getenv("GITEA_INTERNAL_URL", "")
        base = base.rstrip("/")
        return f"{base}/{self.repo_owner}/{self.repo_name}.git"

    def _parse_stdout_result(self, stdout_text: str) -> dict | None:
        """Parse SingleAgentResult JSON from the last line of stdout.

        The CLI (cli.ts) writes: process.stdout.write(JSON.stringify(result) + "\\n")
        where result is {output, summary, variables, success, toolCallsUsed}.
        """
        try:
            lines = stdout_text.strip().split("\n")
            if lines:
                return json.loads(lines[-1])
        except (json.JSONDecodeError, IndexError):
            pass
        return None

    def _load_summary(self) -> dict | None:
        """Load RunSummary from the journal directory.

        Two possible locations:
        1. PI_AGENT_ROOT/dist/sessions/runs/<timestamp>/
        or PI_AGENT_ROOT/sessions/runs/
        (not self.session_dir which is PI_AGENT_SESSIONS_DIR/<run_id>/).
        """
        # Check both possible journal directories
        candidates_dir = PI_AGENT_ROOT / "dist" / "sessions" / "runs"
        if candidates_dir.exists():
            summaries = sorted(
                candidates_dir.glob("*/summary.json"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            cutoff = time.time() - 300
            for candidate in summaries[:5]:
                if candidate.stat().st_mtime >= cutoff:
                    try:
                        return json.loads(candidate.read_text())
                    except json.JSONDecodeError:
                        continue
        # Fallback: PI_AGENT_ROOT/sessions/runs/<timestamp>/summary.json
        runs_dir = PI_AGENT_ROOT / "sessions" / "runs"
        if runs_dir.exists():
            # Find the most recent summary (journal dirs are ISO-timestamped)
            summaries = sorted(
                runs_dir.glob("*/summary.json"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            # Pick the most recent one that was written within the last 5 minutes
            # (avoids picking up stale summaries from previous runs)
            cutoff = time.time() - 300
            for candidate in summaries[:5]:
                if candidate.stat().st_mtime >= cutoff:
                    try:
                        return json.loads(candidate.read_text())
                    except json.JSONDecodeError:
                        continue
        return None


def generate_ingest_token() -> str:
    return secrets.token_urlsafe(32)
