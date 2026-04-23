"""Subprocess runner for the vendored pi_agent (execute_coding_task_pi).

The pi_agent is a Node/TypeScript orchestrator copied into ``pi_agent/`` at
the repo root. Each run spawns ``node pi_agent/dist/cli.js --task <file>``
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
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import structlog

logger = structlog.get_logger()

PI_AGENT_ROOT = Path(os.getenv("PI_AGENT_ROOT", "/app/pi_agent"))
PI_AGENT_CLI = PI_AGENT_ROOT / "dist" / "cli.js"
PI_AGENT_SESSIONS_DIR = Path(os.getenv("PI_AGENT_SESSIONS_DIR", "/app/pi_agent_sessions"))
DRUPPIE_INTERNAL_URL = os.getenv("DRUPPIE_INTERNAL_URL", "http://localhost:8000")

# Cap stdout/stderr kept in DB so a runaway log doesn't blow up Postgres.
_TAIL_BYTES = 64 * 1024


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
        self.sandbox_image = sandbox_image or os.getenv("PI_AGENT_SANDBOX_IMAGE", "oneshot-tdd-agent-sandbox:latest")

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
        task_path = self._write_task_file()
        env = self._build_env(ingest_token)

        repo_url = self._build_repo_url()
        cmd = [
            "node", str(PI_AGENT_CLI),
            "--task", str(task_path),
            "--workdir", str(self.session_dir),
            "--source-repo", repo_url,
        ]
        if self.source_branch:
            cmd += ["--source-branch", self.source_branch]
        # agent_name doubles as the flow name ("tdd" | "explore"); CLI arg is --flow.
        if self.agent_name in ("tdd", "explore"):
            cmd += ["--flow", self.agent_name]

        logger.info("pi_agent_subprocess_start", run_id=self.run_id, cmd=cmd[:3])
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            cwd=str(PI_AGENT_ROOT),
        )
        stdout_b, stderr_b = await proc.communicate()
        exit_code = proc.returncode or 0

        summary = self._load_summary()
        stdout_tail = stdout_b[-_TAIL_BYTES:].decode("utf-8", errors="replace") if stdout_b else ""
        stderr_tail = stderr_b[-_TAIL_BYTES:].decode("utf-8", errors="replace") if stderr_b else ""

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
        }

    def _build_repo_url(self) -> str:
        """Plain HTTPS URL — pi_agent's source-clone.ts calls
        injectTokenIntoHttpsUrl(url, token) to weave in auth just before cloning,
        using the token it mints (GitHub) or reads from env (Gitea)."""
        if self.git_provider == "github_app":
            return f"https://github.com/{self.repo_owner}/{self.repo_name}.git"
        base = self.git_credentials.get("base_url") or os.getenv("GITEA_INTERNAL_URL", "")
        base = base.rstrip("/")
        return f"{base}/{self.repo_owner}/{self.repo_name}.git"

    def _load_summary(self) -> dict | None:
        """pi_agent writes summary.json into the session dir on close()."""
        for candidate in (
            self.session_dir / "summary.json",
            *self.session_dir.glob("*/summary.json"),
        ):
            if candidate.exists():
                try:
                    return json.loads(candidate.read_text())
                except json.JSONDecodeError:
                    continue
        return None


def generate_ingest_token() -> str:
    return secrets.token_urlsafe(32)
