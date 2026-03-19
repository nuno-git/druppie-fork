"""ATK Agent repository for database access."""

from uuid import UUID

from .base import BaseRepository
from ..domain.atk_agent import (
    AtkAgentDetail,
    AtkAgentStatus,
    AtkAgentSummary,
    AtkDeploymentLogEntry,
    AtkShareInfo,
)
from ..db.models.atk_agent import AtkAgent, AtkAgentShare, AtkDeploymentLog


class AtkAgentRepository(BaseRepository):
    """Database access for ATK agents."""

    def create(
        self,
        name: str,
        created_by: UUID,
        description: str | None = None,
        project_id: UUID | None = None,
        environment: str = "dev",
    ) -> AtkAgent:
        """Create a new ATK agent record."""
        agent = AtkAgent(
            name=name,
            description=description,
            created_by=created_by,
            project_id=project_id,
            environment=environment,
            status="scaffolded",
        )
        self.db.add(agent)
        self.db.flush()
        return agent

    def get_by_id(self, agent_id: UUID) -> AtkAgent | None:
        """Get raw ATK agent model."""
        return self.db.query(AtkAgent).filter_by(id=agent_id).first()

    def get_by_name(self, name: str) -> AtkAgent | None:
        """Get ATK agent by name."""
        return self.db.query(AtkAgent).filter_by(name=name).first()

    def list_all(
        self,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[AtkAgentSummary], int]:
        """List all ATK agents."""
        query = self.db.query(AtkAgent)
        total = query.count()
        agents = (
            query.order_by(AtkAgent.created_at.desc())
            .limit(limit)
            .offset(offset)
            .all()
        )
        return [self._to_summary(a) for a in agents], total

    def get_detail(self, agent_id: UUID) -> AtkAgentDetail | None:
        """Get full ATK agent detail with shares and logs."""
        agent = self.get_by_id(agent_id)
        if not agent:
            return None

        shares = (
            self.db.query(AtkAgentShare)
            .filter_by(atk_agent_id=agent_id)
            .order_by(AtkAgentShare.shared_at.desc())
            .all()
        )

        logs = (
            self.db.query(AtkDeploymentLog)
            .filter_by(atk_agent_id=agent_id)
            .order_by(AtkDeploymentLog.performed_at.desc())
            .all()
        )

        return AtkAgentDetail(
            id=agent.id,
            name=agent.name,
            description=agent.description,
            environment=agent.environment,
            status=AtkAgentStatus(agent.status),
            project_id=agent.project_id,
            created_at=agent.created_at,
            m365_app_id=agent.m365_app_id,
            created_by=agent.created_by,
            updated_at=agent.updated_at,
            shares=[
                AtkShareInfo(
                    id=s.id,
                    email=s.email,
                    scope=s.scope,
                    shared_at=s.shared_at,
                )
                for s in shares
            ],
            deployment_logs=[
                AtkDeploymentLogEntry(
                    id=log.id,
                    action=log.action,
                    environment=log.environment,
                    status=log.status,
                    details=log.details,
                    performed_by=log.performed_by,
                    performed_at=log.performed_at,
                )
                for log in logs
            ],
        )

    def update_status(self, agent_id: UUID, status: str, m365_app_id: str | None = None) -> None:
        """Update agent status and optionally the M365 app ID."""
        updates = {"status": status}
        if m365_app_id is not None:
            updates["m365_app_id"] = m365_app_id
        self.db.query(AtkAgent).filter_by(id=agent_id).update(updates)

    def add_share(self, atk_agent_id: UUID, email: str, scope: str = "users") -> AtkAgentShare:
        """Record a share action."""
        share = AtkAgentShare(
            atk_agent_id=atk_agent_id,
            email=email,
            scope=scope,
        )
        self.db.add(share)
        self.db.flush()
        return share

    def add_log(
        self,
        atk_agent_id: UUID,
        action: str,
        status: str,
        performed_by: UUID,
        environment: str | None = None,
        details: str | None = None,
    ) -> AtkDeploymentLog:
        """Add a deployment log entry."""
        log = AtkDeploymentLog(
            atk_agent_id=atk_agent_id,
            action=action,
            environment=environment,
            status=status,
            details=details,
            performed_by=performed_by,
        )
        self.db.add(log)
        self.db.flush()
        return log

    def _to_summary(self, agent: AtkAgent) -> AtkAgentSummary:
        """Convert ATK agent model to summary domain object."""
        return AtkAgentSummary(
            id=agent.id,
            name=agent.name,
            description=agent.description,
            environment=agent.environment,
            status=AtkAgentStatus(agent.status),
            project_id=agent.project_id,
            created_at=agent.created_at,
        )
