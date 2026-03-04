"""Git HTTP proxy for sandbox credential isolation.

Sandboxes never receive git credentials. Instead, they clone via a proxy URL
with a session-scoped key. This endpoint forwards requests to the git host
(Gitea or future GitHub) with the appropriate auth injected.

Routes:
- ANY /git-proxy/{proxy_key}/{owner}/{repo_name}.git/{git_path} - Forward to git host
"""

import os

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session
import httpx
import structlog

from druppie.db.database import get_db
from druppie.repositories import SandboxSessionRepository

logger = structlog.get_logger()

router = APIRouter()

GITEA_INTERNAL_URL = os.getenv("GITEA_INTERNAL_URL", os.getenv("GITEA_URL", "http://gitea:3000"))
GITEA_ADMIN_USER = os.getenv("GITEA_ADMIN_USER", "gitea_admin")
GITEA_ADMIN_PASSWORD = os.getenv("GITEA_ADMIN_PASSWORD", "")
MAX_GIT_BODY_SIZE = 100 * 1024 * 1024  # 100 MB

# Whitelist of allowed git protocol paths to prevent path traversal attacks
# These are the standard git smart HTTP protocol endpoints
ALLOWED_GIT_PATHS = {
    "info/refs",           # Ref discovery (both fetch and push)
    "git-upload-pack",     # Fetch (client pulls objects)
    "git-receive-pack",    # Push (client pushes objects)
}


def is_allowed_git_path(git_path: str) -> bool:
    """Check if the git path is in the allowed whitelist.
    
    Git protocol paths can be:
    - info/refs (possibly with ?service=git-upload-pack query)
    - git-upload-pack
    - git-receive-pack
    - objects/<hash-prefix>/<hash-suffix> (for dumb HTTP, not commonly used)
    
    We allow the smart HTTP protocol paths and object paths for compatibility.
    """
    # Normalize path
    git_path = git_path.strip("/")
    
    # Check exact match for smart HTTP endpoints
    if git_path in ALLOWED_GIT_PATHS:
        return True
    
    # Allow objects/ paths for git pack file retrieval
    # Format: objects/<2-char-prefix>/<38-char-suffix> or objects/pack/<filename>
    if git_path.startswith("objects/"):
        return True
    
    # Allow shallow info for partial clone support
    if git_path == "shallow":
        return True
    
    return False


@router.api_route(
    "/{proxy_key}/{owner}/{repo_name}.git/{git_path:path}",
    methods=["GET", "POST"],
)
async def git_proxy(
    proxy_key: str,
    owner: str,
    repo_name: str,
    git_path: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """Forward git HTTP protocol requests to the git host with injected auth.

    The proxy_key is the sole authentication — it maps to a SandboxSession
    that authorizes access to a specific repo.
    """
    repo = SandboxSessionRepository(db)
    session = repo.get_by_proxy_key(proxy_key)

    if not session:
        logger.warning("git_proxy_invalid_key", proxy_key=proxy_key[:8] + "...")
        raise HTTPException(status_code=403, detail="Invalid or expired proxy key")

    # Verify the requested repo matches what this key authorizes
    if session.git_repo_owner != owner or session.git_repo_name != repo_name:
        logger.warning(
            "git_proxy_repo_mismatch",
            proxy_key=proxy_key[:8] + "...",
            requested=f"{owner}/{repo_name}",
            authorized=f"{session.git_repo_owner}/{session.git_repo_name}",
        )
        raise HTTPException(status_code=403, detail="Proxy key not authorized for this repo")

    # Validate git path against whitelist to prevent path traversal attacks
    if not is_allowed_git_path(git_path):
        logger.warning(
            "git_proxy_invalid_path",
            proxy_key=proxy_key[:8] + "...",
            git_path=git_path,
        )
        raise HTTPException(status_code=403, detail="Git path not allowed")

    # Build target URL based on provider
    if session.git_provider == "github":
        # Future: forward to https://github.com with GitHub App token
        raise HTTPException(status_code=501, detail="GitHub proxy not yet implemented")

    # Default: Gitea
    target_url = f"{GITEA_INTERNAL_URL}/{owner}/{repo_name}.git/{git_path}"

    # Forward query string (e.g., ?service=git-upload-pack)
    if request.url.query:
        target_url += f"?{request.url.query}"

    # Reject oversized payloads to prevent memory exhaustion
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_GIT_BODY_SIZE:
                raise HTTPException(status_code=413, detail="Request body too large")
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid content-length header")

    # Forward the request to Gitea with admin auth
    body = await request.body()
    if len(body) > MAX_GIT_BODY_SIZE:
        raise HTTPException(status_code=413, detail="Request body too large")

    # Auth: admin credentials are used because the system has no per-user Gitea
    # accounts. The security boundary is the proxy key + repo-scoping above —
    # each sandbox can only reach the single repo its session authorizes.
    # TODO: use per-user Gitea tokens once user-level Gitea accounts are added.
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.request(
            method=request.method,
            url=target_url,
            content=body,
            auth=(GITEA_ADMIN_USER, GITEA_ADMIN_PASSWORD),
            headers={
                k: v
                for k, v in request.headers.items()
                if k.lower() in ("content-type", "accept", "git-protocol")
            },
        )

    logger.debug(
        "git_proxy_request",
        method=request.method,
        git_path=git_path,
        repo=f"{owner}/{repo_name}",
        status=resp.status_code,
    )

    return Response(
        content=resp.content,
        status_code=resp.status_code,
        headers={
            k: v
            for k, v in resp.headers.items()
            if k.lower() in ("content-type", "content-length", "cache-control", "pragma")
        },
    )
