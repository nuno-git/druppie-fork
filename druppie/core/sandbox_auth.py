"""Shared sandbox authentication utilities.

Used by both builtin_tools.py (creating sandbox sessions) and
sandbox.py (proxying events to the control plane).
"""

import hashlib
import hmac
import os
import time


SANDBOX_API_SECRET = os.getenv("SANDBOX_API_SECRET", "sandbox-dev-secret")


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
