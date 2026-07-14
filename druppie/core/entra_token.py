"""Entra ID token service for user-scoped Azure access.

Retrieves user-scoped Entra ID tokens via Keycloak's broker token endpoint.
Supports multi-resource token exchange using stored refresh tokens.
"""

import base64
import json
import os
import time
from typing import Any

import httpx
import structlog

logger = structlog.get_logger()

KEYCLOAK_SERVER_URL = os.getenv("KEYCLOAK_SERVER_URL", "http://keycloak:8080")
KEYCLOAK_REALM = os.getenv("KEYCLOAK_REALM", "druppie")
KEYCLOAK_CLIENT_ID = "druppie-backend"
KEYCLOAK_CLIENT_SECRET = os.getenv("KEYCLOAK_CLIENT_SECRET", "")

ENTRA_TENANT_ID = os.getenv("ENTRA_TENANT_ID", "")
ENTRA_CLIENT_ID = os.getenv("ENTRA_CLIENT_ID", "")
ENTRA_CLIENT_SECRET = os.getenv("ENTRA_CLIENT_SECRET", "")

IDP_ALIAS = "entra-id"

# Security: only these Entra ID accounts are allowed to authenticate.
# All other accounts will be rejected even if they have valid Entra credentials.
ALLOWED_ENTRA_EMAILS = {
    "dataplatformtest@waterschap.org",
    "tst_jbode@waterschap.org",
}


def is_entra_configured() -> bool:
    return bool(ENTRA_CLIENT_ID and ENTRA_TENANT_ID)


def _check_entra_email_allowed(access_token: str) -> str | None:
    """Check if the Entra token's email is in the allowlist.

    Returns None if allowed, or an error message if blocked.
    """
    claims = _decode_jwt_payload(access_token)
    email = (claims.get("email") or claims.get("preferred_username") or claims.get("upn") or "").lower()

    if not email:
        logger.warning("entra_email_check_failed", reason="no email claim in token")
        return "Entra ID token does not contain an email claim."

    if email not in ALLOWED_ENTRA_EMAILS:
        logger.warning("entra_email_blocked", email=email)
        return f"Entra ID account '{email}' is not authorized. Contact your administrator."

    logger.info("entra_email_allowed", email=email)
    return None


def _decode_jwt_payload(token: str) -> dict[str, Any]:
    """Decode JWT payload without signature verification (for claim inspection only)."""
    parts = token.split(".")
    if len(parts) != 3:
        return {}
    payload = parts[1]
    padding = 4 - len(payload) % 4
    if padding != 4:
        payload += "=" * padding
    try:
        return json.loads(base64.urlsafe_b64decode(payload))
    except Exception:
        return {}


def _is_token_expired(token: str, margin_seconds: int = 60) -> bool:
    """Check if a JWT token is expired (with safety margin)."""
    claims = _decode_jwt_payload(token)
    exp = claims.get("exp")
    if not exp:
        return True
    return time.time() > (exp - margin_seconds)


def _get_token_claim(token: str, claim: str) -> str | None:
    """Extract a claim from a JWT without verification."""
    return _decode_jwt_payload(token).get(claim)


async def check_entra_linked(user_id: str) -> bool:
    """Check if a user has a linked Entra ID identity in Keycloak.

    Uses the druppie-backend service account to query the KC Admin API.
    """
    if not is_entra_configured():
        return False

    sa_token = await _get_service_account_token()
    if not sa_token:
        logger.warning("entra_check_failed", reason="could not get service account token")
        return False

    url = (
        f"{KEYCLOAK_SERVER_URL}/admin/realms/{KEYCLOAK_REALM}"
        f"/users/{user_id}/federated-identity"
    )

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                url,
                headers={"Authorization": f"Bearer {sa_token}"},
                timeout=10,
            )
            if response.status_code != 200:
                logger.warning(
                    "entra_check_failed",
                    status=response.status_code,
                    user_id=user_id,
                )
                return False

            identities = response.json()
            return any(
                idp.get("identityProvider") == IDP_ALIAS for idp in identities
            )
        except Exception as e:
            logger.error("entra_check_error", error=str(e), user_id=user_id)
            return False


