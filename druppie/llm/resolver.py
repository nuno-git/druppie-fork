"""Model resolver — determines which provider/model to use for an agent.

Resolution chain (first match wins):
1. Override: LLM_FORCE_PROVIDER env var → use for ALL agents
2. Primary: Agent YAML provider/model if the provider's API key is set
3. Fallback: Agent YAML fallback_provider/fallback_model if primary key is missing
4. Global default: LLM_PROVIDER env var (existing behavior)
"""

import os
from dataclasses import dataclass

import structlog

from druppie.domain.agent_definition import AgentDefinition

from .litellm_provider import PROVIDER_CONFIGS

logger = structlog.get_logger()


@dataclass
class ResolvedModel:
    """Result of model resolution for an agent."""

    provider: str
    model: str | None
    source: str  # "override" | "primary" | "fallback" | "global_default"
    fallback_provider: str | None = None
    fallback_model: str | None = None


def _has_api_key(provider: str) -> bool:
    """Check whether the API key env var for a provider is set."""
    config = PROVIDER_CONFIGS.get(provider)
    if not config:
        return False
    return bool(os.getenv(config["api_key_env"]))


def resolve_model(agent_def: AgentDefinition) -> ResolvedModel:
    """Resolve which provider/model an agent should use.

    Resolution order:
    1. Override  — LLM_FORCE_PROVIDER env var (ignores YAML entirely)
    2. Primary   — agent YAML provider/model if its API key is present
    3. Fallback  — agent YAML fallback_provider/fallback_model if primary key missing
    4. Global    — LLM_PROVIDER env var
    """
    resolved = _resolve(agent_def)

    logger.info(
        "model_resolved",
        agent_id=agent_def.id,
        provider=resolved.provider,
        model=resolved.model,
        source=resolved.source,
        fallback_provider=resolved.fallback_provider,
        fallback_model=resolved.fallback_model,
    )

    return resolved


def _resolve(agent_def: AgentDefinition) -> ResolvedModel:
    """Internal resolution logic."""

    # --- 1. Override --------------------------------------------------------
    force_provider = os.getenv("LLM_FORCE_PROVIDER")
    if force_provider:
        return ResolvedModel(
            provider=force_provider,
            model=os.getenv("LLM_FORCE_MODEL"),
            source="override",
        )

    # --- 2. Primary (agent YAML) -------------------------------------------
    if agent_def.provider and _has_api_key(agent_def.provider):
        fb_provider: str | None = None
        fb_model: str | None = None

        if agent_def.fallback_provider and _has_api_key(agent_def.fallback_provider):
            fb_provider = agent_def.fallback_provider
            fb_model = agent_def.fallback_model
        else:
            # Fall back to global default if it differs from primary
            global_provider = os.getenv("LLM_PROVIDER", "zai").lower()
            if global_provider != agent_def.provider and _has_api_key(global_provider):
                fb_provider = global_provider

        return ResolvedModel(
            provider=agent_def.provider,
            model=agent_def.model,
            source="primary",
            fallback_provider=fb_provider,
            fallback_model=fb_model,
        )

    # --- 3. Fallback (agent YAML) ------------------------------------------
    if agent_def.fallback_provider and _has_api_key(agent_def.fallback_provider):
        return ResolvedModel(
            provider=agent_def.fallback_provider,
            model=agent_def.fallback_model,
            source="fallback",
        )

    # --- 4. Global default --------------------------------------------------
    return ResolvedModel(
        provider=os.getenv("LLM_PROVIDER", "zai").lower(),
        model=None,
        source="global_default",
    )
