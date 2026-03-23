"""LLM Integration MCP Server.

Centralized LLM abstraction layer with multi-provider support.
Uses FastMCP framework for HTTP transport.
"""

import os
from pathlib import Path

# Add v1 to path for imports
import sys

sys.path.insert(0, str(Path(__file__).parent))

from fastmcp import FastMCP
from starlette.responses import JSONResponse
from starlette.routing import Route

from v1.config import get_config
from v1.logging import configure_logging, get_logger
from v1.module import initialize_module
from v1.tools import register_tools

# Configure logging
config = get_config()
configure_logging(config.log_level)
logger = get_logger()

# Initialize FastMCP server
mcp = FastMCP("LLM Integration MCP Server")

# Initialize module
module = initialize_module()

# Register tools
register_tools(mcp)


async def health(request):
    """Health check endpoint."""
    health_status = module.health_check()
    status_code = 200 if health_status["status"] == "healthy" else 503
    return JSONResponse(health_status, status_code=status_code)


async def ready(request):
    """Readiness check endpoint."""
    if module.is_initialized():
        return JSONResponse({"ready": True})
    return JSONResponse({"ready": False}, status_code=503)


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    import uvicorn

    # Get MCP app with HTTP transport
    app = mcp.http_app()

    # Add health endpoints
    app.routes.insert(0, Route("/health", health, methods=["GET"]))
    app.routes.insert(0, Route("/ready", ready, methods=["GET"]))

    port = int(os.getenv("MCP_PORT", "9003"))

    logger.info(
        "Starting LLM Integration MCP Server",
        port=port,
        providers=len(config.providers),
    )

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        log_level=config.log_level.lower(),
    )
