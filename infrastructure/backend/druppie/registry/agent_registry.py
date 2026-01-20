"""Agent Registry.

Loads agent definitions from YAML files and provides them to the Planner.
"""

from pathlib import Path

import structlog
import yaml

from druppie.core.models import AgentDefinition, AgentType

logger = structlog.get_logger()


class AgentRegistry:
    """Registry for agent definitions.

    Loads agent definitions from YAML files in the registry directory.
    Provides lookup methods for agents.
    """

    def __init__(self, registry_path: str | Path | None = None):
        """Initialize the AgentRegistry.

        Args:
            registry_path: Path to the registry directory
        """
        self.registry_path = Path(registry_path) if registry_path else None
        self._agents: dict[str, AgentDefinition] = {}

    def load(self, registry_path: str | Path | None = None) -> None:
        """Load agent definitions from YAML files."""
        path = Path(registry_path) if registry_path else self.registry_path
        if not path:
            logger.warning("No registry path configured")
            return

        agents_path = path / "agents"
        if not agents_path.exists():
            logger.warning("Agents registry directory not found", path=str(agents_path))
            return

        self._agents.clear()

        for file_path in agents_path.glob("*.yaml"):
            try:
                self._load_agent_file(file_path)
            except Exception as e:
                logger.error("Failed to load agent", file=str(file_path), error=str(e))

        logger.info("Agent registry loaded", agents=len(self._agents))

    def _load_agent_file(self, file_path: Path) -> None:
        """Load a single agent definition file."""
        with open(file_path) as f:
            data = yaml.safe_load(f)

        if not data:
            return

        # Handle single agent or list of agents
        agents = data if isinstance(data, list) else [data]

        for agent_data in agents:
            # Map type string to enum
            if "type" in agent_data:
                type_map = {
                    "spec_agent": AgentType.SPEC_AGENT,
                    "execution_agent": AgentType.EXECUTION_AGENT,
                    "support_agent": AgentType.SUPPORT_AGENT,
                }
                agent_data["type"] = type_map.get(
                    agent_data["type"], AgentType.EXECUTION_AGENT
                )

            agent = AgentDefinition(**agent_data)
            self._agents[agent.id] = agent

    def register_agent(self, agent: AgentDefinition) -> None:
        """Programmatically register an agent."""
        self._agents[agent.id] = agent

    def get_agent(self, agent_id: str) -> AgentDefinition | None:
        """Get an agent by ID."""
        return self._agents.get(agent_id)

    def list_agents(self, groups: list[str] | None = None) -> list[AgentDefinition]:
        """List all registered agents, optionally filtered by auth groups."""
        agents = list(self._agents.values())

        if groups is not None:
            agents = [
                a
                for a in agents
                if not a.auth_groups or any(g in a.auth_groups for g in groups)
            ]

        return agents

    def list_agents_by_type(self, agent_type: AgentType) -> list[AgentDefinition]:
        """List agents of a specific type."""
        return [a for a in self._agents.values() if a.type == agent_type]

    def get_agents_with_mcp(self, mcp_id: str) -> list[AgentDefinition]:
        """Get agents that have access to a specific MCP server."""
        return [a for a in self._agents.values() if mcp_id in a.mcps]

    def as_dict(self) -> dict[str, AgentDefinition]:
        """Get all agents as a dictionary."""
        return dict(self._agents)

    def get_agent_descriptions(self) -> str:
        """Get formatted descriptions of all agents for LLM prompts."""
        lines = []
        for agent in self._agents.values():
            lines.append(f"- {agent.id}: {agent.description}")
            if agent.mcps:
                lines.append(f"  MCPs: {', '.join(agent.mcps)}")
        return "\n".join(lines)
