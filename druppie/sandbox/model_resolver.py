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
    """Extract provider prefix from a model string like 'deepinfra/Qwen/QwQ-32B'."""
    return model.split("/")[0] if "/" in model else model


def resolve_sandbox_models(requested_agent: str) -> SandboxModelConfig:
    """Resolve models for the requested agent and all subagents.

    Every agent and subagent must have an explicit chain in sandbox_models.yaml.

    Args:
        requested_agent: The primary agent name (e.g. "druppie-builder").

    Returns:
        SandboxModelConfig with resolved primary model, per-agent model map,
        and the set of all providers referenced.
    """
    config = yaml.safe_load(_CONFIG_PATH.read_text())

    agents_section = config.get("agents", {})
    subagents_section = config.get("subagents", {})

    # Resolve primary agent model
    agent_chain = agents_section.get(requested_agent)
    if not agent_chain:
        logger.error(
            "model_resolver.agent_not_configured",
            agent=requested_agent,
            available=list(agents_section.keys()),
        )
        raise ValueError(
            f"Agent '{requested_agent}' has no model chain in sandbox_models.yaml. "
            f"Available agents: {list(agents_section.keys())}"
        )

    primary_model = _resolve_chain(agent_chain)
    if not primary_model:
        # Use first entry in the chain as last-resort (no API key available)
        primary_model = agent_chain[0]["model"]
        logger.warning(
            "model_resolver.no_api_keys",
            agent=requested_agent,
            resolved_model=primary_model,
            reason="no_api_keys_available_for_any_provider_in_chain",
        )

    all_providers: set[str] = {_provider_from_model(primary_model)}
    resolved: dict[str, str] = {}

    # Resolve all named agents
    for name, chain in agents_section.items():
        model = _resolve_chain(chain)
        if model:
            resolved[name] = model
            all_providers.add(_provider_from_model(model))
        else:
            logger.warning("model_resolver.agent_unresolved", agent=name)

    # Resolve all subagents
    for name, chain in subagents_section.items():
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


def get_raw_model_chains() -> dict[str, list[dict[str, str]]]:
    """Return all model chains from sandbox_models.yaml, keyed by model string.

    Used by the proxy for failover — when a model's provider fails, the proxy
    tries the next model in the chain.
    """
    config = yaml.safe_load(_CONFIG_PATH.read_text())
    chains: dict[str, list[dict[str, str]]] = {}
    for section in ("agents", "subagents"):
        for _name, chain in config.get(section, {}).items():
            if chain:
                for entry in chain:
                    model_str = entry["model"]
                    if model_str not in chains:
                        chains[model_str] = [
                            {"provider": e["provider"], "model": e["model"]}
                            for e in chain
                        ]
    return chains


def get_agent_chain(agent_name: str) -> list[dict[str, str]]:
    """Return the raw model chain for an agent from sandbox_models.yaml."""
    config = yaml.safe_load(_CONFIG_PATH.read_text())
    chain = config.get("agents", {}).get(agent_name)
    if not chain:
        chain = config.get("subagents", {}).get(agent_name, [])
    return chain or []
