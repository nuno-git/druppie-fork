"""Authentication module for Druppie platform.

Supports Keycloak JWT validation and development mode bypass.
"""

import os
from typing import Any

import jwt
from jwt import PyJWKClient
import httpx
import structlog

logger = structlog.get_logger()


# Development mode user for bypassing Keycloak
DEV_USER = {
    "sub": "dev-user-001",
    "preferred_username": "developer",
    "email": "developer@localhost",
    "given_name": "Dev",
    "family_name": "User",
    "realm_access": {"roles": ["admin", "developer", "architect", "devops"]},
}


class AuthService:
    """Authentication service supporting Keycloak and dev mode."""

    def __init__(
        self,
        keycloak_url: str | None = None,
        keycloak_realm: str = "druppie",
        dev_mode: bool = False,
    ):
        """Initialize auth service.

        Args:
            keycloak_url: Base URL for Keycloak server
            keycloak_realm: Keycloak realm name
            dev_mode: If True, bypass authentication
        """
        self.keycloak_url = keycloak_url or os.getenv(
            "KEYCLOAK_SERVER_URL", "http://localhost:8080"
        )
        self.keycloak_realm = keycloak_realm or os.getenv("KEYCLOAK_REALM", "druppie")

        # Dev mode security: refuse to enable in production environment
        environment = os.getenv("ENVIRONMENT", "development")
        dev_mode_requested = dev_mode or os.getenv("DEV_MODE", "false").lower() == "true"

        if dev_mode_requested and environment.lower() in ("production", "prod"):
            logger.warning(
                "dev_mode_blocked_in_production",
                message="DEV_MODE cannot be enabled in production environment",
                environment=environment,
            )
            self.dev_mode = False
        else:
            self.dev_mode = dev_mode_requested

        if self.dev_mode:
            logger.warning(
                "dev_mode_enabled",
                message="SECURITY WARNING: Dev mode enabled - authentication is bypassed!",
                environment=environment,
            )

        self._jwk_client: PyJWKClient | None = None

    @property
    def issuer(self) -> str:
        """Get the token issuer URL."""
        issuer_url = os.getenv("KEYCLOAK_ISSUER_URL", self.keycloak_url)
        return f"{issuer_url}/realms/{self.keycloak_realm}"

    @property
    def certs_url(self) -> str:
        """Get the JWKS URL for token verification."""
        return f"{self.keycloak_url}/realms/{self.keycloak_realm}/protocol/openid-connect/certs"

    def is_keycloak_available(self) -> bool:
        """Check if Keycloak is available."""
        try:
            response = httpx.get(
                f"{self.keycloak_url}/realms/{self.keycloak_realm}/.well-known/openid-configuration",
                timeout=5,
            )
            return response.status_code == 200
        except Exception:
            return False

    def get_jwk_client(self) -> PyJWKClient:
        """Get or create the JWK client for fetching signing keys."""
        if self._jwk_client is None:
            self._jwk_client = PyJWKClient(self.certs_url)
        return self._jwk_client

    def decode_token(self, token: str) -> dict[str, Any] | None:
        """Decode and verify a JWT token.

        Args:
            token: The JWT token string

        Returns:
            Decoded token payload or None if invalid
        """
        try:
            jwk_client = self.get_jwk_client()
            signing_key = jwk_client.get_signing_key_from_jwt(token)

            decoded = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                issuer=self.issuer,
                options={"verify_aud": False},
            )
            return decoded

        except jwt.ExpiredSignatureError:
            logger.warning("token_expired")
            return None
        except jwt.InvalidTokenError as e:
            logger.warning("token_invalid", error=str(e))
            return None
        except Exception as e:
            logger.error("token_decode_error", error=str(e), exc_info=True)
            return None

    def validate_request(self, authorization: str | None) -> dict[str, Any] | None:
        """Validate an authorization header.

        Args:
            authorization: The Authorization header value (e.g., "Bearer <token>")

        Returns:
            User info dict or None if authentication failed
        """
        # Try to decode real token first (even in dev mode)
        # This ensures user isolation works properly
        if authorization and authorization.startswith("Bearer "):
            token = authorization[7:]
            user = self.decode_token(token)
            if user:
                return user

        # Dev mode fallback - only if no valid token
        if self.dev_mode:
            logger.debug("dev_mode_auth_bypass")
            return DEV_USER

        return None

    def get_user_roles(self, user: dict[str, Any]) -> list[str]:
        """Extract roles from user info."""
        return user.get("realm_access", {}).get("roles", [])

    def has_role(self, user: dict[str, Any], role: str) -> bool:
        """Check if user has a specific role."""
        roles = self.get_user_roles(user)
        return role in roles or "admin" in roles

    def has_any_role(self, user: dict[str, Any], roles: list[str]) -> bool:
        """Check if user has any of the specified roles."""
        user_roles = self.get_user_roles(user)
        if "admin" in user_roles:
            return True
        return any(r in user_roles for r in roles)


# Default auth service instance
_auth_service: AuthService | None = None


def get_auth_service() -> AuthService:
    """Get the default auth service instance."""
    global _auth_service
    if _auth_service is None:
        _auth_service = AuthService()
    return _auth_service
