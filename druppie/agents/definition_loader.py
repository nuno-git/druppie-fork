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
    _system_prompt_cache: dict[str, str] = {}

    @classmethod
    def set_definitions_path(cls, path: str) -> None:
        """Set the path to agent definitions directory."""
        cls._definitions_path = path
        cls._cache.clear()
        cls._system_prompt_cache.clear()

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
    def load_system_prompt(cls, prompt_id: str) -> str:
        """Load a system prompt from system_prompts/{prompt_id}.yaml, with cache.

        Raises:
            AgentNotFoundError: If the system prompt file doesn't exist.
        """
        from druppie.agents.runtime import AgentError

        if prompt_id in cls._system_prompt_cache:
            return cls._system_prompt_cache[prompt_id]

        path = os.path.join(
            cls._get_definitions_path(), "system_prompts", f"{prompt_id}.yaml"
        )

        if not os.path.exists(path):
            raise AgentError(
                f"System prompt '{prompt_id}' not found at {path}"
            )

        with open(path, "r") as f:
            data = yaml.safe_load(f)

        prompt = data.get("prompt", "").strip()
        cls._system_prompt_cache[prompt_id] = prompt

        logger.debug("system_prompt_loaded", prompt_id=prompt_id)
        return prompt

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
