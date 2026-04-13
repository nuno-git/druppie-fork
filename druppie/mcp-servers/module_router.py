"""Shared version router factory for MCP module servers.

Every module server has the same structure: read MODULE.yaml, mount versioned
MCP apps, expose /health, and wire the FastMCP lifespan. This factory
eliminates the duplication.

Usage in a module's server.py:

    from module_router import create_module_app
    app = create_module_app("coding", default_port=9001)
    # That's it — `app` is a Starlette application ready for uvicorn.
"""

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

import yaml
import uvicorn
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route


def create_module_app(
    module_name: str,
    default_port: int,
    *,
    module_dir: Path | None = None,
) -> Starlette:
    """Create a versioned Starlette app for an MCP module.

    Args:
        module_name: Human-readable name for logging (e.g. "coding").
        default_port: Fallback port when MCP_PORT env var is unset.
        module_dir: Root directory of the module. Defaults to caller's directory
                    (works when server.py and MODULE.yaml are siblings).

    Returns:
        A fully configured Starlette application.
    """
    if module_dir is None:
        # Resolve relative to the calling server.py — but since this is
        # imported as a copied file in /app, use CWD which is /app.
        module_dir = Path.cwd()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    logger = logging.getLogger(f"{module_name}-mcp")

    # Read MODULE.yaml
    manifest_path = module_dir / "MODULE.yaml"
    with open(manifest_path) as f:
        manifest = yaml.safe_load(f)

    latest_version = manifest["latest_version"]
    major_latest = latest_version.split(".")[0]

    # Import version-specific MCP app (v1/tools.py must define `mcp`)
    from v1.tools import mcp as v1_mcp

    version_apps = {
        "1": v1_mcp.http_app(),
    }

    async def health(request):
        return JSONResponse({
            "status": "healthy",
            "module_id": manifest["id"],
            "latest_version": latest_version,
            "active_versions": manifest["versions"],
        })

    # Build routes
    routes = [
        Route("/health", health, methods=["GET"]),
    ]
    for major, app in version_apps.items():
        routes.append(Mount(f"/v{major}", app=app))

    # /mcp → latest version
    routes.append(Mount("/", app=version_apps[major_latest]))

    @asynccontextmanager
    async def lifespan(app):
        async with version_apps[major_latest].router.lifespan_context(
            version_apps[major_latest]
        ):
            yield

    return Starlette(routes=routes, lifespan=lifespan)


def run_module(module_name: str, default_port: int) -> None:
    """Create and run a module server (convenience for __main__ blocks)."""
    app = create_module_app(module_name, default_port)
    port = int(os.getenv("MCP_PORT", str(default_port)))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
