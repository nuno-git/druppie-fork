"""PDOK v1 — MCP Tool Definitions.

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

from .module import PDOKModule

MODULE_ID = "pdok"
MODULE_VERSION = "1.0.0"

mcp = FastMCP(
    "PDOK v1",
    version=MODULE_VERSION,
    instructions="""Geocoding-module via PDOK BAG/BGT. Vertaalt coördinaten naar adressen
en ondersteunt adreszoekfuncties.

Use when:
- Vertalen van coördinaten (RD of WGS84) naar een BAG-adres
- Zoeken van adressen op tekstinput (type-ahead / autocomplete)

Don't use when:
- Je een zaak wilt aanmaken (gebruik module-dsp-zgw)
- Je notificaties wilt versturen (gebruik module-notificatie)
- Je bestanden wilt opslaan (gebruik module-objectstorage)
""",
)

module = PDOKModule()


@mcp.tool(
    name="reverse_geocode",
    description="Vertaal RD- of WGS84-coördinaten naar een BAG-adres.",
    meta={
        "module_id": MODULE_ID,
        "version": MODULE_VERSION,
        "resource_metrics": {
            "processing_ms": {"type": "integer", "unit": "milliseconds"},
        },
    },
)
async def reverse_geocode(
    coordinaat: str,
    coord_systeem: str = "wgs84",
    user_id: str = "",
    project_id: str = "",
    session_id: str = "",
    app_id: str = "",
) -> dict[str, Any]:
    start = time.time()
    result = await module.reverse_geocode(
        coordinaat=coordinaat,
        coord_systeem=coord_systeem,
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
    name="search_address",
    description="Zoek adressen op tekstinput (type-ahead).",
    meta={
        "module_id": MODULE_ID,
        "version": MODULE_VERSION,
        "resource_metrics": {
            "processing_ms": {"type": "integer", "unit": "milliseconds"},
        },
    },
)
async def search_address(
    zoekterm: str,
    max_resultaten: int = 5,
    user_id: str = "",
    project_id: str = "",
    session_id: str = "",
    app_id: str = "",
) -> dict[str, Any]:
    start = time.time()
    result = await module.search_address(
        zoekterm=zoekterm,
        max_resultaten=max_resultaten,
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
