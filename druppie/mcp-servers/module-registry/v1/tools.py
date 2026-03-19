"""Registry v1 — MCP Tool Definitions.

Single source of truth for tool contract:
- Tool name, description, input schema via @mcp.tool()
- Version and module_id via @mcp.tool(meta={...})
- Agent guidance via FastMCP(instructions=...)
"""

import os
from fastmcp import FastMCP
from .module import RegistryModule

MODULE_ID = "registry"
MODULE_VERSION = "1.0.0"

mcp = FastMCP(
    "Registry v1",
    version=MODULE_VERSION,
    instructions="Druppie platform building block catalog. List and inspect agents, skills, MCP tools, and builtin tools.",
)

DATA_DIR = os.getenv("DATA_DIR", "/data")
module = RegistryModule(data_dir=DATA_DIR)


@mcp.tool(
    name="list_components",
    description="List all Druppie building blocks: agents, skills, MCP servers, and builtin tools. Optionally filter by category.",
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
async def list_components(category: str = "") -> dict:
    return module.list_components(category=category)


@mcp.tool(
    name="get_agent",
    description="Get full details of an agent: description, skills, MCP tools, builtin tools, approval overrides, and config.",
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
async def get_agent(agent_id: str) -> dict:
    return module.get_agent(agent_id=agent_id)


@mcp.tool(
    name="get_skill",
    description="Get full skill content including instructions and allowed tools.",
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
async def get_skill(skill_name: str) -> dict:
    return module.get_skill(skill_name=skill_name)


@mcp.tool(
    name="get_mcp_server",
    description="Get MCP server details: description, full tool list with descriptions, and which agents use it.",
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
async def get_mcp_server(server_name: str) -> dict:
    return module.get_mcp_server(server_name=server_name)


@mcp.tool(
    name="get_tool",
    description="Get full tool definition: parameters, approval requirements, and per-agent overrides.",
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
async def get_tool(server_name: str, tool_name: str) -> dict:
    return module.get_tool(server_name=server_name, tool_name=tool_name)
