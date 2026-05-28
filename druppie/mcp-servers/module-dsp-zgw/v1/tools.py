"""DSP-ZGW v1 — MCP Tool Definitions.

Wraps v1/module.py business logic as MCP tools via FastMCP.
This file is the SINGLE SOURCE OF TRUTH for the tool contract:
- Tool name, description, input schema → via @mcp.tool() decorator
- Version, resource metrics → via @mcp.tool(meta={...})
- Agent guidance → via FastMCP(instructions=...)
All discoverable by MCP clients via initialize + tools/list.
"""

import os
import time
from typing import Any

from fastmcp import FastMCP

from .module import DSPZGWModule

MODULE_ID = "dsp-zgw"
MODULE_VERSION = "1.0.0"

mcp = FastMCP(
    "DSP-ZGW v1",
    version=MODULE_VERSION,
    instructions="""Koppeling met het DSP-zaaksysteem via ZGW-API (Zaken API, Catalogi API).

Use when:
- Aanmaken van een zaak in DSP met zaaktype, beschrijving en locatie
- Opvragen van zaakstatus inclusief historie
- Raadplegen van beschikbare zaaktypen uit de catalogus
- Koppelen van documenten aan een bestaande zaak

Don't use when:
- Je alleen adresgegevens nodig hebt (gebruik module-pdok)
- Je bestanden wilt opslaan (gebruik module-objectstorage)
- Je notificaties wilt versturen (gebruik module-notificatie)
""",
)

module = DSPZGWModule()


@mcp.tool(
    name="create_zaak",
    description="Maak een zaak aan in DSP met zaaktype, beschrijving, locatie en metadata.",
    meta={
        "module_id": MODULE_ID,
        "version": MODULE_VERSION,
        "resource_metrics": {
            "processing_ms": {"type": "integer", "unit": "milliseconds"},
        },
    },
)
async def create_zaak(
    zaaktype_url: str,
    beschrijving: str,
    locatie: str = "",
    metadata: str = "{}",
    user_id: str = "",
    project_id: str = "",
    session_id: str = "",
    app_id: str = "",
) -> dict[str, Any]:
    start = time.time()
    result = await module.create_zaak(
        zaaktype_url=zaaktype_url,
        beschrijving=beschrijving,
        locatie=locatie,
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
    description="Haal actuele zaakstatus op inclusief laatste opmerking en historie.",
    meta={
        "module_id": MODULE_ID,
        "version": MODULE_VERSION,
        "resource_metrics": {
            "processing_ms": {"type": "integer", "unit": "milliseconds"},
        },
    },
)
async def get_zaak_status(
    zaak_url: str,
    user_id: str = "",
    project_id: str = "",
    session_id: str = "",
    app_id: str = "",
) -> dict[str, Any]:
    start = time.time()
    result = await module.get_zaak_status(
        zaak_url=zaak_url,
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
    name="list_zaaktypen",
    description="Geef beschikbare zaaktypen terug uit de DSP-catalogus.",
    meta={
        "module_id": MODULE_ID,
        "version": MODULE_VERSION,
        "resource_metrics": {
            "processing_ms": {"type": "integer", "unit": "milliseconds"},
        },
    },
)
async def list_zaaktypen(
    catalogus_url: str = "",
    user_id: str = "",
    project_id: str = "",
    session_id: str = "",
    app_id: str = "",
) -> dict[str, Any]:
    start = time.time()
    result = await module.list_zaaktypen(
        catalogus_url=catalogus_url,
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
    name="link_zaak_document",
    description="Koppel een document (bijv. foto) aan een bestaande zaak.",
    meta={
        "module_id": MODULE_ID,
        "version": MODULE_VERSION,
        "resource_metrics": {
            "processing_ms": {"type": "integer", "unit": "milliseconds"},
        },
    },
)
async def link_zaak_document(
    zaak_url: str,
    document_url: str,
    titel: str = "",
    user_id: str = "",
    project_id: str = "",
    session_id: str = "",
    app_id: str = "",
) -> dict[str, Any]:
    start = time.time()
    result = await module.link_zaak_document(
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
