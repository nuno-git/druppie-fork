"""ArchiMate v1 — MCP Tool Definitions.

Single source of truth for tool contract:
- Tool name, description, input schema via @mcp.tool()
- Version and module_id via @mcp.tool(meta={...})
- Agent guidance via FastMCP(instructions=...)
"""

import os
from fastmcp import FastMCP
from .module import ArchiMateModule

MODULE_ID = "archimate"
MODULE_VERSION = "1.0.0"

mcp = FastMCP(
    "ArchiMate v1",
    version=MODULE_VERSION,
    instructions="""Read-only ArchiMate architecture reference. Use for querying elements, relationships, views, and impact analysis.""",
)

MODELS_DIR = os.getenv("MODELS_DIR", "/models")
module = ArchiMateModule(models_dir=MODELS_DIR)


@mcp.tool(
    name="list_models",
    description="List all available ArchiMate models.",
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
async def list_models() -> dict:
    return module.list_models()


@mcp.tool(
    name="get_statistics",
    description="Get overview statistics for an ArchiMate model: element counts per layer/type, relationship counts.",
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
async def get_statistics(model_name: str = "") -> dict:
    return module.get_statistics(model_name=model_name)


@mcp.tool(
    name="list_elements",
    description="List elements in the model. Filter by layer (Strategy/Business/Application/Technology/Motivation) or type (BusinessProcess, ApplicationComponent, etc.).",
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
async def list_elements(
    model_name: str = "",
    layer: str = "",
    element_type: str = "",
    max_results: int = 50,
    offset: int = 0,
) -> dict:
    return module.list_elements(
        model_name=model_name,
        layer=layer,
        element_type=element_type,
        max_results=max_results,
        offset=offset,
    )


@mcp.tool(
    name="get_element",
    description="Get full details of an element by name or ID, including all its relationships, views, and properties.",
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
async def get_element(element_name: str, model_name: str = "") -> dict:
    return module.get_element(model_name=model_name, element_name=element_name)


@mcp.tool(
    name="list_views",
    description="List all views/diagrams in the ArchiMate model.",
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
async def list_views(model_name: str = "") -> dict:
    return module.list_views(model_name=model_name)


@mcp.tool(
    name="get_view",
    description="Get all elements and relationships shown on a specific view/diagram by view name or ID.",
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
async def get_view(view_id: str, model_name: str = "") -> dict:
    return module.get_view(model_name=model_name, view_id=view_id)


@mcp.tool(
    name="search_model",
    description="Search for elements by name, description, or property value. Optionally filter by layer or type.",
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
async def search_model(
    query: str,
    model_name: str = "",
    layer: str = "",
    element_type: str = "",
    max_results: int = 20,
) -> dict:
    return module.search_model(
        model_name=model_name,
        query=query,
        layer=layer,
        element_type=element_type,
        max_results=max_results,
    )


@mcp.tool(
    name="get_impact",
    description="Analyze impact: traverse relationships from an element to find all connected elements. Direction: 'downstream' (what this serves/triggers), 'upstream' (what depends on this), or 'both'.",
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
async def get_impact(
    element_name: str,
    model_name: str = "",
    direction: str = "both",
    max_depth: int = 3,
) -> dict:
    return module.get_impact(
        model_name=model_name,
        element_name=element_name,
        direction=direction,
        max_depth=max_depth,
    )
