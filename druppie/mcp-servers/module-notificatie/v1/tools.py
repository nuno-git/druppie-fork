"""Notificatie v1 — MCP Tool Definitions.

Wraps v1/module.py business logic as MCP tools via FastMCP.
This file is the SINGLE SOURCE OF TRUTH for the tool contract:
- Tool name, description, input schema → via @mcp.tool() decorator
- Version, resource metrics → via @mcp.tool(meta={...})
- Agent guidance → via FastMCP(instructions=...)
"""

import os
import time

from fastmcp import FastMCP

from .module import NotificatieModule

MODULE_ID = "notificatie"
MODULE_VERSION = "1.0.0"

mcp = FastMCP(
    "Notificatie v1",
    version=MODULE_VERSION,
    instructions="""Notificatie Module — E-mail en push-notificaties.

Use when:
- Versturen van bevestigingsmail aan burger na melding
- Notificeren van behandelteam bij nieuwe melding
- Versturen van status-update notificaties

Don't use when:
- Je een zaak wilt aanmaken (gebruik module-dsp-zgw)
- Je adresgegevens nodig hebt (gebruik module-pdok-geocode)
""",
)

module = NotificatieModule(
    base_url=os.getenv("NOTIFICATIE_BASE_URL"),
    from_address=os.getenv("SMTP_FROM"),
)


@mcp.tool(
    name="send_email",
    description="Verstuur e-mail naar een of meer ontvangers met onderwerp, body (sjabloon) en optionele bijlagen.",
    meta={
        "module_id": MODULE_ID,
        "version": MODULE_VERSION,
        "resource_metrics": {
            "processing_ms": {"type": "integer", "unit": "milliseconds"},
        },
    },
)
async def send_email(
    ontvangers: list[str],
    onderwerp: str,
    body: str,
    sjabloon: str = "default",
    bijlagen: list[str] | None = None,
    user_id: str = "",
    project_id: str = "",
    session_id: str = "",
    app_id: str = "",
) -> dict:
    """Send an e-mail notification.

    Args:
        ontvangers: List of recipient e-mail addresses.
        onderwerp: E-mail subject line.
        body: E-mail body content (HTML or plain text).
        sjabloon: Template name to use (default: 'default').
        bijlagen: Optional list of attachment URLs.
    """
    start = time.time()
    result = await module.send_email(
        ontvangers=ontvangers,
        onderwerp=onderwerp,
        body=body,
        sjabloon=sjabloon,
        bijlagen=bijlagen,
        user_id=user_id,
        project_id=project_id,
        session_id=session_id,
        app_id=app_id,
    )
    elapsed_ms = int((time.time() - start) * 1000)
    return {
        **result,
        "_meta": {
            "module_id": MODULE_ID,
            "module_version": MODULE_VERSION,
            "usage": {
                "cost_cents": 0.0,
                "resources": {"processing_ms": elapsed_ms},
            },
        },
    }


@mcp.tool(
    name="send_push",
    description="Stuur push-notificatie naar een behandelteam-kanaal (toekomstige uitbreiding, stub).",
    meta={
        "module_id": MODULE_ID,
        "version": MODULE_VERSION,
        "resource_metrics": {
            "processing_ms": {"type": "integer", "unit": "milliseconds"},
        },
    },
)
async def send_push(
    kanaal: str,
    bericht: str,
    user_id: str = "",
    project_id: str = "",
    session_id: str = "",
    app_id: str = "",
) -> dict:
    """Send a push notification (stub).

    Args:
        kanaal: Channel/kanaal identifier for the behandelteam.
        bericht: Push notification message.
    """
    start = time.time()
    result = await module.send_push(
        kanaal=kanaal,
        bericht=bericht,
        user_id=user_id,
        project_id=project_id,
        session_id=session_id,
        app_id=app_id,
    )
    elapsed_ms = int((time.time() - start) * 1000)
    return {
        **result,
        "_meta": {
            "module_id": MODULE_ID,
            "module_version": MODULE_VERSION,
            "usage": {
                "cost_cents": 0.0,
                "resources": {"processing_ms": elapsed_ms},
            },
        },
    }
