"""Sandbox package — isolated execution environments for AI coding agents.

Provides:
- create_and_start_sandbox(): Create, register, and prompt a sandbox session
- credentials: Build LLM/Git credentials for control plane
- model_resolver: Resolve per-agent models from YAML config
"""

import os
import secrets
from pathlib import Path
from uuid import UUID

import httpx
import structlog

from druppie.core.sandbox_auth import generate_control_plane_token
from druppie.sandbox.credentials import build_llm_credentials
from druppie.sandbox.model_resolver import get_raw_model_chains, resolve_sandbox_models

logger = structlog.get_logger()

_AGENTS_DIR = Path(__file__).parent.parent / "sandbox-config" / "agents"


class SandboxCreateError(Exception):
    """Raised when sandbox creation or prompt sending fails."""

    pass


def _load_agent_files() -> dict[str, str]:
    """Load all .md agent files from sandbox-config/agents/ directory."""
    if _AGENTS_DIR.is_dir():
        return {f.stem: f.read_text() for f in _AGENTS_DIR.glob("*.md")}
    return {}


async def _build_github_git_credentials(repo_owner: str, repo_name: str) -> dict:
    """Build git credentials for GitHub using the GitHub App installation token.

    Returns the same dict format as create_sandbox_git_user() so the control plane
    credential store handles it identically.
    """
    from druppie.services.github_app_service import get_github_app_service

    service = get_github_app_service()
    if not service.enabled:
        raise SandboxCreateError("GitHub App is not configured — cannot create sandbox for GitHub repo")

    token = await service.get_installation_token()
    if not token:
        raise SandboxCreateError("Failed to obtain GitHub App installation token")

    return {
        "provider": "github",
        "url": "https://github.com",
        "username": "x-access-token",
        "password": token,
        "authorizedRepo": f"{repo_owner}/{repo_name}",
    }


