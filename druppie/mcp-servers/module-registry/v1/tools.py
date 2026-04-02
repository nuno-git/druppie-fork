"""Registry v1 — MCP Tool Definitions.

Module-first registry for the Druppie platform. Every MCP server IS a module.

Tools are organized in two groups:
- Module tools: list_modules, get_module, search_modules
- Component tools: list_components, get_agent, get_skill

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
    instructions=(
        "Druppie platform registry. Every MCP server is a module — use "
        "list_modules/get_module/search_modules to discover modules and their "
        "tools. Use list_components/get_agent/get_skill for agents, skills, "
        "and builtin tools."
    ),
)

DATA_DIR = os.getenv("DATA_DIR", "/data")
module = RegistryModule(data_dir=DATA_DIR)


# ── Module tools ─────────────────────────────────────────────────────────

@mcp.tool(
    name="list_modules",
    description=(
        "List all available Druppie modules with their versions, type, tool "
        "count, and which agents use them. Optionally filter by type: 'core' "
        "(agents only) or 'module' (apps only). Empty = all."    
        ),
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
async def list_modules(category: str = "") -> dict:
    return module.list_modules(category=category)


@mcp.tool(
    name="get_module",
    description=(
        "Get detailed info for a specific module: versions, description, full "
        "tool list with schemas and approval rules, and which agents use it. "
        "Fetches live tool schemas from the running MCP server when available. "
        "Optionally specify a version to inspect (e.g. 'v1', 'v2')."
    ),
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
async def get_module(module_id: str, version: str = "") -> dict:
    return await module.get_module(module_id=module_id, version=version)


@mcp.tool(
    name="search_modules",
    description=(
        "Search modules by keyword across module IDs, tool names, and "
        "descriptions. Use this to check if a capability already exists "
        "before proposing a new module."
    ),
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
async def search_modules(query: str) -> dict:
    return module.search_modules(query=query)


# ── Component tools (agents, skills, builtin tools) ─────────────────────

@mcp.tool(
    name="list_components",
    description=(
        "List agents, skills, and builtin tools. For modules, use "
        "list_modules() instead. Optionally filter by category: 'agents', "
        "'skills', or 'builtin_tools'."
    ),
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
async def list_components(category: str = "") -> dict:
    return module.list_components(category=category)


@mcp.tool(
    name="get_agent",
    description=(
        "Get full details of an agent: description, skills, modules it uses, "
        "builtin tools, approval overrides, and config."
    ),
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
