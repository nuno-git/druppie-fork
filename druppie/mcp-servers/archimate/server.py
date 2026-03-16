"""ArchiMate MCP Server.

Provides read-only access to ArchiMate models for architecture analysis.
Uses FastMCP framework for HTTP transport.
"""

import logging
import os

from fastmcp import FastMCP

from module import ArchiMateModule

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("archimate-mcp")

mcp = FastMCP("ArchiMate MCP Server")

MODELS_DIR = os.getenv("MODELS_DIR", "/models")

module = ArchiMateModule(models_dir=MODELS_DIR)


@mcp.tool()
async def list_models() -> dict:
    """List all available ArchiMate models."""
    return module.list_models()


@mcp.tool()
async def get_statistics(model_name: str = "") -> dict:
    """Get overview statistics for an ArchiMate model: element counts per layer/type, relationship counts."""
    return module.get_statistics(model_name=model_name)


@mcp.tool()
async def list_elements(
    model_name: str = "",
    layer: str = "",
    element_type: str = "",
    max_results: int = 50,
    offset: int = 0,
) -> dict:
    """List elements in the model. Filter by layer (Strategy/Business/Application/Technology/Motivation) or type (BusinessProcess, ApplicationComponent, etc.)."""
    return module.list_elements(
        model_name=model_name,
        layer=layer,
        element_type=element_type,
        max_results=max_results,
        offset=offset,
    )


@mcp.tool()
async def get_element(element_name: str, model_name: str = "") -> dict:
    """Get full details of an element by name or ID, including all its relationships, views, and properties."""
    return module.get_element(model_name=model_name, element_name=element_name)


@mcp.tool()
async def list_views(model_name: str = "") -> dict:
    """List all views/diagrams in the ArchiMate model."""
    return module.list_views(model_name=model_name)


@mcp.tool()
async def get_view(view_id: str, model_name: str = "") -> dict:
    """Get all elements and relationships shown on a specific view/diagram by view name or ID."""
    return module.get_view(model_name=model_name, view_id=view_id)


@mcp.tool()
async def search_model(
    query: str,
    model_name: str = "",
    layer: str = "",
    element_type: str = "",
    max_results: int = 20,
) -> dict:
    """Search for elements by name, description, or property value. Optionally filter by layer or type."""
    return module.search_model(
        model_name=model_name,
        query=query,
        layer=layer,
        element_type=element_type,
        max_results=max_results,
    )


@mcp.tool()
async def get_impact(
    element_name: str,
    model_name: str = "",
    direction: str = "both",
    max_depth: int = 3,
) -> dict:
    """Analyze impact: traverse relationships from an element to find all connected elements. Direction: 'downstream' (what this serves/triggers), 'upstream' (what depends on this), or 'both'."""
    return module.get_impact(
        model_name=model_name,
        element_name=element_name,
        direction=direction,
        max_depth=max_depth,
    )


if __name__ == "__main__":
    import uvicorn
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    app = mcp.http_app()

    async def health(request):
        """Health check endpoint."""
        return JSONResponse({
            "status": "healthy",
            "service": "archimate-mcp",
            "models_loaded": len(module.models),
        })

    app.routes.insert(0, Route("/health", health, methods=["GET"]))

    port = int(os.getenv("MCP_PORT", "9006"))

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        log_level="info",
    )
