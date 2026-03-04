"""Resolve per-agent sandbox models from sandbox_models.yaml.

Reads the YAML config and picks the first provider in each chain
that has a valid API key set in the environment. No runtime fallback —
resolution happens once at sandbox creation time.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path

import structlog
import yaml

logger = structlog.get_logger()

_CONFIG_PATH = Path(__file__).parent.parent / "sandbox-config" / "sandbox_models.yaml"

# Provider name -> env var mapping. Shared source of truth for which
# API keys enable which providers. Imported by builtin_tools.py too.
PROVIDER_API_KEYS = {
    "zai": "ZAI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "deepinfra": "DEEPINFRA_API_KEY",
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}


@dataclass
class SandboxModelConfig:
    """Resolved model configuration for a sandbox session."""

    primary_model: str
    agents: dict[str, str] = field(default_factory=dict)
    all_providers: set[str] = field(default_factory=set)


def _resolve_chain(chain: list[dict]) -> str | None:
    """Return the first model in the chain whose provider has a valid API key."""
    for entry in chain:
        provider = entry["provider"]
        env_var = PROVIDER_API_KEYS.get(provider)
        if env_var and os.getenv(env_var):
            return entry["model"]
    return None


def _provider_from_model(model: str) -> str:
    """Extract base provider name from a model string like 'deepinfra/Qwen/QwQ-32B'."""
    return model.split("/")[0] if "/" in model else model


def resolve_sandbox_models(requested_agent: str) -> SandboxModelConfig:
    """Resolve models for the requested agent and all subagents.

    Args:
        requested_agent: The primary agent name (e.g. "druppie-builder").

    Returns:
        SandboxModelConfig with resolved primary model, per-agent model map,
        and the set of all providers referenced.
    """
    config = yaml.safe_load(_CONFIG_PATH.read_text())

    default_chain = config.get("default", [])
    agents_section = config.get("agents", {})
    subagents_section = config.get("subagents", {})

    # Resolve primary agent model
    agent_chain = agents_section.get(requested_agent)
    # null means "use default"
    if agent_chain is None:
        agent_chain = default_chain
    primary_model = _resolve_chain(agent_chain)
    if not primary_model:
        primary_model = default_chain[0]["model"] if default_chain else "zai-coding-plan/glm-4.7"
        logger.warning(
            "model_resolver.fallback",
            agent=requested_agent,
            resolved_model=primary_model,
            reason="no_api_keys_available",
        )

    all_providers: set[str] = {_provider_from_model(primary_model)}
    resolved: dict[str, str] = {}

    # Resolve all named agents
    for name, chain in agents_section.items():
        if chain is None:
            chain = default_chain
        model = _resolve_chain(chain)
        if model:
            resolved[name] = model
            all_providers.add(_provider_from_model(model))

    # Resolve all subagents
    for name, chain in subagents_section.items():
        if chain is None:
            chain = default_chain
        model = _resolve_chain(chain)
        if model:
            resolved[name] = model
            all_providers.add(_provider_from_model(model))
        else:
            logger.warning(
                "model_resolver.subagent_unresolved",
                subagent=name,
                fallback="primary_model",
            )

    return SandboxModelConfig(
        primary_model=primary_model,
        agents=resolved,
        all_providers=all_providers,
    )
