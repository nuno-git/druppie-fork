"""Registry MCP Server.

Provides read-only access to Druppie's building block catalog:
agents, skills, MCP servers, and builtin tools.
"""

import logging
import os

from fastmcp import FastMCP

from module import RegistryModule

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("registry-mcp")

mcp = FastMCP("Registry MCP Server")

DATA_DIR = os.getenv("DATA_DIR", "/data")

module = RegistryModule(data_dir=DATA_DIR)


@mcp.tool()
async def list_components(category: str = "") -> dict:
    """List all Druppie building blocks: agents, skills, MCP servers, and builtin tools. Optionally filter by category."""
    return module.list_components(category=category)


@mcp.tool()
async def get_agent(agent_id: str) -> dict:
    """Get full details of an agent: description, skills, MCP tools, builtin tools, approval overrides, and config."""
    return module.get_agent(agent_id=agent_id)


@mcp.tool()
async def get_skill(skill_name: str) -> dict:
    """Get full skill content including instructions and allowed tools."""
    return module.get_skill(skill_name=skill_name)


@mcp.tool()
async def get_mcp_server(server_name: str) -> dict:
    """Get MCP server details: description, full tool list with descriptions, and which agents use it."""
    return module.get_mcp_server(server_name=server_name)


@mcp.tool()
async def get_tool(server_name: str, tool_name: str) -> dict:
    """Get full tool definition: parameters, approval requirements, and per-agent overrides."""
    return module.get_tool(server_name=server_name, tool_name=tool_name)


if __name__ == "__main__":
    import uvicorn
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    app = mcp.http_app()

    async def health(request):
        """Health check endpoint."""
        return JSONResponse({
            "status": "healthy",
            "service": "registry-mcp",
            "agents_loaded": len(module.agents),
            "skills_loaded": len(module.skills),
            "mcp_servers_loaded": len(module.mcp_servers),
            "builtin_tools_loaded": len(module.builtin_tools),
        })

    app.routes.insert(0, Route("/health", health, methods=["GET"]))

    port = int(os.getenv("MCP_PORT", "9007"))

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        log_level="info",
    )
