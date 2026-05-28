"""Notificatie v1 — MCP Tool Definitions.

Wraps v1/module.py business logic as MCP tools via FastMCP.
This file is the SINGLE SOURCE OF TRUTH for the tool contract:
- Tool name, description, input schema → via @mcp.tool() decorator
- Version, resource metrics → via @mcp.tool(meta={...})
- Agent guidance → via FastMCP(instructions=...)
All discoverable by MCP clients via initialize + tools/list.
"""

import time
from typing import Any

from fastmcp import FastMCP

from .module import NotificatieModule

MODULE_ID = "notificatie"
MODULE_VERSION = "1.0.0"

mcp = FastMCP(
    "Notificatie v1",
    version=MODULE_VERSION,
    instructions="""Notificatie-module voor e-mail en push-transport. Bevat geen routing-logica;
de aanroepende service bepaalt ontvangers.

Use when:
- Versturen van e-mail naar één of meer ontvangers
- Versturen van push-notificaties naar behandelteam-groepen

Don't use when:
- Je een zaak wilt aanmaken (gebruik module-dsp-zgw)
- Je een adres wilt opzoeken (gebruik module-pdok)
- Je bestanden wilt opslaan (gebruik module-objectstorage)
""",
)

module = NotificatieModule()


@mcp.tool(
    name="send_email",
    description="Verstuur e-mail naar één of meer ontvangers met onderwerp, body en optionele bijlage-link.",
    meta={
        "module_id": MODULE_ID,
        "version": MODULE_VERSION,
        "resource_metrics": {
            "processing_ms": {"type": "integer", "unit": "milliseconds"},
        },
    },
)
async def send_email(
    ontvangers: str,
    onderwerp: str,
    body: str,
    bijlage_link: str = "",
    user_id: str = "",
    project_id: str = "",
    session_id: str = "",
    app_id: str = "",
) -> dict[str, Any]:
    start = time.time()
    result = await module.send_email(
        ontvangers=ontvangers,
        onderwerp=onderwerp,
        body=body,
        bijlage_link=bijlage_link,
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
    description="Stuur push-notificatie naar een behandelteam-groep.",
    meta={
        "module_id": MODULE_ID,
        "version": MODULE_VERSION,
        "resource_metrics": {
            "processing_ms": {"type": "integer", "unit": "milliseconds"},
        },
    },
)
async def send_push(
    team_groep: str,
    bericht: str,
    titel: str = "",
    user_id: str = "",
    project_id: str = "",
    session_id: str = "",
    app_id: str = "",
) -> dict[str, Any]:
    start = time.time()
    result = await module.send_push(
        team_groep=team_groep,
        bericht=bericht,
        titel=titel,
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
