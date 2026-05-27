"""Agents API routes.

Endpoints for listing available agents and their configuration.
Provides transparency about which models each agent uses.
"""

import os
from pathlib import Path

from uuid import UUID

import structlog
import yaml
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from druppie.api.deps import get_current_user, get_custom_agent_service, get_user_roles, require_any_role


def _get_user_id(user: dict) -> UUID:
    """Extract and validate user UUID from JWT token."""
    try:
        return UUID(user["sub"])
    except (ValueError, KeyError):
        raise HTTPException(status_code=401, detail="Invalid user identity in token")
from druppie.domain.custom_agent import CustomAgentCreate, CustomAgentUpdate
from druppie.services.custom_agent_service import CustomAgentService

logger = structlog.get_logger()

router = APIRouter()


# =============================================================================
# RESPONSE MODELS
# =============================================================================


class AgentResponse(BaseModel):
    """Agent response model for transparency."""

    id: str
    name: str
    description: str
    # Model configuration (transparency)
    model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    max_iterations: int | None = None
    # MCP tools this agent can use
    mcps: list[str] = []
    # Category for UI grouping
    category: str = "execution"


class AgentsListResponse(BaseModel):
    """List of agents response."""

    agents: list[AgentResponse]
    total: int


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def load_agent_definitions() -> list[AgentResponse]:
    """Load all agent definitions from YAML files.

    Returns:
        List of AgentResponse objects with model configuration
    """
    agents = []
    definitions_dir = Path(__file__).parent.parent.parent / "agents" / "definitions"

    if not definitions_dir.exists():
        logger.warning("agent_definitions_dir_not_found", path=str(definitions_dir))
        return agents

    for yaml_file in definitions_dir.glob("*.yaml"):
        try:
            with open(yaml_file, "r") as f:
                data = yaml.safe_load(f)

            if not data or not data.get("id"):
                continue

            # Determine MCP list (can be list or dict)
            mcps = data.get("mcps", [])
            if isinstance(mcps, dict):
                mcp_list = list(mcps.keys())
            else:
                mcp_list = mcps

            # Read category from YAML definition (default: execution)
            category = data.get("category", "execution")

            agent = AgentResponse(
                id=data.get("id"),
                name=data.get("name", data.get("id")),
                description=data.get("description", ""),
                model=data.get("model"),
                temperature=data.get("temperature"),
                max_tokens=data.get("max_tokens"),
                max_iterations=data.get("max_iterations"),
                mcps=mcp_list,
                category=category,
            )
            agents.append(agent)

        except Exception as e:
            logger.error(
                "failed_to_load_agent_definition",
                file=str(yaml_file),
                error=str(e),
                exc_info=True,
            )

    # Sort agents by category (system first, then execution, quality, deployment)
    category_order = {"system": 0, "execution": 1, "quality": 2, "deployment": 3}
    agents.sort(key=lambda a: (category_order.get(a.category, 99), a.name))

    return agents


# =============================================================================
# ROUTES
# =============================================================================


@router.get("/agents", response_model=AgentsListResponse)
async def list_agents(
    user: dict = Depends(get_current_user),
):
    """List all configured agents with their model information.

    Returns agent definitions including:
    - Model used (for transparency)
    - Temperature and max_tokens settings
    - MCP tools accessible to the agent
    """
    agents = load_agent_definitions()

    logger.info(
        "agents_listed",
        user_id=user.get("sub"),
        count=len(agents),
    )

    return AgentsListResponse(
        agents=agents,
        total=len(agents),
    )


# =============================================================================
# CUSTOM AGENT ENDPOINTS
# (Must be defined before /agents/{agent_id} to avoid path conflicts)
# =============================================================================


@router.get("/agents/metadata")
async def get_agent_metadata(
    service: CustomAgentService = Depends(get_custom_agent_service),
    user: dict = Depends(get_current_user),
):
    """Get available MCPs, skills, tools, profiles for the agent editor form."""
    return service.get_metadata()


@router.get("/agents/custom")
async def list_custom_agents(
    service: CustomAgentService = Depends(get_custom_agent_service),
    user: dict = Depends(get_current_user),
):
    """List custom agents visible to the current user.

    Admin/developer roles see all agents. Others see only their own.
    """
    user_id = _get_user_id(user)
    roles = get_user_roles(user)
    agents = service.list_custom_agents_for_user(user_id, roles)
    return {"agents": [a.model_dump() for a in agents], "total": len(agents)}


