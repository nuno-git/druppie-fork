"""DSP ZGW v1 — MCP Tool Definitions.

Wraps v1/module.py business logic as MCP tools via FastMCP.
This file is the SINGLE SOURCE OF TRUTH for the tool contract:
- Tool name, description, input schema → via @mcp.tool() decorator
- Version, resource metrics → via @mcp.tool(meta={...})
- Agent guidance → via FastMCP(instructions=...)
"""

import os
import time

from fastmcp import FastMCP

from .module import DspZgwModule

MODULE_ID = "dsp-zgw"
MODULE_VERSION = "1.0.0"

mcp = FastMCP(
    "DSP ZGW v1",
    version=MODULE_VERSION,
    instructions="""DSP ZGW Module — Integratie met DSP zaaksysteem via ZGW-API's.

Use when:
- Aanmaken van een nieuwe zaak in DSP
- Ophalen van zaakstatus en opmerkingen
- Raadplegen van beschikbare zaaktypen
- Koppelen van documenten (foto's) aan een zaak

Don't use when:
- Je alleen adresgegevens nodig hebt (gebruik module-pdok-geocode)
- Je een notificatie wilt versturen (gebruik module-notificatie)
""",
)

module = DspZgwModule(
    base_url=os.getenv("ZGW_BASE_URL"),
    client_id=os.getenv("ZGW_CLIENT_ID"),
    client_secret=os.getenv("ZGW_CLIENT_SECRET"),
)


@mcp.tool(
    name="create_zaak",
    description="Maak een nieuwe zaak aan in DSP met zaaktype, beschrijving, locatie en metadata.",
    meta={
        "module_id": MODULE_ID,
        "version": MODULE_VERSION,
        "resource_metrics": {
            "processing_ms": {"type": "integer", "unit": "milliseconds"},
        },
    },
)
async def create_zaak(
    zaaktype: str,
    beschrijving: str,
    locatie_lat: float,
    locatie_lon: float,
    metadata: dict | None = None,
    user_id: str = "",
    project_id: str = "",
    session_id: str = "",
    app_id: str = "",
) -> dict:
    """Create a new zaak in DSP.

    Args:
        zaaktype: URL or identificatie of the zaaktype.
        beschrijving: Description of the zaak.
        locatie_lat: Latitude of the location.
        locatie_lon: Longitude of the location.
        metadata: Optional key-value pairs for zaak eigenschappen.
    """
    start = time.time()
    result = await module.create_zaak(
        zaaktype=zaaktype,
        beschrijving=beschrijving,
        locatie_lat=locatie_lat,
        locatie_lon=locatie_lon,
        metadata=metadata,
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
    name="get_zaak_status",
    description="Haal de actuele status en laatste opmerking op van een zaak.",
    meta={
        "module_id": MODULE_ID,
        "version": MODULE_VERSION,
        "resource_metrics": {
            "processing_ms": {"type": "integer", "unit": "milliseconds"},
        },
    },
)
async def get_zaak_status(
    zaak_id: str,
    user_id: str = "",
    project_id: str = "",
    session_id: str = "",
    app_id: str = "",
) -> dict:
    """Retrieve zaak status and remarks.

    Args:
        zaak_id: The zaak identificatie.
    """
    start = time.time()
    result = await module.get_zaak_status(
        zaak_id=zaak_id,
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
    name="get_zaaktypen",
    description="Haal beschikbare zaaktypen op uit DSP voor mapping-configuratie.",
    meta={
        "module_id": MODULE_ID,
        "version": MODULE_VERSION,
        "resource_metrics": {
            "processing_ms": {"type": "integer", "unit": "milliseconds"},
        },
    },
)
async def get_zaaktypen(
    user_id: str = "",
    project_id: str = "",
    session_id: str = "",
    app_id: str = "",
) -> dict:
    """Retrieve available zaaktypen from DSP Catalogi API."""
    start = time.time()
    result = await module.get_zaaktypen(
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
    name="link_document_to_zaak",
    description="Koppel een document (foto) aan een bestaande zaak in DSP.",
    meta={
        "module_id": MODULE_ID,
        "version": MODULE_VERSION,
        "resource_metrics": {
            "processing_ms": {"type": "integer", "unit": "milliseconds"},
        },
    },
)
async def link_document_to_zaak(
    zaak_url: str,
    document_url: str,
    titel: str = "Bijlage",
    user_id: str = "",
    project_id: str = "",
    session_id: str = "",
    app_id: str = "",
) -> dict:
    """Link a document to an existing zaak.

    Args:
        zaak_url: The full URL of the zaak.
        document_url: The full URL of the informatieobject.
        titel: Title for the document link.
    """
    start = time.time()
    result = await module.link_document_to_zaak(
        zaak_url=zaak_url,
        document_url=document_url,
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
