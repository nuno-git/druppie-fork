"""Azure SSO authentication routes.

Implements the OAuth 2.0 Authorization Code flow for Azure AI Foundry authentication.
Users are redirected to Azure AD login and back via a callback endpoint.
"""

from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from druppie.api.deps import get_current_user
from druppie.core.config import get_settings
from druppie.db.database import get_db
from druppie.db.models.user import UserToken

logger = structlog.get_logger()

router = APIRouter()

# In-memory store for pending auth code flows: state -> {user_id, flow, created_at}
_pending_flows: dict[str, dict] = {}
_FLOW_TTL_SECONDS = 900  # 15 minutes


def _purge_stale_flows():
    """Remove pending flows older than _FLOW_TTL_SECONDS."""
    now = datetime.now(timezone.utc)
    stale = [
        k
        for k, v in _pending_flows.items()
        if (now - v["created_at"]).total_seconds() > _FLOW_TTL_SECONDS
    ]
    for k in stale:
        del _pending_flows[k]
    if stale:
        logger.info("azure_stale_flows_purged", count=len(stale))


_AZURE_SCOPES = ["https://cognitiveservices.azure.com/.default"]


def _get_msal_app():
    """Create an MSAL ConfidentialClientApplication for auth code flow."""
    import msal

    settings = get_settings().azure
    return msal.ConfidentialClientApplication(
        client_id=settings.client_id,
        client_credential=settings.client_secret,
        authority=f"https://login.microsoftonline.com/{settings.tenant_id}",
    )


@router.get("/auth/azure/login")
async def start_azure_login(
    user: dict = Depends(get_current_user),
):
    """Start Azure SSO login.

    Returns an auth_url that the frontend should redirect the browser to.
    """
    settings = get_settings().azure
    if not settings.is_configured:
        raise HTTPException(
            status_code=503,
            detail="Azure SSO is not configured. Set AZURE_CLIENT_ID and AZURE_CLIENT_SECRET.",
        )

    user_id = user["sub"]

    try:
        app = _get_msal_app()
        flow = app.initiate_auth_code_flow(
            scopes=_AZURE_SCOPES,
            redirect_uri=settings.redirect_uri,
        )

        if "auth_uri" not in flow:
            logger.error(
                "azure_auth_code_flow_failed",
                user_id=user_id,
                error=flow.get("error"),
            )
            raise HTTPException(
                status_code=502,
                detail=f"Failed to initiate Azure login: {flow.get('error_description', 'Unknown error')}",
            )

        _purge_stale_flows()

        # Use the state from the MSAL flow to map back to the user
        state = flow["state"]
        _pending_flows[state] = {
            "user_id": user_id,
            "flow": flow,
            "created_at": datetime.now(timezone.utc),
        }

        logger.info("azure_sso_login_started", user_id=user_id)

        return {"auth_url": flow["auth_uri"]}

    except HTTPException:
        raise
    except ImportError:
        raise HTTPException(
            status_code=503,
            detail="msal package not installed. Run: pip install msal",
        )
    except Exception as e:
        logger.error("azure_sso_start_error", user_id=user_id, error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to start Azure login: {str(e)}")


@router.get("/auth/azure/callback")
async def azure_callback(
    request: Request,
    db: Session = Depends(get_db),
):
    """OAuth callback endpoint.

    Azure AD redirects the browser here after authentication.
    This endpoint is unauthenticated (no Keycloak token) -- the user
    is identified via the state parameter from the original login request.

    Security: the state parameter is the sole link between this callback and the
    authenticated user who initiated the flow. MSAL generates a cryptographically
    random state value, making it infeasible to guess or brute-force. Pending flow
    entries expire after _FLOW_TTL_SECONDS, limiting the replay window.
    """
    settings = get_settings().azure
    params = dict(request.query_params)
    state = params.get("state", "")

    flow_data = _pending_flows.pop(state, None)
    if flow_data is None:
        logger.warning("azure_callback_unknown_state", state=state[:16])
        return RedirectResponse(
            url=f"{settings.frontend_url}/settings?azure=error&message=Invalid+or+expired+login+session"
        )

    user_id = flow_data["user_id"]
    flow = flow_data["flow"]

    try:
        app = _get_msal_app()
        result = app.acquire_token_by_auth_code_flow(flow, params)

        if "access_token" not in result:
            error_desc = result.get("error_description", result.get("error", "Unknown error"))
            logger.warning("azure_callback_token_error", user_id=user_id, error=error_desc)
            return RedirectResponse(
                url=f"{settings.frontend_url}/settings?azure=error&message=Authentication+failed"
            )

        # Store token in DB
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

        logger.info("azure_sso_authenticated", user_id=user_id)
        return RedirectResponse(url=f"{settings.frontend_url}/settings?azure=success")

    except Exception as e:
        logger.error("azure_callback_error", user_id=user_id, error=str(e))
        return RedirectResponse(
            url=f"{settings.frontend_url}/settings?azure=error&message=Authentication+failed"
        )


@router.get("/auth/azure/status")
async def check_azure_auth_status(
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Check if the user has a stored Azure token."""
    settings = get_settings().azure
    user_id = user["sub"]

    token = db.query(UserToken).filter_by(user_id=user_id, service="azure").first()
    if token:
        return {
            "status": "authenticated",
            "is_configured": settings.is_configured,
            "expires_at": token.expires_at.isoformat() if token.expires_at else None,
        }
    return {"status": "not_started", "is_configured": settings.is_configured}


@router.post("/auth/azure/disconnect")
async def disconnect_azure(
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Remove stored Azure token."""
    user_id = user["sub"]

    deleted = db.query(UserToken).filter_by(user_id=user_id, service="azure").delete()
    db.commit()

    logger.info("azure_disconnected", user_id=user_id, tokens_removed=deleted)
    return {"status": "disconnected"}
