"""Agents API routes.

Endpoints for listing available agents and their configuration.
Provides transparency about which models each agent uses.
"""

import os
from pathlib import Path

import structlog
import yaml
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from druppie.api.deps import get_current_user

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

            # Determine category based on agent ID
            agent_id = data.get("id", "")
            category = "system"
            if agent_id in ["router", "planner"]:
                category = "system"
            elif agent_id in ["reviewer", "tester", "test_builder", "test_executor", "builder_planner"]:
                category = "quality"
            elif agent_id in ["deployer"]:
                category = "deployment"
            else:
                category = "execution"

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
