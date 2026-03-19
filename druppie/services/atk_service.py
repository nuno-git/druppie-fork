"""ATK Agent service for business logic."""

from uuid import UUID

import structlog

from ..repositories.atk_agent_repository import AtkAgentRepository
from ..domain.atk_agent import AtkAgentDetail, AtkAgentSummary
from ..api.errors import NotFoundError

logger = structlog.get_logger()


class AtkService:
    """Business logic for ATK Copilot agents."""

    def __init__(self, atk_repo: AtkAgentRepository):
        self.atk_repo = atk_repo

    def list_agents(
        self,
        page: int = 1,
        limit: int = 20,
    ) -> tuple[list[AtkAgentSummary], int]:
        """List all ATK agents."""
        offset = (page - 1) * limit
        return self.atk_repo.list_all(limit, offset)

    def get_detail(self, agent_id: UUID) -> AtkAgentDetail:
        """Get ATK agent detail."""
        detail = self.atk_repo.get_detail(agent_id)
        if not detail:
            raise NotFoundError("atk_agent", str(agent_id))
        return detail

    def record_scaffold(
        self,
        name: str,
        user_id: UUID,
        description: str | None = None,
        project_id: UUID | None = None,
        environment: str = "dev",
    ) -> AtkAgentSummary:
        """Record a scaffolded agent."""
        agent = self.atk_repo.create(
            name=name,
            created_by=user_id,
            description=description,
            project_id=project_id,
            environment=environment,
        )
        self.atk_repo.add_log(
            atk_agent_id=agent.id,
            action="scaffold",
            status="success",
            performed_by=user_id,
        )
        self.atk_repo.commit()
        logger.info("atk_agent_scaffolded", name=name, user_id=str(user_id))
        return self.atk_repo._to_summary(agent)

    def record_provision(
        self,
        agent_id: UUID,
        user_id: UUID,
        environment: str,
        m365_app_id: str | None = None,
    ) -> None:
        """Record a provision action."""
        agent = self.atk_repo.get_by_id(agent_id)
        if not agent:
            raise NotFoundError("atk_agent", str(agent_id))

        self.atk_repo.update_status(agent_id, "provisioned", m365_app_id)
        self.atk_repo.add_log(
            atk_agent_id=agent_id,
            action="provision",
            status="success",
            performed_by=user_id,
            environment=environment,
        )
        self.atk_repo.commit()
        logger.info("atk_agent_provisioned", agent_id=str(agent_id), environment=environment)

    def record_share(
        self,
        agent_id: UUID,
        user_id: UUID,
        email: str,
        scope: str = "users",
    ) -> None:
        """Record a share action."""
        agent = self.atk_repo.get_by_id(agent_id)
        if not agent:
            raise NotFoundError("atk_agent", str(agent_id))

        self.atk_repo.add_share(agent_id, email, scope)
        self.atk_repo.update_status(agent_id, "shared")
        self.atk_repo.add_log(
            atk_agent_id=agent_id,
            action="share",
            status="success",
            performed_by=user_id,
            details=f"Shared with {email} (scope: {scope})",
        )
        self.atk_repo.commit()
        logger.info("atk_agent_shared", agent_id=str(agent_id), email=email)

    def record_uninstall(
        self,
        agent_id: UUID,
        user_id: UUID,
    ) -> None:
        """Record an uninstall action."""
        agent = self.atk_repo.get_by_id(agent_id)
        if not agent:
            raise NotFoundError("atk_agent", str(agent_id))

        self.atk_repo.update_status(agent_id, "uninstalled")
        self.atk_repo.add_log(
            atk_agent_id=agent_id,
            action="uninstall",
            status="success",
            performed_by=user_id,
        )
        self.atk_repo.commit()
        logger.info("atk_agent_uninstalled", agent_id=str(agent_id))
