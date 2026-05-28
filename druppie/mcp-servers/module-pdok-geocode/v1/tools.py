"""PDOK Geocode v1 — MCP Tool Definitions.

Wraps v1/module.py business logic as MCP tools via FastMCP.
This file is the SINGLE SOURCE OF TRUTH for the tool contract:
- Tool name, description, input schema → via @mcp.tool() decorator
- Version, resource metrics → via @mcp.tool(meta={...})
- Agent guidance → via FastMCP(instructions=...)
"""

import time

from fastmcp import FastMCP

from .module import PdokGeocodeModule

MODULE_ID = "pdok-geocode"
MODULE_VERSION = "1.0.0"

mcp = FastMCP(
    "PDOK Geocode v1",
    version=MODULE_VERSION,
    instructions="""PDOK Geocode Module — BAG/BGT adres-resolutie via PDOK.

Use when:
- Reverse geocoding: vertaal coördinaten (lat/lon) naar een BAG-adres
- Adres-zoekfunctie: type-ahead zoekveld voor adresinvoer

Don't use when:
- Je een zaak wilt aanmaken (gebruik module-dsp-zgw)
- Je een notificatie wilt versturen (gebruik module-notificatie)
- Je een bestand wilt opslaan (gebruik module-objectstore)
""",
)

module = PdokGeocodeModule()


@mcp.tool(
    name="reverse_geocode",
    description="Resolve coördinaten (lat/lon) naar een BAG-adres met huisnummer, straat, plaats.",
    meta={
        "module_id": MODULE_ID,
        "version": MODULE_VERSION,
        "resource_metrics": {
            "processing_ms": {"type": "integer", "unit": "milliseconds"},
        },
    },
)
async def reverse_geocode(
    lat: float,
    lon: float,
    user_id: str = "",
    project_id: str = "",
    session_id: str = "",
    app_id: str = "",
) -> dict:
    """Resolve coordinates to a BAG address.

    Args:
        lat: Latitude in WGS84 (e.g., 52.3676).
        lon: Longitude in WGS84 (e.g., 4.9041).
    """
    start = time.time()
    result = await module.reverse_geocode(
        lat=lat,
        lon=lon,
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
    description="Zoek adressen op tekstinput (type-ahead voor adresveld).",
    meta={
        "module_id": MODULE_ID,
        "version": MODULE_VERSION,
        "resource_metrics": {
            "processing_ms": {"type": "integer", "unit": "milliseconds"},
        },
    },
)
async def search_address(
    query: str,
    rows: int = 5,
    user_id: str = "",
    project_id: str = "",
    session_id: str = "",
    app_id: str = "",
) -> dict:
    """Search addresses by text input.

    Args:
        query: Search text (partial address, min 2 characters).
        rows: Maximum number of results (1-10, default 5).
    """
    start = time.time()
    result = await module.search_address(
        query=query,
        rows=rows,
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
