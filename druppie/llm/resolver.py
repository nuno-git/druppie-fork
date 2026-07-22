"""Model resolver — determines which provider/model to use for an agent.

Resolution chain (first match wins):
1. Override: LLM_FORCE_PROVIDER env var → use for ALL agents
2. DB override: per-agent override set by admin via the UI
3. Profile: First entry in agent's llm_profile whose API key is set
4. Global default: LLM_PROVIDER env var as last-resort

Profiles are loaded from agents/definitions/llm_profiles.yaml.
"""

import os
from dataclasses import dataclass
from pathlib import Path

import structlog
import yaml

from druppie.domain.agent_definition import AgentDefinition

from .litellm_provider import PROVIDER_CONFIGS, has_api_key

logger = structlog.get_logger()


@dataclass
class ResolvedModel:
    """Result of model resolution for an agent."""

    provider: str
    model: str | None
    source: str  # "override" | "db_override" | "profile" | "global_default"
    fallback_provider: str | None = None
    fallback_model: str | None = None
    override_unavailable: bool = False
    thinking: str | None = None
    reasoning_effort: str | None = None



# Module-level profile cache
_profiles_cache: dict[str, list[dict[str, str]]] | None = None


def _get_db_override(agent_id: str) -> tuple[str, str, str | None, str | None] | None:
    """Fetch a single agent's DB override directly from the database.

    Returns None if no override exists for this agent.
    """
    from druppie.db.database import SessionLocal
    from druppie.db.models.model_override import ModelOverride

    db = SessionLocal()
    try:
        override = (
            db.query(ModelOverride)
            .filter(ModelOverride.target_type == "agent", ModelOverride.target_id == agent_id, ModelOverride.enabled.is_(True))
            .first()
        )
        if override:
            return (override.provider, override.model, override.fallback_provider, override.fallback_model)
        return None
    finally:
        db.close()


def get_db_overrides() -> dict[str, tuple[str, str, str | None, str | None]]:
    """Return all current DB overrides (for status/debug endpoint)."""
    from druppie.db.database import SessionLocal
    from druppie.db.models.model_override import ModelOverride

    db = SessionLocal()
    try:
        overrides = (
            db.query(ModelOverride)
            .filter(ModelOverride.target_type == "agent", ModelOverride.enabled.is_(True))
            .all()
        )
        return {
            o.target_id: (o.provider, o.model, o.fallback_provider, o.fallback_model)
            for o in overrides
        }
    finally:
        db.close()


def _load_profiles() -> dict[str, list[dict[str, str]]]:
    """Load LLM profiles from YAML (cached at module level)."""
    global _profiles_cache
    if _profiles_cache is not None:
        return _profiles_cache

    profiles_path = Path(__file__).parent.parent / "agents" / "definitions" / "llm_profiles.yaml"
    if not profiles_path.exists():
        logger.warning("llm_profiles_not_found", path=str(profiles_path))
        _profiles_cache = {}
        return _profiles_cache

    with open(profiles_path) as f:
        data = yaml.safe_load(f)

    _profiles_cache = data.get("profiles", {})
    logger.info("llm_profiles_loaded", profiles=list(_profiles_cache.keys()))
    return _profiles_cache


def get_profiles() -> dict[str, list[dict[str, str]]]:
    """Get all loaded profiles (for status endpoint)."""
    return _load_profiles()


def resolve_model(agent_def: AgentDefinition) -> ResolvedModel:
    """Resolve which provider/model an agent should use.

    Resolution order:
    1. Override   — LLM_FORCE_PROVIDER env var (ignores profile entirely)
    2. DB override — per-agent admin override from model_overrides table
    3. Profile    — first entry with a valid API key becomes primary;
                    second entry (if any) becomes fallback
    4. Global     — LLM_PROVIDER env var as last-resort
    """
    resolved = _resolve(agent_def)

    logger.info(
        "model_resolved",
        agent_id=agent_def.id,
        provider=resolved.provider,
        model=resolved.model,
        source=resolved.source,
        profile=agent_def.llm_profile,
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

    # --- 2. DB override (admin UI) -----------------------------------------
    db_override = _get_db_override(agent_def.id)
    if db_override:
        provider, model, admin_fb_provider, admin_fb_model = db_override
        key_available = has_api_key(provider)

        if not key_available:
            logger.warning(
                "db_override_api_key_missing",
                agent_id=agent_def.id,
                provider=provider,
            )

        if admin_fb_provider and has_api_key(admin_fb_provider):
            fb_provider, fb_model = admin_fb_provider, admin_fb_model
        else:
            if admin_fb_provider:
                logger.warning(
                    "admin_fallback_api_key_missing",
                    agent_id=agent_def.id,
                    fallback_provider=admin_fb_provider,
                )
            fb_provider, fb_model = _find_alternative_provider(agent_def, exclude_provider=provider)

        return ResolvedModel(
            provider=provider,
            model=model,
            source="db_override",
            override_unavailable=not key_available,
            fallback_provider=fb_provider,
            fallback_model=fb_model,
        )

    # --- 3. Profile (was step 2) --------------------------------------------
    profiles = _load_profiles()
    profile_name = agent_def.llm_profile
    chain = profiles.get(profile_name)

    if chain:
        # Build list of available entries (API key is set)
        available = [e for e in chain if has_api_key(e["provider"])]

        # Append global LLM_PROVIDER as last-resort if not already in chain
        global_provider = os.getenv("LLM_PROVIDER", "zai").lower()
        already_listed = any(e["provider"] == global_provider for e in chain)
        if not already_listed and has_api_key(global_provider):
            default_model = PROVIDER_CONFIGS.get(global_provider, {}).get("default_model")
            available.append({"provider": global_provider, "model": default_model})

        if available:
            primary = available[0]
            fb_provider = None
            fb_model = None
            if len(available) > 1:
                fb_provider = available[1]["provider"]
                fb_model = available[1].get("model")

            return ResolvedModel(
                provider=primary["provider"],
                model=primary.get("model"),
                source="profile",
                fallback_provider=fb_provider,
                fallback_model=fb_model,
                thinking=primary.get("thinking"),
                reasoning_effort=primary.get("reasoning_effort"),
            )
    else:
        logger.warning("llm_profile_not_found", profile=profile_name, agent=agent_def.id)

    # --- 4. Global default --------------------------------------------------
    return ResolvedModel(
        provider=os.getenv("LLM_PROVIDER", "zai").lower(),
        model=None,
        source="global_default",
    )


def _find_alternative_provider(
    agent_def: AgentDefinition,
    exclude_provider: str,
) -> tuple[str | None, str | None]:
    """Find the first available provider/model from the profile chain that
    differs from *exclude_provider*.  Returns (None, None) if none found."""
    profiles = _load_profiles()
    chain = profiles.get(agent_def.llm_profile) or []

    available = [e for e in chain if has_api_key(e["provider"])]

    global_provider = os.getenv("LLM_PROVIDER", "zai").lower()
    if not any(e["provider"] == global_provider for e in chain) and has_api_key(global_provider):
        default_model = PROVIDER_CONFIGS.get(global_provider, {}).get("default_model")
        available.append({"provider": global_provider, "model": default_model})

    for entry in available:
        if entry["provider"] != exclude_provider:
            return entry["provider"], entry.get("model")

    return None, None
