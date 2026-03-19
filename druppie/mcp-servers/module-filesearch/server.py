"""File Search MCP Server — Version Router.

Routes requests to the correct version:
  /v1/mcp → v1/tools.py
  /mcp    → latest version (from MODULE.yaml)
  /health → aggregate health
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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("filesearch-mcp")

# Read MODULE.yaml
MANIFEST_PATH = Path(__file__).parent / "MODULE.yaml"
with open(MANIFEST_PATH) as f:
    manifest = yaml.safe_load(f)

latest_version = manifest["latest_version"]
major_latest = latest_version.split(".")[0]

# Import version-specific MCP apps
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
    async with version_apps[major_latest].router.lifespan_context(version_apps[major_latest]):
        yield


app = Starlette(routes=routes, lifespan=lifespan)

if __name__ == "__main__":
    port = int(os.getenv("MCP_PORT", "9004"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
