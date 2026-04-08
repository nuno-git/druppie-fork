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
from pydantic import BaseModel
from sqlalchemy.orm import Session

from druppie.api.deps import get_current_user, get_custom_agent_service
from druppie.db.database import get_db
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


# =============================================================================
# CUSTOM AGENT ENDPOINTS
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
    """List all custom agents."""
    agents = service.list_custom_agents()
    return {"agents": [a.model_dump() for a in agents], "total": len(agents)}


@router.post("/agents/custom")
async def create_custom_agent(
    data: CustomAgentCreate,
    service: CustomAgentService = Depends(get_custom_agent_service),
    user: dict = Depends(get_current_user),
):
    """Create a new custom agent."""
    owner_id = UUID(user["sub"])
    detail = service.create_custom_agent(data, owner_id)
    return detail.model_dump()


@router.get("/agents/custom/{agent_id}")
async def get_custom_agent(
    agent_id: str,
    service: CustomAgentService = Depends(get_custom_agent_service),
    user: dict = Depends(get_current_user),
):
    """Get a custom agent's full configuration."""
    detail = service.get_custom_agent(agent_id)
    return detail.model_dump()


@router.put("/agents/custom/{agent_id}")
async def update_custom_agent(
    agent_id: str,
    data: CustomAgentUpdate,
    service: CustomAgentService = Depends(get_custom_agent_service),
    user: dict = Depends(get_current_user),
):
    """Update a custom agent."""
    user_id = UUID(user["sub"])
    detail = service.update_custom_agent(agent_id, data, user_id)
    return detail.model_dump()


@router.delete("/agents/custom/{agent_id}", status_code=204)
async def delete_custom_agent(
    agent_id: str,
    service: CustomAgentService = Depends(get_custom_agent_service),
    user: dict = Depends(get_current_user),
):
    """Delete a custom agent."""
    user_id = UUID(user["sub"])
    service.delete_custom_agent(agent_id, user_id)


@router.get("/agents/custom/{agent_id}/yaml")
async def export_custom_agent_yaml(
    agent_id: str,
    service: CustomAgentService = Depends(get_custom_agent_service),
    user: dict = Depends(get_current_user),
):
    """Export a custom agent as YAML."""
    yaml_str = service.export_as_yaml(agent_id)
    return {"agent_id": agent_id, "yaml": yaml_str}


@router.post("/agents/custom/{agent_id}/validate")
async def validate_custom_agent(
    agent_id: str,
    service: CustomAgentService = Depends(get_custom_agent_service),
    user: dict = Depends(get_current_user),
):
    """Validate a custom agent's configuration."""
    detail = service.get_custom_agent(agent_id)
    data = CustomAgentCreate(
        agent_id=detail.agent_id,
        name=detail.name,
        description=detail.description,
        category=detail.category,
        system_prompt=detail.system_prompt,
        system_prompts=detail.system_prompts,
        extra_builtin_tools=detail.extra_builtin_tools,
        mcps=detail.mcps,
        approval_overrides=detail.approval_overrides,
        skills=detail.skills,
        llm_profile=detail.llm_profile,
        temperature=detail.temperature,
        max_tokens=detail.max_tokens,
        max_iterations=detail.max_iterations,
    )
    warnings = service.validate_definition(data)
    return {"valid": len(warnings) == 0, "warnings": warnings}


@router.post("/agents/custom/{agent_id}/deploy")
async def deploy_custom_agent(
    agent_id: str,
    service: CustomAgentService = Depends(get_custom_agent_service),
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Deploy a custom agent to Azure AI Foundry."""
    from druppie.services.foundry_service import FoundryService, FoundryNotConfiguredError
    from druppie.core.config import get_settings

    settings = get_settings()
    foundry = FoundryService(endpoint=settings.foundry_project_endpoint)

    if not foundry.is_configured():
        raise HTTPException(
            status_code=503,
            detail="Azure AI Foundry is not configured. Set FOUNDRY_PROJECT_ENDPOINT in .env.",
        )

    detail = service.get_custom_agent(agent_id)

    try:
        result = foundry.deploy_agent(detail)

        # Update deployment status in DB
        from druppie.repositories import CustomAgentRepository
        repo = CustomAgentRepository(db)
        agent = repo.get_by_agent_id(agent_id)
        if agent:
            from datetime import datetime, timezone
            agent.deployment_status = "deployed"
            agent.deployed_at = datetime.now(timezone.utc)
            db.commit()

        return result
    except FoundryNotConfiguredError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        # Update status to failed
        from druppie.repositories import CustomAgentRepository
        repo = CustomAgentRepository(db)
        agent = repo.get_by_agent_id(agent_id)
        if agent:
            agent.deployment_status = "failed"
            db.commit()
        raise HTTPException(status_code=500, detail=f"Deployment failed: {str(e)}")
