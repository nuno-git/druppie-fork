"""ATK Copilot Agents API routes.

Read-only endpoints for viewing ATK agents deployed via Copilot Studio.
Agent deployments happen through chat sessions via the atk_deployer agent.

Architecture:
    Route (this file)
      |
      +-->  AtkService --> AtkAgentRepository --> Database
"""

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
import structlog

from druppie.api.deps import get_current_user, get_atk_service
from druppie.services import AtkService
from druppie.domain.atk_agent import AtkAgentSummary, AtkAgentDetail

logger = structlog.get_logger()

router = APIRouter()


# =============================================================================
# RESPONSE MODELS
# =============================================================================


class AtkAgentListResponse(BaseModel):
    """Paginated ATK agent list response."""

    items: list[AtkAgentSummary]
    total: int
    page: int
    limit: int


# =============================================================================
# ROUTES
# =============================================================================


@router.get("/atk-agents", response_model=AtkAgentListResponse)
async def list_atk_agents(
    page: int = 1,
    limit: int = 20,
    service: AtkService = Depends(get_atk_service),
    user: dict = Depends(get_current_user),
) -> AtkAgentListResponse:
    """List all ATK Copilot agents.

    All authenticated users can view the list.

    Args:
        page: Page number (1-indexed)
        limit: Items per page

    Returns:
        Paginated list of ATK agents
    """
    items, total = service.list_agents(page=page, limit=limit)

    return AtkAgentListResponse(
        items=items,
        total=total,
        page=page,
        limit=limit,
    )


@router.get("/atk-agents/{agent_id}", response_model=AtkAgentDetail)
async def get_atk_agent(
    agent_id: UUID,
    service: AtkService = Depends(get_atk_service),
    user: dict = Depends(get_current_user),
) -> AtkAgentDetail:
    """Get ATK agent detail with shares and deployment history.

    All authenticated users can view agent details.

    Args:
        agent_id: ATK agent UUID

    Returns:
        Full agent detail with shares and deployment log

    Raises:
        NotFoundError: Agent doesn't exist
    """
    return service.get_detail(agent_id)
