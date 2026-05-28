"""Object Storage v1 — MCP Tool Definitions.

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

from .module import ObjectStorageModule

MODULE_ID = "objectstorage"
MODULE_VERSION = "1.0.0"

mcp = FastMCP(
    "Object Storage v1",
    version=MODULE_VERSION,
    instructions="""S3-compatibele objectopslag-module voor upload, download en verwijdering
van bestanden.

Use when:
- Uploaden van bestanden (bijv. foto's) naar S3-compatible objectopslag
- Genereren van tijdelijke signed URL's voor download
- Verwijderen van objecten uit de bucket

Don't use when:
- Je een zaak wilt aanmaken (gebruik module-dsp-zgw)
- Je een adres wilt opzoeken (gebruik module-pdok)
- Je notificaties wilt versturen (gebruik module-notificatie)
""",
)

module = ObjectStorageModule()


@mcp.tool(
    name="upload_object",
    description="Upload een bestand naar S3 en retourneer Object-Key.",
    meta={
        "module_id": MODULE_ID,
        "version": MODULE_VERSION,
        "resource_metrics": {
            "processing_ms": {"type": "integer", "unit": "milliseconds"},
        },
    },
)
async def upload_object(
    bestand_pad: str,
    bestandsnaam: str = "",
    content_type: str = "application/octet-stream",
    user_id: str = "",
    project_id: str = "",
    session_id: str = "",
    app_id: str = "",
) -> dict[str, Any]:
    start = time.time()
    result = await module.upload_object(
        bestand_pad=bestand_pad,
        bestandsnaam=bestandsnaam,
        content_type=content_type,
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
    name="get_object_url",
    description="Genereer tijdelijke signed URL voor download.",
    meta={
        "module_id": MODULE_ID,
        "version": MODULE_VERSION,
        "resource_metrics": {
            "processing_ms": {"type": "integer", "unit": "milliseconds"},
        },
    },
)
async def get_object_url(
    object_key: str,
    geldigheid_seconden: int = 3600,
    user_id: str = "",
    project_id: str = "",
    session_id: str = "",
    app_id: str = "",
) -> dict[str, Any]:
    start = time.time()
    result = await module.get_object_url(
        object_key=object_key,
        geldigheid_seconden=geldigheid_seconden,
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
    name="delete_object",
    description="Verwijder een object uit de bucket.",
    meta={
        "module_id": MODULE_ID,
        "version": MODULE_VERSION,
        "resource_metrics": {
            "processing_ms": {"type": "integer", "unit": "milliseconds"},
        },
    },
)
async def delete_object(
    object_key: str,
    user_id: str = "",
    project_id: str = "",
    session_id: str = "",
    app_id: str = "",
) -> dict[str, Any]:
    start = time.time()
    result = await module.delete_object(
        object_key=object_key,
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
