"""Agent definition loader - loads YAML agent definitions from disk."""

import os

import structlog
import yaml

from druppie.domain.agent_definition import AgentDefinition

logger = structlog.get_logger()


class AgentDefinitionLoader:
    """Loads and caches agent definitions from YAML files.

    All methods are class-level — no instance state needed.
    """

    _definitions_path: str = None
    _cache: dict[str, AgentDefinition] = {}
    _common_prompt: str | None = None

    @classmethod
    def set_definitions_path(cls, path: str) -> None:
        """Set the path to agent definitions directory."""
        cls._definitions_path = path
        cls._cache.clear()
        cls._common_prompt = None

    @classmethod
    def _get_definitions_path(cls) -> str:
        """Get the path to agent definitions directory."""
        if cls._definitions_path:
            return cls._definitions_path
        # Default: druppie/agents/definitions/
        return os.path.join(os.path.dirname(__file__), "definitions")

    @classmethod
    def load(cls, agent_id: str) -> AgentDefinition:
        """Load agent definition from YAML, with cache.

        Args:
            agent_id: Agent identifier (e.g., "router", "developer")

        Returns:
            Parsed AgentDefinition

        Raises:
            AgentNotFoundError: If YAML file doesn't exist
        """
        from druppie.agents.runtime import AgentNotFoundError

        if agent_id in cls._cache:
            return cls._cache[agent_id]

        path = os.path.join(cls._get_definitions_path(), f"{agent_id}.yaml")

        if not os.path.exists(path):
            raise AgentNotFoundError(f"Agent '{agent_id}' not found at {path}")

        with open(path, "r") as f:
            data = yaml.safe_load(f)

        definition = AgentDefinition(**data)
        cls._cache[agent_id] = definition

        logger.debug("agent_definition_loaded", agent_id=agent_id)
        return definition

    @classmethod
    def load_common_prompt(cls) -> str:
        """Load shared prompt instructions from _common.md, with cache."""
        if cls._common_prompt is not None:
            return cls._common_prompt

        path = os.path.join(cls._get_definitions_path(), "_common.md")
        if os.path.exists(path):
            with open(path, "r") as f:
                cls._common_prompt = f.read().strip()
        else:
            cls._common_prompt = ""

        return cls._common_prompt

    @classmethod
    def list_agents(cls) -> list[str]:
        """List available agent IDs from disk."""
        path = cls._get_definitions_path()
        if not os.path.exists(path):
            return []
        return [
            f.replace(".yaml", "").replace(".yml", "")
            for f in os.listdir(path)
            if f.endswith((".yaml", ".yml"))
        ]
