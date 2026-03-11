"""Resolve per-agent sandbox models from sandbox_models.yaml.

Uses a profile-based approach: each agent/subagent name becomes a virtual
"profile" that the LLM proxy resolves to a real provider chain at request time.

OpenCode sees model names like "sandbox/druppie-builder" and routes all requests
through a single "sandbox" provider pointing at our proxy. The proxy extracts
the profile name from the request body, looks up the chain, and tries each
real provider in order with failover on 5xx/429.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path

import structlog
import yaml

logger = structlog.get_logger()

_CONFIG_PATH = Path(__file__).parent.parent / "opencode" / "config" / "sandbox_models.yaml"
_cached_config: dict | None = None


def _load_config() -> dict:
    """Load and cache sandbox_models.yaml. The file is baked into the
    Docker image and never changes at runtime."""
    global _cached_config
    if _cached_config is None:
        _cached_config = yaml.safe_load(_CONFIG_PATH.read_text())
    return _cached_config

# Provider name -> env var mapping. Shared source of truth for which
# API keys enable which providers. Imported by credentials.py too.
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

    primary_model: str  # e.g. "sandbox/druppie-builder"
    agents: dict[str, str] = field(default_factory=dict)  # name → "sandbox/name"
    all_providers: set[str] = field(default_factory=set)  # real providers for credentials


def resolve_sandbox_models(requested_agent: str) -> SandboxModelConfig:
    """Resolve models for the requested agent using profile-based naming.

    Each agent/subagent name becomes a profile. The primary model is
    "sandbox/{requested_agent}" and all agents/subagents get their own
    profile name. The LLM proxy resolves profiles to real provider chains.

    Args:
        requested_agent: The primary agent name (e.g. "druppie-builder").

    Returns:
        SandboxModelConfig with profile-based model names and the set of
        all real providers referenced (for credential building).
    """
    config = _load_config()

    agents_section = config.get("agents", {})
    subagents_section = config.get("subagents", {})

    # Verify requested agent exists
    if requested_agent not in agents_section and requested_agent not in subagents_section:
        all_available = list(agents_section.keys()) + list(subagents_section.keys())
        logger.error(
            "model_resolver.agent_not_configured",
            agent=requested_agent,
            available=all_available,
        )
        raise ValueError(
            f"Agent '{requested_agent}' has no model chain in sandbox_models.yaml. "
            f"Available agents: {all_available}"
        )

    primary_model = f"sandbox/{requested_agent}"

    # Collect all real providers and build agent→profile mapping
    all_providers: set[str] = set()
    agents: dict[str, str] = {}

    # If force override is set, ensure that provider's credentials are included
    force_provider = os.getenv("LLM_FORCE_PROVIDER")
    if force_provider:
        all_providers.add(force_provider)

    for section in (agents_section, subagents_section):
        for name, chain in section.items():
            agents[name] = f"sandbox/{name}"
            for entry in chain:
                all_providers.add(entry["provider"])

    return SandboxModelConfig(
        primary_model=primary_model,
        agents=agents,
        all_providers=all_providers,
    )


def get_raw_model_chains() -> dict[str, list[dict[str, str]]]:
    """Return all model chains keyed by profile name (agent/subagent name).

    Used by the LLM proxy for failover. When a profile's primary provider
    fails, the proxy tries the next entry in the chain.

    If LLM_FORCE_PROVIDER and LLM_FORCE_MODEL are set, every profile gets
    a single-entry chain with that provider/model (override → profile).
    """
    config = _load_config()

    # Check for override — same env vars as the backend agent system
    force_provider = os.getenv("LLM_FORCE_PROVIDER")
    force_model = os.getenv("LLM_FORCE_MODEL")

    chains: dict[str, list[dict[str, str]]] = {}
    for section in ("agents", "subagents"):
        for name, chain in config.get(section, {}).items():
            if force_provider and force_model:
                chains[name] = [{"provider": force_provider, "model": force_model}]
            elif chain:
                chains[name] = [
                    {"provider": e["provider"], "model": e["model"]}
                    for e in chain
                ]

    if force_provider and force_model:
        logger.info(
            "model_resolver.force_override",
            provider=force_provider,
            model=force_model,
            profiles=list(chains.keys()),
        )

    return chains


def get_agent_chain(agent_name: str) -> list[dict[str, str]]:
    """Return the raw model chain for an agent from sandbox_models.yaml."""
    config = _load_config()
    chain = config.get("agents", {}).get(agent_name)
    if not chain:
        chain = config.get("subagents", {}).get(agent_name, [])
    return chain or []
