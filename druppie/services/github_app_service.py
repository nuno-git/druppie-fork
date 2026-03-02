"""GitHub App token service for authenticating as a GitHub App installation.

Generates short-lived installation access tokens that agents use to push code
and create PRs on GitHub repos (specifically nuno-git/druppie-fork for update_core).

The service is disabled (returns None) when env vars are not set, so it never
breaks existing Gitea-only flows.
"""

import time
from datetime import datetime

import jwt  # PyJWT — already in requirements.txt as pyjwt[crypto]
import httpx
import structlog

from druppie.core.config import get_settings

logger = structlog.get_logger()


class GitHubAppService:
    """Generates GitHub App installation access tokens.

    Reads config from settings.github_app (env vars with GITHUB_APP_ prefix):
      - GITHUB_APP_ID: numeric app ID from GitHub
      - GITHUB_APP_PRIVATE_KEY_PATH: path to the .pem private key file
      - GITHUB_APP_INSTALLATION_ID: numeric installation ID on the target org/repo

    If any are missing, the service is disabled — get_installation_token() returns None.
    """

    def __init__(self):
        # Load GitHub App config from the central settings (reads GITHUB_APP_* env vars)
        config = get_settings().github_app

        # Store the app ID and installation ID for JWT generation and API calls
        self._app_id: str = config.id
        self._installation_id: str = config.installation_id

        # Cached installation token and its expiry timestamp (epoch seconds)
        self._cached_token: str | None = None
        self._token_expires_at: float = 0.0

        # Load the private key from disk once at init, so we fail fast if the path is wrong
        self._private_key: str | None = None
        if config.private_key_path:
            try:
                with open(config.private_key_path) as f:
                    # Read the PEM file contents — PyJWT needs the raw PEM string
                    self._private_key = f.read()
                logger.info("github_app_private_key_loaded", path=config.private_key_path)
            except FileNotFoundError:
                # Log a warning but don't crash — the service will be disabled
                logger.warning("github_app_private_key_not_found", path=config.private_key_path)

        # Service is enabled only when all three config values are present AND key loaded
        self._enabled = config.is_configured and self._private_key is not None

        if self._enabled:
            logger.info("github_app_service_enabled", app_id=self._app_id)
        else:
            # This is expected in dev environments without GitHub App setup
            logger.info("github_app_service_disabled", reason="missing env vars or private key")

    @property
    def enabled(self) -> bool:
        """Whether the service is configured and ready to generate tokens."""
        return self._enabled

    def _generate_jwt(self) -> str:
        """Generate a short-lived JWT signed with the app's private key.

        GitHub requires RS256-signed JWTs with:
        - iss: the app ID
        - iat: issued-at timestamp (60 seconds in the past to account for clock drift)
        - exp: expiration timestamp (10 minutes max, we use 9 to be safe)

        Returns the encoded JWT string.
        """
        now = int(time.time())

        payload = {
            # iss (issuer) must be the GitHub App ID as a string
            "iss": self._app_id,
            # iat (issued at) — 60 seconds in the past for clock drift tolerance
            "iat": now - 60,
            # exp (expiration) — 9 minutes from now (GitHub max is 10)
            "exp": now + (9 * 60),
        }

        # Sign with RS256 using the private key from the PEM file
        return jwt.encode(payload, self._private_key, algorithm="RS256")

    async def _request_installation_token(self) -> tuple[str, float]:
        """Exchange a JWT for an installation access token via GitHub API.

        Calls POST /app/installations/{id}/access_tokens with the JWT as bearer auth.
        GitHub responds with a token and its expiry timestamp.

        Returns:
            Tuple of (token_string, expires_at_epoch_seconds)

        Raises:
            httpx.HTTPStatusError: if the GitHub API returns a non-2xx response
        """
        # Generate a fresh JWT for this request
        app_jwt = self._generate_jwt()

        async with httpx.AsyncClient() as client:
            # POST to GitHub's installation token endpoint
            response = await client.post(
                f"https://api.github.com/app/installations/{self._installation_id}/access_tokens",
                headers={
                    # Bearer auth with the JWT (not the installation token)
                    "Authorization": f"Bearer {app_jwt}",
                    # GitHub API versioning header
                    "Accept": "application/vnd.github+json",
                    # Recommended by GitHub for API requests
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
            # Raise an exception for 4xx/5xx responses
            response.raise_for_status()

        data = response.json()
        # The token string we'll use for git operations and API calls
        token = data["token"]
        # Parse the ISO 8601 expiry into epoch seconds for easy comparison
        # GitHub tokens last 1 hour; we'll refresh at 55 minutes (see get_installation_token)
        expires_at_str = data["expires_at"]

        # Convert ISO 8601 timestamp (e.g. "2024-01-01T00:00:00Z") to epoch seconds
        expires_at = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00")).timestamp()

        logger.info(
            "github_installation_token_created",
            expires_at=expires_at_str,
        )

        return token, expires_at

    async def get_installation_token(self) -> str | None:
        """Get a valid installation access token, refreshing if needed.

        This is the only public method. Returns None if the service is disabled.

        Caching strategy:
        - Tokens last 1 hour (GitHub default)
        - We refresh 5 minutes before expiry to avoid using an expired token
        - If no cached token exists, we request a new one
        """
        # If service is disabled, return None — callers must handle this gracefully
        if not self._enabled:
            return None

        # Check if cached token is still valid (with 5-minute safety margin)
        now = time.time()
        if self._cached_token and now < (self._token_expires_at - 300):
            # Token is still fresh — reuse it
            return self._cached_token

        # Token is expired or doesn't exist — request a new one
        try:
            token, expires_at = await self._request_installation_token()
            # Cache the new token and its expiry for future calls
            self._cached_token = token
            self._token_expires_at = expires_at
            return token
        except Exception as e:
            # Log the error but don't crash — return None so callers can handle it
            logger.error("github_installation_token_failed", error=str(e))
            return None


# Module-level singleton — created once, reused across requests
_instance: GitHubAppService | None = None


def get_github_app_service() -> GitHubAppService:
    """Get or create the singleton GitHubAppService instance.

    Using a singleton because the service loads a private key from disk
    and caches tokens — we don't want to re-read the key on every request.
    """
    global _instance
    if _instance is None:
        _instance = GitHubAppService()
    return _instance
