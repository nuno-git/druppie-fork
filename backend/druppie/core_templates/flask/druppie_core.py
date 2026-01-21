"""
Druppie Core - Flask Integration for Druppie Platform

Provides:
- Keycloak JWT authentication middleware
- MCP tool access through Druppie's governance layer
- Request authorization helpers
"""

import os
import functools
from typing import Any, Optional

import jwt
import requests
from flask import g, request, jsonify

# Druppie Platform Configuration
DRUPPIE_URL = os.getenv('DRUPPIE_URL', 'http://localhost:8000')
KEYCLOAK_URL = os.getenv('KEYCLOAK_URL', 'http://localhost:8080')
KEYCLOAK_REALM = os.getenv('KEYCLOAK_REALM', 'druppie')

# Cache for Keycloak public keys
_keycloak_keys = None


def get_keycloak_public_keys():
    """Fetch Keycloak public keys for JWT validation."""
    global _keycloak_keys
    if _keycloak_keys is None:
        try:
            certs_url = f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/certs"
            response = requests.get(certs_url, timeout=10)
            response.raise_for_status()
            _keycloak_keys = response.json()
        except Exception as e:
            print(f"Failed to fetch Keycloak keys: {e}")
            return None
    return _keycloak_keys


def decode_token(token: str) -> Optional[dict]:
    """Decode and validate a Keycloak JWT token."""
    try:
        # Get Keycloak public keys
        keys = get_keycloak_public_keys()
        if not keys:
            return None

        # Get the key ID from the token header
        unverified_header = jwt.get_unverified_header(token)
        kid = unverified_header.get('kid')

        # Find matching key
        public_key = None
        for key in keys.get('keys', []):
            if key.get('kid') == kid:
                public_key = jwt.algorithms.RSAAlgorithm.from_jwk(key)
                break

        if not public_key:
            return None

        # Decode and verify
        decoded = jwt.decode(
            token,
            public_key,
            algorithms=['RS256'],
            audience='account',
            options={"verify_aud": False}
        )
        return decoded

    except jwt.ExpiredSignatureError:
        print("Token expired")
        return None
    except jwt.InvalidTokenError as e:
        print(f"Invalid token: {e}")
        return None


def auth_required(f):
    """Decorator to require authentication on a route."""
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        # Get token from Authorization header
        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return jsonify({'error': 'Missing authorization token'}), 401

        token = auth_header[7:]  # Remove 'Bearer ' prefix
        user = decode_token(token)

        if not user:
            return jsonify({'error': 'Invalid or expired token'}), 401

        # Store user in Flask's g object
        g.user = user
        g.token = token
        return f(*args, **kwargs)

    return decorated


def role_required(*required_roles):
    """Decorator to require specific roles."""
    def decorator(f):
        @functools.wraps(f)
        @auth_required
        def decorated(*args, **kwargs):
            user_roles = g.user.get('realm_access', {}).get('roles', [])

            # Admin can do anything
            if 'admin' in user_roles:
                return f(*args, **kwargs)

            # Check if user has any required role
            if not any(role in user_roles for role in required_roles):
                return jsonify({
                    'error': 'Insufficient permissions',
                    'required_roles': list(required_roles)
                }), 403

            return f(*args, **kwargs)
        return decorated
    return decorator


class DruppieClient:
    """Client for interacting with Druppie Platform."""

    def __init__(self, base_url: str = None, token: str = None):
        """Initialize Druppie client.

        Args:
            base_url: Druppie API URL (default from DRUPPIE_URL env)
            token: Optional auth token for requests
        """
        self.base_url = base_url or DRUPPIE_URL
        self.token = token

    def _get_headers(self) -> dict:
        """Get headers for API requests."""
        headers = {'Content-Type': 'application/json'}
        # Use provided token or get from Flask g
        token = self.token or getattr(g, 'token', None)
        if token:
            headers['Authorization'] = f'Bearer {token}'
        return headers

    def check_permission(self, tool_name: str) -> dict:
        """Check if current user can execute a tool.

        Args:
            tool_name: Name of the MCP tool

        Returns:
            Permission check result
        """
        response = requests.post(
            f"{self.base_url}/api/mcp/check",
            json={'tool': tool_name},
            headers=self._get_headers(),
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    def execute_tool(self, tool_name: str, params: dict = None) -> dict:
        """Execute an MCP tool through Druppie governance.

        Args:
            tool_name: Name of the MCP tool
            params: Tool parameters

        Returns:
            Tool execution result
        """
        response = requests.post(
            f"{self.base_url}/api/mcp/execute",
            json={'tool': tool_name, 'params': params or {}},
            headers=self._get_headers(),
            timeout=60,
        )
        response.raise_for_status()
        return response.json()

    def create_plan(self, name: str, description: str) -> dict:
        """Create a new governance plan.

        Args:
            name: Plan name
            description: Plan description

        Returns:
            Created plan object
        """
        response = requests.post(
            f"{self.base_url}/api/plans",
            json={'name': name, 'description': description},
            headers=self._get_headers(),
            timeout=30,
        )
        response.raise_for_status()
        return response.json()


# Global client instance (can be used without Flask context)
druppie = DruppieClient()