async def create_and_start_sandbox(
    *,
    task_prompt: str,
    model: str,
    agent_name: str,
    repo_owner: str,
    repo_name: str,
    user_id: UUID,
    session_id: UUID | None,
    model_chain: str,
    model_chain_index: int,
    title: str,
    source: str,
    author_id: str,
    db,
    git_provider: str = "gitea",
    branch: str | None = None,
) -> dict:
    """Create a sandbox session on the control plane, register ownership, and send the prompt.

    This is the single source of truth for sandbox session creation, used by
    both the initial execute_coding_task path and the retry path.

    Args:
        task_prompt: The coding task prompt to send.
        model: Primary model profile (e.g. "sandbox/druppie-builder").
        agent_name: Sandbox agent name (e.g. "druppie-builder").
        repo_owner: Git repository owner.
        repo_name: Git repository name.
        user_id: Owner user UUID.
        session_id: Parent session UUID (optional).
        model_chain: JSON-serialized model chain for failover.
        model_chain_index: Current position in the model chain.
        title: Human-readable title for the sandbox session.
        source: Source identifier ("api" or "retry").
        author_id: Author identifier for the prompt.
        db: SQLAlchemy session.
        git_provider: "gitea" (default) or "github".
        branch: Target branch for git sync (default: repo's default branch).

    Returns:
        Dict with sandbox_session_id, message_id, webhook_secret, git_user_id, and git_provider.

    Raises:
        SandboxCreateError: If creation, registration, or prompt fails.
    """
    from druppie.repositories.sandbox_session_repository import SandboxSessionRepository

    control_plane_url = os.environ.get(
        "SANDBOX_CONTROL_PLANE_URL", "http://sandbox-control-plane:8787"
    ).rstrip("/")
    backend_url = os.environ.get("BACKEND_URL", "http://druppie-backend:8000")

    model_config = resolve_sandbox_models(agent_name)
    webhook_secret = secrets.token_urlsafe(32)

    # Build git credentials based on provider
    git_user_id = None
    delete_git_user = None  # cleanup function, only set for Gitea

    if git_provider == "github":
        scoped_git_creds = await _build_github_git_credentials(repo_owner, repo_name)
    else:
        from druppie.sandbox.gitea_credentials import create_sandbox_git_user, delete_sandbox_git_user
        git_user_id = secrets.token_hex(6)  # 12-char hex, used for Gitea username
        scoped_git_creds = await create_sandbox_git_user(
            sandbox_session_id=git_user_id,
            repo_owner=repo_owner,
            repo_name=repo_name,
        )
        delete_git_user = lambda: delete_sandbox_git_user(git_user_id)

    # Build credentials payload
    credentials: dict = {
        "git": scoped_git_creds,
        "llm": build_llm_credentials(),
    }

    # For GitHub repos, also provide GitHub API credentials so the sandbox
    # can use gh CLI / curl to create PRs, read issues, etc. via the proxy.
    if git_provider == "github":
        credentials["githubApi"] = {
            "token": scoped_git_creds["password"],  # Same GitHub App installation token
            "authorizedRepo": f"{repo_owner}/{repo_name}",
        }

    create_body = {
        "repoOwner": repo_owner,
        "repoName": repo_name,
        "model": model,
        "agentModels": model_config.agents,
        "agentFiles": _load_agent_files(),
        "modelChains": get_raw_model_chains(),
        "title": title,
        "credentials": credentials,
    }
    if branch:
        create_body["branch"] = branch

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            auth_headers = {
                "Authorization": f"Bearer {generate_control_plane_token()}",
                "Content-Type": "application/json",
            }

            # Step 1: Create sandbox session on control plane
            resp = await client.post(
                f"{control_plane_url}/sessions",
                json=create_body,
                headers=auth_headers,
            )

            if resp.status_code not in (200, 201):
                raise SandboxCreateError(
                    f"Control plane returned {resp.status_code}: {resp.text[:200]}"
                )

            sandbox_session_id = resp.json().get("sessionId")
            if not sandbox_session_id:
                raise SandboxCreateError("No sessionId in create response")

            logger.info(
                "sandbox_created",
                sandbox_session_id=sandbox_session_id,
                model=model,
                agent=agent_name,
                repo=f"{repo_owner}/{repo_name}",
                git_provider=git_provider,
            )

            # Step 2: Register ownership BEFORE sending the prompt.
            # Ownership must exist in the DB before the webhook can arrive,
            # otherwise it 403s and the session is stuck forever.
            try:
                sandbox_repo = SandboxSessionRepository(db)
                sandbox_repo.create(
                    sandbox_session_id=sandbox_session_id,
                    user_id=user_id,
                    session_id=session_id,
                    webhook_secret=webhook_secret,
                    model_chain=model_chain,
                    model_chain_index=model_chain_index,
                    task_prompt=task_prompt,
                    agent_name=agent_name,
                    git_user_id=git_user_id,
                    git_provider=git_provider,
                )
                db.flush()
            except Exception as e:
                # Cancel the orphaned sandbox on the control plane
                try:
                    await client.delete(
                        f"{control_plane_url}/sessions/{sandbox_session_id}",
                        headers=auth_headers,
                    )
                except Exception:
                    pass
                raise SandboxCreateError(f"Failed to register ownership: {e}") from e

            # Step 3: Send the task prompt with callback info
            callback_url = (
                f"{backend_url}/api/sandbox-sessions/{sandbox_session_id}/complete"
            )
            prompt_body = {
                "content": task_prompt,
                "authorId": author_id,
                "source": source,
                "agent": agent_name,
                "callbackUrl": callback_url,
                "callbackSecret": webhook_secret,
                "githubName": "druppie-core-bot",
                "githubEmail": "druppie-core-bot@users.noreply.github.com",
            }

            prompt_resp = await client.post(
                f"{control_plane_url}/sessions/{sandbox_session_id}/prompt",
                json=prompt_body,
                headers=auth_headers,
            )

            if prompt_resp.status_code not in (200, 201):
                # Cancel the orphaned sandbox
                try:
                    await client.delete(
                        f"{control_plane_url}/sessions/{sandbox_session_id}",
                        headers=auth_headers,
                    )
                except Exception:
                    pass
                raise SandboxCreateError(
                    f"Failed to send prompt: {prompt_resp.status_code}"
                )

            message_id = prompt_resp.json().get("messageId", "")

            logger.info(
                "sandbox_prompt_sent",
                sandbox_session_id=sandbox_session_id,
                message_id=message_id,
                source=source,
            )

            return {
                "sandbox_session_id": sandbox_session_id,
                "message_id": message_id,
                "webhook_secret": webhook_secret,
                "git_user_id": git_user_id,
                "git_provider": git_provider,
            }

    except SandboxCreateError:
        # Clean up the per-sandbox Gitea user on any creation failure
        if delete_git_user:
            try:
                await delete_git_user()
            except Exception:
                pass
        raise
    except httpx.TimeoutException as e:
        if delete_git_user:
            try:
                await delete_git_user()
            except Exception:
                pass
        raise SandboxCreateError(
            f"Timeout connecting to sandbox control plane: {e}"
        ) from e
    except Exception as e:
        if delete_git_user:
            try:
                await delete_git_user()
            except Exception:
                pass
        raise SandboxCreateError(f"Sandbox error: {e}") from e
