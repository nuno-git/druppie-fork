"""Notificatie Module v1 — Public API.

Entry point for v1 business logic. One public method per MCP tool.
Wraps e-mail notificatie-endpoint / SMTP for sending notifications.
"""

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger("notificatie-mcp.v1")

NOTIFICATIE_BASE_URL = os.getenv("NOTIFICATIE_BASE_URL", "http://localhost:25")
SMTP_FROM = os.getenv("SMTP_FROM", "noreply@example.com")


class NotificatieModule:
    """v1 business logic for notification delivery.

    Supports e-mail with templates. Future: push notifications.
    All public methods correspond 1:1 to MCP tools defined in tools.py.
    """

    def __init__(
        self,
        base_url: str | None = None,
        from_address: str | None = None,
    ):
        self._base_url = (base_url or NOTIFICATIE_BASE_URL).rstrip("/")
        self._from_address = from_address or SMTP_FROM

    async def send_email(
        self,
        ontvangers: list[str],
        onderwerp: str,
        body: str,
        sjabloon: str = "default",
        bijlagen: list[str] | None = None,
        user_id: str = "",
        project_id: str = "",
        session_id: str = "",
        app_id: str = "",
    ) -> dict[str, Any]:
        """Send an e-mail to one or more recipients.

        Args:
            ontvangers: List of e-mail addresses.
            onderwerp: E-mail subject line.
            body: E-mail body content (HTML or plain text).
            sjabloon: Template name to use (default: 'default').
            bijlagen: Optional list of attachment URLs/paths.
        """
        if not ontvangers:
            raise ValueError("At least one recipient (ontvangers) is required")
        if not onderwerp:
            raise ValueError("Subject (onderwerp) is required")
        if not body:
            raise ValueError("Body is required")

        payload: dict[str, Any] = {
            "from": self._from_address,
            "to": ontvangers,
            "subject": onderwerp,
            "body": body,
            "template": sjabloon,
        }
        if bijlagen:
            payload["attachments"] = bijlagen

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{self._base_url}/api/send",
                json=payload,
            )
            response.raise_for_status()
            result = response.json()

        return {
            "status": "verzonden",
            "ontvangers": ontvangers,
            "message_id": result.get("message_id", ""),
        }

    async def send_push(
        self,
        kanaal: str,
        bericht: str,
        user_id: str = "",
        project_id: str = "",
        session_id: str = "",
        app_id: str = "",
    ) -> dict[str, Any]:
        """Send a push notification to a behandelteam kanaal (future, stub).

        Args:
            kanaal: Channel/kanaal identifier for the behandelteam.
            bericht: Push notification message.
        """
        # Stub implementation — future expansion for push notifications
        logger.info("Push notification stub: kanaal=%s bericht=%s", kanaal, bericht)
        return {
            "status": "stub",
            "kanaal": kanaal,
            "bericht": bericht,
            "opmerking": "Push notifications not yet implemented (stub)",
        }
