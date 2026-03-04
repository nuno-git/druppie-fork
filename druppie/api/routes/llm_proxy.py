"""LLM API proxy for sandbox credential isolation.

Sandboxes never receive LLM API keys. Instead, they call via a proxy URL
with a session-scoped key. This endpoint forwards requests to the LLM provider
with the appropriate API key injected.

This prevents API key exfiltration from sandbox containers.

Routes:
- ANY /llm-proxy/{proxy_key}/{provider} - Forward to LLM provider
"""

import os
import time
import hmac
import hashlib
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session
import httpx
import structlog

from druppie.db.database import get_db
from druppie.repositories import SandboxSessionRepository

logger = structlog.get_logger()

router = APIRouter()

# LLM provider configuration
LLM_PROVIDERS = {
    "zai": {
        "base_url": os.getenv("ZAI_BASE_URL", "https://api.z.ai/api/coding/paas/v4"),
        "api_key_env": "ZAI_API_KEY",
    },
    "deepseek": {
        "base_url": os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
        "api_key_env": "DEEPSEEK_API_KEY",
    },
    "deepinfra": {
        "base_url": os.getenv("DEEPINFRA_BASE_URL", "https://api.deepinfra.com/v1/openai"),
        "api_key_env": "DEEPINFRA_API_KEY",
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "api_key_env": "OPENAI_API_KEY",
    },
    "anthropic": {
        "base_url": "https://api.anthropic.com/v1",
        "api_key_env": "ANTHROPIC_API_KEY",
    },
}

MAX_LLM_BODY_SIZE = 10 * 1024 * 1024  # 10 MB


def _verify_proxy_key(proxy_key: str, db: Session) -> tuple[UUID, str] | None:
    """Verify the proxy key and return (tool_call_id, provider) if valid.
    
    The proxy key format is: {timestamp}.{hmac}
    where HMAC is computed over the sandbox session ID.
    """
    sandbox_repo = SandboxSessionRepository(db)
    session = sandbox_repo.get_by_llm_proxy_key(proxy_key)
    
    if not session:
        return None
    
    return (session.tool_call_id, session.llm_provider or "zai")


@router.api_route(
    "/{proxy_key}/{provider}/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE"],
)
async def llm_proxy(
    proxy_key: str,
    provider: str,
    path: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """Forward LLM API requests to the provider with injected API key.

    The proxy_key maps to a SandboxSession that authorizes access.
    The provider must match what was configured for the session.
    """
    # Verify proxy key
    result = _verify_proxy_key(proxy_key, db)
    if not result:
        logger.warning("llm_proxy_invalid_key", proxy_key=proxy_key[:8] + "...")
        raise HTTPException(status_code=403, detail="Invalid or expired proxy key")
    
    tool_call_id, allowed_provider = result
    
    # Verify provider matches what's allowed for this session
    if provider != allowed_provider:
        logger.warning(
            "llm_proxy_provider_mismatch",
            proxy_key=proxy_key[:8] + "...",
            requested=provider,
            allowed=allowed_provider,
        )
        raise HTTPException(status_code=403, detail="Provider not allowed for this session")
    
    # Get provider config
    provider_config = LLM_PROVIDERS.get(provider)
    if not provider_config:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {provider}")
    
    api_key = os.getenv(provider_config["api_key_env"])
    if not api_key:
        logger.error(f"llm_proxy_missing_key", provider=provider)
        raise HTTPException(status_code=503, detail=f"Provider {provider} not configured")
    
    # Build target URL
    base_url = provider_config["base_url"].rstrip("/")
    target_url = f"{base_url}/{path}"
    
    # Forward query string
    if request.url.query:
        target_url += f"?{request.url.query}"
    
    # Reject oversized payloads
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_LLM_BODY_SIZE:
                raise HTTPException(status_code=413, detail="Request body too large")
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid content-length header")
    
    # Get request body
    body = await request.body()
    if len(body) > MAX_LLM_BODY_SIZE:
        raise HTTPException(status_code=413, detail="Request body too large")
    
    # Build headers with API key injected
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    
    # Provider-specific auth headers
    if provider == "anthropic":
        headers["x-api-key"] = api_key
        headers["anthropic-version"] = "2023-06-01"
    else:
        # OpenAI-compatible providers use Authorization header
        headers["Authorization"] = f"Bearer {api_key}"
    
    # Forward other relevant headers
    for h in ["accept-encoding", "user-agent"]:
        if h in request.headers:
            headers[h] = request.headers[h]
    
    # Make the request
    timeout = httpx.Timeout(connect=30.0, read=300.0, write=30.0, pool=30.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            resp = await client.request(
                method=request.method,
                url=target_url,
                content=body,
                headers=headers,
            )
        except httpx.RequestError as e:
            logger.error("llm_proxy_request_error", error=str(e), provider=provider)
            raise HTTPException(status_code=502, detail=f"Provider {provider} unavailable")
    
    logger.debug(
        "llm_proxy_request",
        method=request.method,
        provider=provider,
        path=path,
        status=resp.status_code,
    )
    
    # Return response
    return Response(
        content=resp.content,
        status_code=resp.status_code,
        headers={
            k: v
            for k, v in resp.headers.items()
            if k.lower() in ("content-type", "content-length", "cache-control")
        },
    )
