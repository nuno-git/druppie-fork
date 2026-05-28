"""Notificatie Module v1 — Public API.

Entry point for v1 business logic. One public method per MCP tool.
Imports from sibling files for complex logic.

Notificatie-module voor e-mail en push-transport. Bevat geen routing-logica;
de aanroepende service bepaalt ontvangers.
"""

import json
import logging
import os
from typing import Any

import httpx

logger = logging.getLogger("notificatie-mcp.v1")


class NotificatieModule:
    """v1 business logic for notification transport.

    All public methods correspond 1:1 to MCP tools defined in tools.py.
    """

    def __init__(self):
        self._smtp_host = os.getenv("NOTIFICATIE_SMTP_HOST", "")
        self._smtp_port = int(os.getenv("NOTIFICATIE_SMTP_PORT", "587"))
        self._smtp_user = os.getenv("NOTIFICATIE_SMTP_USER", "")
        self._smtp_pass = os.getenv("NOTIFICATIE_SMTP_PASS", "")
        self._smtp_from = os.getenv("NOTIFICATIE_SMTP_FROM", "")

        self._push_url = os.getenv("NOTIFICATIE_PUSH_URL", "")
        self._push_api_key = os.getenv("NOTIFICATIE_PUSH_API_KEY", "")

    async def send_email(
        self,
        ontvangers: str,
        onderwerp: str,
        body: str,
        bijlage_link: str = "",
        user_id: str = "",
        project_id: str = "",
        session_id: str = "",
        app_id: str = "",
    ) -> dict[str, Any]:
        """Verstuur e-mail naar één of meer ontvangers met onderwerp, body en optionele bijlage-link."""
        if not self._smtp_host:
            raise RuntimeError("NOTIFICATIE_SMTP_HOST is not configured")

        try:
            recipients = json.loads(ontvangers)
            if isinstance(recipients, str):
                recipients = [recipients]
        except (json.JSONDecodeError, TypeError):
            recipients = [r.strip() for r in ontvangers.split(",") if r.strip()]

        if not recipients:
            raise ValueError(
                "Ontvangers lijst is leeg — minimaal één ontvanger vereist"
            )

        headers = {
            "Authorization": f"Bearer {self._smtp_pass}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "from": self._smtp_from,
            "to": recipients,
            "subject": onderwerp,
            "html": body,
        }
        if bijlage_link:
            payload["attachments"] = [{"url": bijlage_link}]

        url = f"{self._smtp_host}:{self._smtp_port}/api/send"

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()

        logger.info("Email sent to %s: %s", recipients, onderwerp)

        return {
            "status": "sent",
            "ontvangers": recipients,
            "onderwerp": onderwerp,
        }

    async def send_push(
        self,
        team_groep: str,
        bericht: str,
        titel: str = "",
        user_id: str = "",
        project_id: str = "",
        session_id: str = "",
        app_id: str = "",
    ) -> dict[str, Any]:
        """Stuur push-notificatie naar een behandelteam-groep."""
        if not self._push_url:
            raise RuntimeError("NOTIFICATIE_PUSH_URL is not configured")

        headers = {
            "Content-Type": "application/json",
        }
        if self._push_api_key:
            headers["Authorization"] = f"Bearer {self._push_api_key}"

        payload: dict[str, Any] = {
            "group": team_groep,
            "message": bericht,
        }
        if titel:
            payload["title"] = titel

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{self._push_url}/api/push", json=payload, headers=headers
            )
            response.raise_for_status()

        logger.info("Push sent to team %s: %s", team_groep, titel or bericht[:50])

        return {
            "status": "sent",
            "team_groep": team_groep,
            "titel": titel,
        }