@router.post("/agents/custom")
async def create_custom_agent(
    data: CustomAgentCreate,
    service: CustomAgentService = Depends(get_custom_agent_service),
    user: dict = Depends(get_current_user),
    _role=Depends(require_any_role(["developer", "admin", "architect"])),
):
    """Create a new custom agent. Requires developer, admin, or architect role."""
    owner_id = _get_user_id(user)
    detail = service.create_custom_agent(data, owner_id)
    return detail.model_dump()


@router.get("/agents/custom/{agent_id}")
async def get_custom_agent(
    agent_id: str,
    service: CustomAgentService = Depends(get_custom_agent_service),
    user: dict = Depends(get_current_user),
):
    """Get a custom agent's full configuration."""
    user_id = _get_user_id(user)
    roles = get_user_roles(user)
    detail = service.get_custom_agent(agent_id)
    if detail.owner_id != user_id and not any(r in roles for r in ("admin", "developer")):
        raise HTTPException(status_code=403, detail="Not authorized to view this agent")
    return detail.model_dump()


@router.put("/agents/custom/{agent_id}")
async def update_custom_agent(
    agent_id: str,
    data: CustomAgentUpdate,
    service: CustomAgentService = Depends(get_custom_agent_service),
    user: dict = Depends(get_current_user),
):
    """Update a custom agent."""
    user_id = _get_user_id(user)
    roles = get_user_roles(user)
    detail = service.update_custom_agent(agent_id, data, user_id, user_roles=roles)
    return detail.model_dump()


@router.delete("/agents/custom/{agent_id}", status_code=204)
async def delete_custom_agent(
    agent_id: str,
    service: CustomAgentService = Depends(get_custom_agent_service),
    user: dict = Depends(get_current_user),
):
    """Delete a custom agent."""
    user_id = _get_user_id(user)
    roles = get_user_roles(user)
    service.delete_custom_agent(agent_id, user_id, user_roles=roles)


@router.get("/agents/custom/{agent_id}/yaml")
async def export_custom_agent_yaml(
    agent_id: str,
    service: CustomAgentService = Depends(get_custom_agent_service),
    user: dict = Depends(get_current_user),
):
    """Export a custom agent as YAML."""
    user_id = _get_user_id(user)
    roles = get_user_roles(user)
    detail = service.get_custom_agent(agent_id)
    if detail.owner_id != user_id and not any(r in roles for r in ("admin", "developer")):
        raise HTTPException(status_code=403, detail="Not authorized to view this agent")
    yaml_str = service.export_as_yaml(agent_id)
    return {"agent_id": agent_id, "yaml": yaml_str}


class YamlUpdateRequest(BaseModel):
    yaml: str = Field(..., max_length=65536)


@router.put("/agents/custom/{agent_id}/yaml")
async def update_custom_agent_yaml(
    agent_id: str,
    body: YamlUpdateRequest,
    service: CustomAgentService = Depends(get_custom_agent_service),
    user: dict = Depends(get_current_user),
):
    """Update a custom agent from raw YAML."""
    user_id = _get_user_id(user)
    try:
        data = yaml.safe_load(body.yaml)
    except yaml.YAMLError as e:
        raise HTTPException(status_code=400, detail=f"Invalid YAML: {e}")

    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="YAML must be a mapping")

    # Parse Azure Foundry agent format (has "definition" block)
    definition = data.get("definition") or {}
    is_foundry_format = bool(definition)

    if is_foundry_format:
        # Extract tools as list of type strings from Foundry tool objects
        tools_raw = definition.get("tools") or []
        foundry_tools = [
            t["type"] if isinstance(t, dict) else t
            for t in tools_raw
            if (isinstance(t, dict) and "type" in t) or isinstance(t, str)
        ]

        # Extract per-tool config from tool_resources (e.g. vector_store_ids for file_search)
        tool_resources = data.get("tool_resources") or definition.get("tool_resources") or {}
        foundry_tool_configs: dict = {}
        for tool_key, res in tool_resources.items():
            if isinstance(res, dict) and res:
                foundry_tool_configs[tool_key] = res

        update = CustomAgentUpdate(
            name=data.get("name"),
            description=data.get("description") or (data.get("metadata") or {}).get("description"),
            system_prompt=definition.get("instructions"),
            llm_profile=definition.get("model"),
            temperature=definition.get("temperature"),
            max_tokens=definition.get("max_tokens"),
            max_iterations=definition.get("max_iterations"),
            foundry_tools=foundry_tools,
            foundry_tool_configs=foundry_tool_configs if foundry_tool_configs else None,
        )
    else:
        update = CustomAgentUpdate(
            name=data.get("name"),
            description=data.get("description"),
            category=data.get("category"),
            system_prompt=data.get("system_prompt"),
            llm_profile=data.get("llm_profile"),
            temperature=data.get("temperature"),
            max_tokens=data.get("max_tokens"),
            max_iterations=data.get("max_iterations"),
            mcps=data.get("mcps"),
            skills=data.get("skills"),
            system_prompts=data.get("system_prompts"),
            druppie_runtime_tools=data.get("druppie_runtime_tools"),
            approval_overrides=data.get("approval_overrides"),
            foundry_tools=data.get("foundry_tools"),
            foundry_tool_configs=data.get("foundry_tool_configs"),
        )
    detail = service.update_custom_agent(agent_id, update, user_id)
    return detail.model_dump()


