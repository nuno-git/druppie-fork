"""Agent definition loader - loads YAML agent definitions from disk."""

import os

import structlog
import yaml

from druppie.domain.agent_definition import AgentDefinition

logger = structlog.get_logger()


class AgentDefinitionLoader:
    """Loads and caches agent definitions from YAML files.

    Cache auto-invalidates when the file on disk changes (mtime check).
    All methods are class-level — no instance state needed.
    """

    _definitions_path: str = None
    _cache: dict[str, AgentDefinition] = {}
    _cache_mtime: dict[str, float] = {}
    _system_prompt_cache: dict[str, str] = {}
    _system_prompt_mtime: dict[str, float] = {}

    @classmethod
    def set_definitions_path(cls, path: str) -> None:
        """Set the path to agent definitions directory."""
        cls._definitions_path = path
        cls._cache.clear()
        cls._cache_mtime.clear()
        cls._system_prompt_cache.clear()
        cls._system_prompt_mtime.clear()

    @classmethod
    def _get_definitions_path(cls) -> str:
        """Get the path to agent definitions directory."""
        if cls._definitions_path:
            return cls._definitions_path
        # Default: druppie/agents/definitions/
        return os.path.join(os.path.dirname(__file__), "definitions")

    @classmethod
    def load(cls, agent_id: str) -> AgentDefinition:
        """Load agent definition from YAML, with mtime-based cache.

        Args:
            agent_id: Agent identifier (e.g., "router", "builder")

        Returns:
            Parsed AgentDefinition

        Raises:
            AgentNotFoundError: If YAML file doesn't exist
        """
        from druppie.agents.runtime import AgentNotFoundError

        path = os.path.join(cls._get_definitions_path(), f"{agent_id}.yaml")

        if not os.path.exists(path):
            raise AgentNotFoundError(f"Agent '{agent_id}' not found at {path}")

        mtime = os.path.getmtime(path)

        if agent_id in cls._cache and cls._cache_mtime.get(agent_id) == mtime:
            return cls._cache[agent_id]

        with open(path, "r") as f:
            data = yaml.safe_load(f)

        definition = AgentDefinition(**data)
        is_reload = agent_id in cls._cache_mtime
        cls._cache[agent_id] = definition
        cls._cache_mtime[agent_id] = mtime

        if is_reload:
            logger.debug("agent_definition_reloaded", agent_id=agent_id)
        else:
            logger.debug("agent_definition_loaded", agent_id=agent_id)
        return definition

    @classmethod
    def load_system_prompt(cls, prompt_id: str) -> str:
        """Load a system prompt from system_prompts/{prompt_id}.yaml, with mtime-based cache.

        Raises:
            AgentNotFoundError: If the system prompt file doesn't exist.
        """
        from druppie.agents.runtime import AgentError

        path = os.path.join(
            cls._get_definitions_path(), "system_prompts", f"{prompt_id}.yaml"
        )

        if not os.path.exists(path):
            raise AgentError(
                f"System prompt '{prompt_id}' not found at {path}"
            )

        mtime = os.path.getmtime(path)

        if prompt_id in cls._system_prompt_cache and cls._system_prompt_mtime.get(prompt_id) == mtime:
            return cls._system_prompt_cache[prompt_id]

        with open(path, "r") as f:
            data = yaml.safe_load(f)

        prompt = data.get("prompt", "").strip()
        cls._system_prompt_cache[prompt_id] = prompt
        cls._system_prompt_mtime[prompt_id] = mtime

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
