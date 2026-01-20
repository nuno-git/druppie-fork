"""Keycloak authentication module."""

import os
from functools import wraps
from typing import Optional

import jwt
from jwt import PyJWKClient
import requests
from flask import current_app, g, jsonify, request


# Development mode user for bypassing Keycloak
DEV_USER = {
    "sub": "dev-user-001",
    "preferred_username": "developer",
    "email": "developer@localhost",
    "given_name": "Dev",
    "family_name": "User",
    "realm_access": {
        "roles": ["admin", "developer", "architect", "devops"]
    }
}


class KeycloakAuth:
    """Keycloak authentication handler."""

    def __init__(self, app=None):
        self.app = app
        self._jwk_client = None

        if app:
            self.init_app(app)

    def init_app(self, app):
        """Initialize with Flask app."""
        self.app = app

    @property
    def server_url(self) -> str:
        return current_app.config.get("KEYCLOAK_SERVER_URL", "http://localhost:8080")

    @property
    def issuer_url(self) -> str:
        return current_app.config.get("KEYCLOAK_ISSUER_URL", "http://localhost:8080")

    @property
    def realm(self) -> str:
        return current_app.config.get("KEYCLOAK_REALM", "druppie")

    @property
    def issuer(self) -> str:
        return f"{self.issuer_url}/realms/{self.realm}"

    @property
    def certs_url(self) -> str:
        return f"{self.server_url}/realms/{self.realm}/protocol/openid-connect/certs"

    def is_available(self) -> bool:
        """Check if Keycloak is available."""
        try:
            response = requests.get(
                f"{self.server_url}/realms/{self.realm}/.well-known/openid-configuration",
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

    def decode_token(self, token: str) -> Optional[dict]:
        """Decode and verify a JWT token."""
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
            return None
        except jwt.InvalidTokenError:
            return None
        except Exception:
            return None

    def get_token_from_request(self) -> Optional[str]:
        """Extract token from Authorization header."""
        auth_header = request.headers.get("Authorization", "")

        if auth_header.startswith("Bearer "):
            return auth_header[7:]

        return None


# Global auth instance
_auth = None


def get_auth() -> KeycloakAuth:
    """Get the global auth instance."""
    global _auth
    if _auth is None:
        _auth = KeycloakAuth()
    return _auth


def auth_required(f):
    """Decorator to require authentication."""

    @wraps(f)
    def decorated(*args, **kwargs):
        # Check for development mode bypass
        dev_mode = current_app.config.get("DEV_MODE", False)
        if dev_mode:
            g.user = DEV_USER
            return f(*args, **kwargs)

        auth = get_auth()

        token = auth.get_token_from_request()
        if not token:
            return jsonify({"error": "No authorization token provided"}), 401

        user = auth.decode_token(token)
        if not user:
            return jsonify({"error": "Invalid or expired token"}), 401

        g.user = user
        return f(*args, **kwargs)

    return decorated


def role_required(role: str):
    """Decorator to require a specific role."""

    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if not hasattr(g, "user"):
                return jsonify({"error": "Authentication required"}), 401

            roles = g.user.get("realm_access", {}).get("roles", [])

            if role not in roles and "admin" not in roles:
                return jsonify({"error": f"Role '{role}' required"}), 403

            return f(*args, **kwargs)

        return decorated

    return decorator


def any_role_required(*required_roles):
    """Decorator to require any of the specified roles."""

    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if not hasattr(g, "user"):
                return jsonify({"error": "Authentication required"}), 401

            user_roles = g.user.get("realm_access", {}).get("roles", [])

            # Admin can do anything
            if "admin" in user_roles:
                return f(*args, **kwargs)

            # Check if user has any of the required roles
            if not any(r in user_roles for r in required_roles):
                return (
                    jsonify({"error": f"One of these roles required: {required_roles}"}),
                    403,
                )

            return f(*args, **kwargs)

        return decorated

    return decorator