@router.post("/agents/custom/{agent_id}/validate")
async def validate_custom_agent(
    agent_id: str,
    service: CustomAgentService = Depends(get_custom_agent_service),
    user: dict = Depends(get_current_user),
):
    """Validate a custom agent's configuration."""
    user_id = _get_user_id(user)
    roles = get_user_roles(user)
    detail = service.get_custom_agent(agent_id)
    if detail.owner_id != user_id and not any(r in roles for r in ("admin", "developer")):
        raise HTTPException(status_code=403, detail="Not authorized to validate this agent")
    warnings = service.validate_agent(agent_id)
    return {"valid": len(warnings) == 0, "warnings": warnings}


@router.post("/agents/custom/{agent_id}/validate-foundry")
async def validate_for_foundry(
    agent_id: str,
    service: CustomAgentService = Depends(get_custom_agent_service),
    user: dict = Depends(get_current_user),
):
    """Validate a custom agent definition is deployable to Azure AI Foundry.

    Returns validation results with errors (blocking) and warnings (informational).
    """
    user_id = _get_user_id(user)
    roles = get_user_roles(user)
    detail = service.get_custom_agent(agent_id)
    if detail.owner_id != user_id and not any(r in roles for r in ("admin", "developer")):
        raise HTTPException(status_code=403, detail="Not authorized to validate this agent")
    return service.validate_for_foundry(agent_id)


@router.post("/agents/custom/{agent_id}/deploy")
async def deploy_custom_agent(
    agent_id: str,
    service: CustomAgentService = Depends(get_custom_agent_service),
    user: dict = Depends(get_current_user),
    _: bool = Depends(require_any_role(["developer", "admin"])),
):
    """Deploy a custom agent to Azure AI Foundry.

    Requires developer or admin role.
    """
    user_id = _get_user_id(user)
    roles = get_user_roles(user)
    return service.deploy_custom_agent(agent_id, user_id, user_roles=roles)


@router.post("/agents/custom/{agent_id}/undeploy")
async def undeploy_custom_agent(
    agent_id: str,
    service: CustomAgentService = Depends(get_custom_agent_service),
    user: dict = Depends(get_current_user),
    _: bool = Depends(require_any_role(["developer", "admin"])),
):
    """Remove a custom agent from Azure AI Foundry.

    Requires developer or admin role.
    """
    user_id = _get_user_id(user)
    roles = get_user_roles(user)
    return service.undeploy_custom_agent(agent_id, user_id, user_roles=roles)


# =============================================================================
# SINGLE AGENT LOOKUP (must be after /agents/custom and /agents/metadata)
# =============================================================================


@router.get("/agents/{agent_id}", response_model=AgentResponse)
async def get_agent(
    agent_id: str,
    user: dict = Depends(get_current_user),
):
    """Get a specific agent's configuration."""
    agents = load_agent_definitions()

    for agent in agents:
        if agent.id == agent_id:
            return agent

    from druppie.api.errors import NotFoundError

    raise NotFoundError("agent", agent_id)
