"""Boter-Kaas-Eieren MCP Server — Version Router.

Routes requests to the correct version:
  /v1/mcp → v1/tools.py
  /mcp    → latest version
Also provides HTTP API endpoints for the web UI.
"""

import logging
import os
from pathlib import Path
import json

import yaml
import uvicorn
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("boter-kaas-eieren-mcp")

# Read MODULE.yaml for version info
MANIFEST_PATH = Path(__file__).parent / "MODULE.yaml"
with open(MANIFEST_PATH) as f:
    manifest = yaml.safe_load(f)

latest_version = manifest["latest_version"]
major_latest = latest_version.split(".")[0]

# Import version-specific MCP apps
from v1.tools import mcp as v1_mcp
from v1 import module as v1_module

version_apps = {
    "1": v1_mcp.http_app(),
}


# HTTP API endpoints for web UI
async def new_game_handler(request):
    """HTTP endpoint to create a new game."""
    result = v1_module.new_game()
    return JSONResponse(result)


async def make_move_handler(request):
    """HTTP endpoint to make a move."""
    data = await request.json()
    game_id = data.get("game_id")
    position = data.get("position")
    result = v1_module.make_move(game_id, position)
    return JSONResponse(result)


async def get_state_handler(request):
    """HTTP endpoint to get game state."""
    game_id = request.query_params.get("game_id")
    if not game_id:
        return JSONResponse({"error": "game_id is required"}, status_code=400)
    result = v1_module.get_game_state(game_id)
    return JSONResponse(result)


async def health(request):
    """Aggregate health: reports status of all active versions."""
    return JSONResponse(
        {
            "status": "healthy",
            "module_id": manifest["id"],
            "latest_version": latest_version,
            "active_versions": manifest["versions"],
        }
    )


async def version_health(request):
    """Per-version health check."""
    major = request.path_params["major"]
    if major not in version_apps:
        return JSONResponse({"status": "not_found"}, status_code=404)
    return JSONResponse(
        {
            "status": "healthy",
            "module_id": manifest["id"],
            "version": f"v{major}",
        }
    )


# Build routes
routes = [
    # Health checks
    Route("/health", health, methods=["GET"]),
    Route("/v{major}/health", version_health, methods=["GET"]),
    # HTTP API for web UI
    Route("/api/new-game", new_game_handler, methods=["POST"]),
    Route("/api/move", make_move_handler, methods=["POST"]),
    Route("/api/state", get_state_handler, methods=["GET"]),
    # Static files
    Mount("/static", app=StaticFiles(directory="static"), name="static"),
]

# MCP endpoints (versioned)
for major, app in version_apps.items():
    routes.append(Mount(f"/v{major}", app=app))

# /mcp → latest version
routes.append(Mount("/", app=version_apps[major_latest]))

app = Starlette(routes=routes)

if __name__ == "__main__":
    port = int(os.getenv("MCP_PORT", "9010"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
