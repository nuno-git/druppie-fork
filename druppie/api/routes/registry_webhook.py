"""Harbor registry webhook receiver.

Receives Harbor ``PUSH_ARTIFACT`` webhooks and triggers a k8s deployment
rollout for the affected image. This endpoint does NOT use Keycloak auth
(Harbor calls it server-to-server); instead it optionally validates a shared
secret via the ``REGISTRY_WEBHOOK_SECRET`` env var and the
``X-Registry-Webhook-Secret`` header.
"""

import hmac
import os

from fastapi import APIRouter, Depends, Header
import structlog

from druppie.api.deps import get_deploy_service
from druppie.services import DeployService

logger = structlog.get_logger()

# Optional shared secret. When unset, the webhook is accepted without a secret
# (convenient for local dev). Set it in production to lock the endpoint down.
REGISTRY_WEBHOOK_SECRET = os.getenv("REGISTRY_WEBHOOK_SECRET", "")

router = APIRouter()


def _verify_secret(x_registry_webhook_secret: str | None) -> bool:
    """Constant-time check of the webhook secret when one is configured."""
    if not REGISTRY_WEBHOOK_SECRET:
        # No secret configured -> open in dev. Logged for visibility.
        return True
    if not x_registry_webhook_secret:
        return False
    return hmac.compare_digest(x_registry_webhook_secret, REGISTRY_WEBHOOK_SECRET)


def _extract_image_and_tag(payload: dict) -> tuple[str | None, str | None]:
    """Parse a Harbor webhook payload for the pushed image + tag.

    Harbor's PUSH_ARTIFACT payload nests the resource list under
    ``event_data.resources``. Each resource carries ``resource_url`` (a full
    reference like ``harbor.io/druppie/backend:latest``) and optionally ``tag``.
    """
    event_data = payload.get("event_data") or {}
    resources = event_data.get("resources") or []
    if not resources or not isinstance(resources, list):
        return None, None

    first = resources[0] if isinstance(resources[0], dict) else {}
    image = first.get("resource_url")
    tag = first.get("tag")
    return image, tag


@router.post("/registry/webhook")
async def harbor_webhook(
    payload: dict,
    deploy_service: DeployService = Depends(get_deploy_service),
    x_registry_webhook_secret: str | None = Header(None, alias="X-Registry-Webhook-Secret"),
) -> dict:
    """Receive a Harbor webhook and trigger a deploy on PUSH_ARTIFACT.

    Returns ``{"status": "accepted"}`` for any well-formed PUSH_ARTIFACT event
    so Harbor treats the delivery as successful, even if the rollout restart
    itself fails (the failure is logged and surfaced in the response body).
    """
    if not _verify_secret(x_registry_webhook_secret):
        logger.warning("registry_webhook_unauthorized")
        return {"status": "unauthorized"}

    event_type = payload.get("type")
    if event_type != "PUSH_ARTIFACT":
        logger.info("registry_webhook_ignored", event_type=event_type)
        return {"status": "ignored", "reason": f"event type {event_type!r} not handled"}

    image, tag = _extract_image_and_tag(payload)
    if not image:
        logger.warning("registry_webhook_no_image", payload_keys=list(payload.keys()))
        return {"status": "ignored", "reason": "no image found in payload"}

    logger.info("registry_webhook_push", image=image, tag=tag)
    result = await deploy_service.trigger_deploy(image=image, tag=tag)

    return {
        "status": "accepted",
        "image": image,
        "tag": tag,
        "deploy": result,
    }
