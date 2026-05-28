"""Objectstore v1 — MCP Tool Definitions.

Wraps v1/module.py business logic as MCP tools via FastMCP.
This file is the SINGLE SOURCE OF TRUTH for the tool contract:
- Tool name, description, input schema → via @mcp.tool() decorator
- Version, resource metrics → via @mcp.tool(meta={...})
- Agent guidance → via FastMCP(instructions=...)
"""

import os
import time

from fastmcp import FastMCP

from .module import ObjectstoreModule

MODULE_ID = "objectstore"
MODULE_VERSION = "1.0.0"

mcp = FastMCP(
    "Objectstore v1",
    version=MODULE_VERSION,
    instructions="""Objectstore Module — S3-compatibele object-opslag.

Use when:
- Uploaden van bestanden (foto's, documenten) naar object-opslag
- Genereren van tijdelijke download-URL's (presigned URL's)
- Verwijderen van objecten (retentie-beheer)

Don't use when:
- Je adresgegevens nodig hebt (gebruik module-pdok-geocode)
- Je een notificatie wilt versturen (gebruik module-notificatie)
""",
)

module = ObjectstoreModule(
    endpoint_url=os.getenv("S3_ENDPOINT_URL"),
    access_key=os.getenv("S3_ACCESS_KEY"),
    secret_key=os.getenv("S3_SECRET_KEY"),
    bucket_name=os.getenv("S3_BUCKET_NAME"),
    region=os.getenv("S3_REGION"),
)


@mcp.tool(
    name="upload_object",
    description="Upload een bestand (base64-encoded bytes) naar een S3-bucket en retourneer de object-key.",
    meta={
        "module_id": MODULE_ID,
        "version": MODULE_VERSION,
        "resource_metrics": {
            "processing_ms": {"type": "integer", "unit": "milliseconds"},
            "size_bytes": {"type": "integer", "unit": "bytes"},
        },
    },
)
async def upload_object(
    data: str,
    filename: str,
    content_type: str = "application/octet-stream",
    prefix: str = "",
    user_id: str = "",
    project_id: str = "",
    session_id: str = "",
    app_id: str = "",
) -> dict:
    """Upload a file to the S3 bucket.

    Args:
        data: Base64-encoded file content.
        filename: Original filename.
        content_type: MIME type (default: application/octet-stream).
        prefix: Optional key prefix (folder path).
    """
    start = time.time()
    result = await module.upload_object(
        data=data,
        filename=filename,
        content_type=content_type,
        prefix=prefix,
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
                "resources": {
                    "processing_ms": elapsed_ms,
                    "size_bytes": result.get("size_bytes", 0),
                },
            },
        },
    }


@mcp.tool(
    name="get_object_url",
    description="Genereer een tijdelijke presigned URL voor download van een object.",
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
    expires_in: int = 3600,
    user_id: str = "",
    project_id: str = "",
    session_id: str = "",
    app_id: str = "",
) -> dict:
    """Generate a presigned download URL.

    Args:
        object_key: The S3 object key.
        expires_in: URL expiration in seconds (60-86400, default 3600).
    """
    start = time.time()
    result = await module.get_object_url(
        object_key=object_key,
        expires_in=expires_in,
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
    description="Verwijder een object uit de bucket (voor retentie-beheer).",
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
) -> dict:
    """Delete an object from the bucket.

    Args:
        object_key: The S3 object key to delete.
    """
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
