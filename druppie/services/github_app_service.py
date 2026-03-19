"""GitHub App token service — generates short-lived installation access tokens.

Used by update_core_builder agent to authenticate sandbox agents against GitHub repos.
Disabled (returns None) when env vars are not set.
"""

import asyncio
import time
from datetime import datetime

import jwt
import httpx
import structlog

from druppie.core.config import get_settings

logger = structlog.get_logger()


class GitHubAppService:
    """Generates GitHub App installation access tokens.

    Config from env: GITHUB_APP_ID, GITHUB_APP_PRIVATE_KEY_PATH, GITHUB_APP_INSTALLATION_ID.
    If any are missing, the service is disabled — get_installation_token() returns None.
    """

    def __init__(self):
        config = get_settings().github_app

        self._app_id: str = config.id
        self._installation_id: str = config.installation_id
        self._cached_token: str | None = None
        self._token_expires_at: float = 0.0
        self._refresh_lock = asyncio.Lock()

        self._private_key: str | None = None
        if config.private_key_path:
            try:
                with open(config.private_key_path) as f:
                    self._private_key = f.read()
                logger.info("github_app_private_key_loaded", path=config.private_key_path)
            except FileNotFoundError:
                logger.warning("github_app_private_key_not_found", path=config.private_key_path)

        self._enabled = config.is_configured and self._private_key is not None

        if self._enabled:
            logger.info("github_app_service_enabled", app_id=self._app_id)
        else:
            logger.info("github_app_service_disabled", reason="missing env vars or private key")

    @property
    def enabled(self) -> bool:
        return self._enabled

    def _generate_jwt(self) -> str:
        """Generate RS256 JWT for GitHub App authentication."""
        now = int(time.time())
        payload = {
            "iss": self._app_id,
            "iat": now - 60,
            "exp": now + (9 * 60),
        }
        return jwt.encode(payload, self._private_key, algorithm="RS256")

    async def _request_installation_token(self) -> tuple[str, float]:
        """Exchange JWT for an installation access token via GitHub API."""
        app_jwt = self._generate_jwt()

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"https://api.github.com/app/installations/{self._installation_id}/access_tokens",
                headers={
                    "Authorization": f"Bearer {app_jwt}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
            response.raise_for_status()

        data = response.json()
        token = data["token"]
        expires_at = datetime.fromisoformat(data["expires_at"].replace("Z", "+00:00")).timestamp()

        logger.info("github_installation_token_created", expires_at=data["expires_at"])
        return token, expires_at

    async def get_installation_token(self) -> str | None:
        """Get a valid installation token, refreshing if needed. Returns None if disabled."""
        if not self._enabled:
            return None

        if self._cached_token and time.time() < (self._token_expires_at - 300):
            return self._cached_token

        async with self._refresh_lock:
            # Re-check after acquiring lock (another coroutine may have refreshed)
            if self._cached_token and time.time() < (self._token_expires_at - 300):
                return self._cached_token

            try:
                token, expires_at = await self._request_installation_token()
                self._cached_token = token
                self._token_expires_at = expires_at
                return token
            except Exception as e:
                logger.error("github_installation_token_failed", error=str(e))
                return None


_instance: GitHubAppService | None = None


def get_github_app_service() -> GitHubAppService:
    """Get or create the singleton GitHubAppService."""
    global _instance
    if _instance is None:
        _instance = GitHubAppService()
    return _instance