async def get_entra_token(
    user_kc_token: str,
    scope: str | None = None,
) -> dict[str, Any]:
    """Retrieve a user-scoped Entra ID token via Keycloak's broker endpoint.

    Returns dict with keys:
        - "access_token": the Entra access token (or None)
        - "error": error message if failed (or None)
        - "needs_reauth": True if user must re-authenticate with Entra
    """
    if not is_entra_configured():
        return {"access_token": None, "error": "Entra ID is not configured", "needs_reauth": False}

    broker_url = (
        f"{KEYCLOAK_SERVER_URL}/realms/{KEYCLOAK_REALM}"
        f"/broker/{IDP_ALIAS}/token"
    )

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                broker_url,
                headers={"Authorization": f"Bearer {user_kc_token}"},
                timeout=10,
            )
        except Exception as e:
            logger.error("entra_broker_error", error=str(e))
            return {"access_token": None, "error": "Broker request failed", "needs_reauth": False}

    if response.status_code == 400:
        try:
            body = response.json()
        except Exception:
            body = {"raw": response.text[:200]}
        logger.warning("entra_broker_400", status=400)
        return {
            "access_token": None,
            "error": "Your Microsoft session has expired. Please sign in with Microsoft again.",
            "needs_reauth": True,
        }

    if response.status_code != 200:
        logger.warning("entra_broker_failed", status=response.status_code)
        return {
            "access_token": None,
            "error": f"Broker returned status {response.status_code}",
            "needs_reauth": response.status_code in (401, 403),
        }

    token_data = response.json()
    access_token = token_data.get("access_token")
    refresh_token = token_data.get("refresh_token")

    if not access_token:
        return {"access_token": None, "error": "Broker returned no access token", "needs_reauth": True}

    # Security: reject tokens from accounts not in the allowlist
    email_error = _check_entra_email_allowed(access_token)
    if email_error:
        return {"access_token": None, "error": email_error, "needs_reauth": False}

    # C1: verify the Entra token belongs to the same user as the KC token
    kc_claims = _decode_jwt_payload(user_kc_token)
    kc_email = (kc_claims.get("email") or kc_claims.get("preferred_username") or "").lower()
    entra_claims = _decode_jwt_payload(access_token)
    entra_email = (
        entra_claims.get("email")
        or entra_claims.get("preferred_username")
        or entra_claims.get("upn")
        or ""
    ).lower()
    if kc_email and entra_email and kc_email != entra_email:
        logger.error(
            "entra_token_identity_mismatch",
            kc_email=kc_email,
            entra_email=entra_email,
        )
        return {
            "access_token": None,
            "error": "Entra token identity does not match authenticated user.",
            "needs_reauth": True,
        }

    # If a specific scope is requested and we have a refresh token, exchange it
    if scope and refresh_token:
        scoped_token = await _exchange_refresh_for_scope(refresh_token, scope)
        if scoped_token:
            scoped_error = _check_entra_email_allowed(scoped_token)
            if scoped_error:
                return {"access_token": None, "error": scoped_error, "needs_reauth": False}
            return {"access_token": scoped_token, "error": None, "needs_reauth": False}

    # Check if the default access token is expired
    if _is_token_expired(access_token):
        if refresh_token:
            refreshed = await _exchange_refresh_for_scope(
                refresh_token, scope or "openid profile email User.Read"
            )
            if refreshed:
                refreshed_error = _check_entra_email_allowed(refreshed)
                if refreshed_error:
                    return {"access_token": None, "error": refreshed_error, "needs_reauth": False}
                return {"access_token": refreshed, "error": None, "needs_reauth": False}

        logger.warning("entra_token_expired", has_refresh=bool(refresh_token))
        return {
            "access_token": None,
            "error": "Entra ID token expired. Please re-authenticate with Microsoft.",
            "needs_reauth": True,
        }

    return {"access_token": access_token, "error": None, "needs_reauth": False}


async def _exchange_refresh_for_scope(refresh_token: str, scope: str) -> str | None:
    """Exchange a refresh token for an access token with a specific scope.

    Used for multi-resource access: same refresh token, different Azure resource scope.
    """
    if not ENTRA_TENANT_ID or not ENTRA_CLIENT_ID or not ENTRA_CLIENT_SECRET:
        logger.warning("entra_refresh_exchange_not_configured")
        return None

    token_url = f"https://login.microsoftonline.com/{ENTRA_TENANT_ID}/oauth2/v2.0/token"

    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "scope": scope,
        "client_id": ENTRA_CLIENT_ID,
        "client_secret": ENTRA_CLIENT_SECRET,
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(token_url, data=data, timeout=10)
        except Exception as e:
            logger.error("entra_refresh_exchange_error", error=str(e))
            return None

    if response.status_code != 200:
        logger.warning(
            "entra_refresh_exchange_failed",
            status=response.status_code,
        )
        return None

    result = response.json()
    return result.get("access_token")


async def _get_service_account_token() -> str | None:
    """Get a Keycloak access token for the druppie-backend service account."""
    if not KEYCLOAK_CLIENT_SECRET:
        return None

    token_url = (
        f"{KEYCLOAK_SERVER_URL}/realms/{KEYCLOAK_REALM}"
        f"/protocol/openid-connect/token"
    )

    data = {
        "grant_type": "client_credentials",
        "client_id": KEYCLOAK_CLIENT_ID,
        "client_secret": KEYCLOAK_CLIENT_SECRET,
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(token_url, data=data, timeout=10)
            if response.status_code == 200:
                return response.json().get("access_token")
            logger.warning("sa_token_failed", status=response.status_code)
            return None
        except Exception as e:
            logger.error("sa_token_error", error=str(e))
            return None
