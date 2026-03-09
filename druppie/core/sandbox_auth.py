"""Shared sandbox authentication utilities.

Used by both builtin_tools.py (creating sandbox sessions) and
sandbox.py (proxying events to the control plane).
"""

import hashlib
import hmac
import os
import time
import warnings


# Default secret for development only - MUST be overridden in production
_DEFAULT_SANDBOX_SECRET = "sandbox-dev-secret"
SANDBOX_API_SECRET = os.getenv("SANDBOX_API_SECRET", _DEFAULT_SANDBOX_SECRET)

_environment = os.getenv("ENVIRONMENT", "development").lower()
if SANDBOX_API_SECRET == _DEFAULT_SANDBOX_SECRET:
    if _environment in ("production", "staging", "prod"):
        raise RuntimeError(
            "SANDBOX_API_SECRET is using the insecure default value. "
            "Set a unique SANDBOX_API_SECRET in your .env file for production deployments."
        )
    warnings.warn(
        "SANDBOX_API_SECRET is using the default development value. "
        "Set SANDBOX_API_SECRET in .env for production.",
        UserWarning,
        stacklevel=2,
    )


def generate_control_plane_token(secret: str | None = None) -> str:
    """Generate an HMAC-SHA256 auth token for the Open-Inspect control plane.

    Token format: <unix-ms-timestamp>.<hmac-sha256-hex-signature>
    Matches the auth format expected by the control plane API.

    Args:
        secret: HMAC secret. Defaults to SANDBOX_API_SECRET env var.
    """
    secret = secret or SANDBOX_API_SECRET
    timestamp = str(int(time.time() * 1000))
    signature = hmac.new(
        secret.encode(), timestamp.encode(), hashlib.sha256
    ).hexdigest()
    return f"{timestamp}.{signature}"
