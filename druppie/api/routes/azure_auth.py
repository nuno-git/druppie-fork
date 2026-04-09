"""Azure device code authentication routes.

Implements the OAuth 2.0 device code flow for Azure AI Foundry authentication.
Users authenticate via microsoft.com/devicelogin and the token is stored in the DB.
"""

import os
import threading
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from druppie.api.deps import get_current_user
from druppie.db.database import get_db
from druppie.db.models.user import UserToken

logger = structlog.get_logger()

router = APIRouter()

# In-memory store for pending device code flows (user_id -> flow state)
# Each entry: {"app": msal.PublicClientApplication, "flow": dict}
_pending_flows: dict[str, dict] = {}
_flows_lock = threading.Lock()

# Azure client ID for device code flow.
# Default: Microsoft Azure PowerShell (1950a258-...) — pre-consented in most enterprise tenants.
# Override via AZURE_CLIENT_ID env var if your tenant requires a custom app registration.
_AZURE_CLIENT_ID = os.getenv("AZURE_CLIENT_ID", "1950a258-227b-4e31-a9cf-717495945fc2")
_AZURE_TENANT_ID = os.getenv("AZURE_TENANT_ID", "common")
_AZURE_SCOPES = ["https://cognitiveservices.azure.com/.default"]


def _get_msal_app():
    """Create an MSAL PublicClientApplication for device code flow."""
    import msal

    return msal.PublicClientApplication(
        client_id=_AZURE_CLIENT_ID,
        authority=f"https://login.microsoftonline.com/{_AZURE_TENANT_ID}",
    )


@router.post("/auth/azure/device-code")
async def start_device_code_flow(
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Start Azure device code flow.

    Returns the user_code and verification_uri for the user to complete
    authentication at microsoft.com/devicelogin.
    """
    user_id = user["sub"]

    try:
        app = _get_msal_app()
        flow = app.initiate_device_flow(scopes=_AZURE_SCOPES)

        if "user_code" not in flow:
            logger.error(
                "azure_device_code_flow_failed",
                user_id=user_id,
                error=flow.get("error"),
                description=flow.get("error_description"),
            )
            raise HTTPException(
                status_code=502,
                detail=f"Failed to initiate Azure device code flow: {flow.get('error_description', 'Unknown error')}",
            )

        with _flows_lock:
            _pending_flows[user_id] = {"app": app, "flow": flow}

        logger.info(
            "azure_device_code_flow_started",
            user_id=user_id,
            verification_uri=flow.get("verification_uri"),
        )

        return {
            "user_code": flow["user_code"],
            "verification_uri": flow.get("verification_uri", "https://microsoft.com/devicelogin"),
            "message": flow.get("message", ""),
            "expires_in": flow.get("expires_in", 900),
        }

    except HTTPException:
        raise
    except ImportError:
        raise HTTPException(
            status_code=503,
            detail="msal package not installed. Run: pip install msal",
        )
    except Exception as e:
        logger.error("azure_device_code_start_error", user_id=user_id, error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to start device code flow: {str(e)}")


@router.get("/auth/azure/status")
async def check_azure_auth_status(
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Check if the device code flow completed.

    Frontend polls this endpoint every few seconds until status is 'authenticated'.
    Returns: {status: 'not_started' | 'pending' | 'authenticated', expires_at?: str}
    """
    user_id = user["sub"]

    # Check if there's a pending flow
    with _flows_lock:
        flow_data = _pending_flows.get(user_id)

    if flow_data is None:
        # No pending flow - check if already authenticated (token in DB)
        token = db.query(UserToken).filter_by(user_id=user_id, service="azure").first()
        if token:
            return {
                "status": "authenticated",
                "expires_at": token.expires_at.isoformat() if token.expires_at else None,
            }
        return {"status": "not_started"}

    app = flow_data["app"]
    flow = flow_data["flow"]

    try:
        # Try to acquire token (non-blocking if user hasn't completed flow yet)
        result = app.acquire_token_by_device_flow(flow)

        if "access_token" in result:
            # Success - store token in DB
            access_token = result["access_token"]
            expires_in = result.get("expires_in", 3600)
            expires_at = datetime.fromtimestamp(
                datetime.now(timezone.utc).timestamp() + expires_in,
                tz=timezone.utc,
            )

            existing = db.query(UserToken).filter_by(user_id=user_id, service="azure").first()
            if existing:
                existing.access_token = access_token
                existing.refresh_token = result.get("refresh_token")
                existing.expires_at = expires_at
            else:
                db.add(
                    UserToken(
                        user_id=user_id,
                        service="azure",
                        access_token=access_token,
                        refresh_token=result.get("refresh_token"),
                        expires_at=expires_at,
                    )
                )
            db.commit()

            # Clean up pending flow
            with _flows_lock:
                _pending_flows.pop(user_id, None)

            logger.info("azure_device_code_authenticated", user_id=user_id)
            return {"status": "authenticated", "expires_at": expires_at.isoformat()}

        # Not yet authenticated or error
        error = result.get("error", "")
        if error == "authorization_pending":
            return {"status": "pending"}
        elif error == "expired_token":
            with _flows_lock:
                _pending_flows.pop(user_id, None)
            return {"status": "expired"}
        else:
            logger.warning(
                "azure_device_code_error",
                user_id=user_id,
                error=error,
                description=result.get("error_description"),
            )
            with _flows_lock:
                _pending_flows.pop(user_id, None)
            return {"status": "error", "error": result.get("error_description", error)}

    except Exception as e:
        logger.warning("azure_device_code_poll_error", user_id=user_id, error=str(e))
        return {"status": "pending"}


@router.post("/auth/azure/disconnect")
async def disconnect_azure(
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Remove stored Azure token."""
    user_id = user["sub"]

    # Clean up any pending flow
    with _flows_lock:
        _pending_flows.pop(user_id, None)

    # Remove token from DB
    deleted = db.query(UserToken).filter_by(user_id=user_id, service="azure").delete()
    db.commit()

    logger.info("azure_disconnected", user_id=user_id, tokens_removed=deleted)
    return {"status": "disconnected"}
