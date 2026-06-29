"""Service for managing runtime LLM model overrides."""

import os
import time
from pathlib import Path
from uuid import UUID

import structlog
import yaml

from druppie.agents.definition_loader import AgentDefinitionLoader
from druppie.core.translation import get_translation_service
from druppie.domain.model_override import (
    AgentModelInfo,
    ModelManagementView,
    ModelOverrideSummary,
    ProviderStatus,
    TranslationModelInfo,
)
from druppie.llm.base import clean_llm_error
from druppie.llm.litellm_provider import PROVIDER_CONFIGS, has_api_key
from druppie.llm.resolver import resolve_model, set_db_overrides
from druppie.repositories.model_override_repository import ModelOverrideRepository

logger = structlog.get_logger()


def _to_summary(row) -> ModelOverrideSummary:
    return ModelOverrideSummary(
        id=row.id,
        target_type=row.target_type,
        target_id=row.target_id,
        provider=row.provider,
        model=row.model,
        fallback_provider=row.fallback_provider,
        fallback_model=row.fallback_model,
        enabled=row.enabled,
        updated_at=row.updated_at,
    )


_clean_llm_error = clean_llm_error


def _validate_fallback(provider: str, model: str, fallback_provider: str | None, fallback_model: str | None):
    if fallback_model and not fallback_provider:
        raise ValueError("fallback_model requires fallback_provider")
    if fallback_provider:
        if fallback_provider not in PROVIDER_CONFIGS:
            raise ValueError(f"Unknown fallback provider: {fallback_provider}")
        if fallback_provider == provider:
            raise ValueError(
                f"Fallback provider must differ from primary ('{provider}') "
                f"— same provider fails the same way when it's down"
            )


class ModelManagementService:

    def __init__(self, override_repo: ModelOverrideRepository):
        self.override_repo = override_repo

    def get_management_view(self) -> ModelManagementView:
        overrides = self.override_repo.get_all()
        override_map = {
            o.target_id: _to_summary(o)
            for o in overrides
            if o.target_type == "agent" and o.enabled
        }

        # Refresh resolver cache while we have DB data
        self._refresh_resolver_cache(overrides)

        # Build agent list — read category from raw YAML since AgentDefinition
        # does not include it as a field.
        defs_dir = Path(__file__).parent.parent / "agents" / "definitions"
        agents: list[AgentModelInfo] = []
        for agent_id in sorted(AgentDefinitionLoader.list_agents()):
            try:
                agent_def = AgentDefinitionLoader.load(agent_id)
            except Exception:
                logger.warning("agent_load_failed", agent_id=agent_id)
                continue

            category = "execution"
            yaml_path = defs_dir / f"{agent_id}.yaml"
            if yaml_path.exists():
                try:
                    with open(yaml_path) as f:
                        raw = yaml.safe_load(f)
                    category = raw.get("category", "execution")
                except Exception:
                    pass

            resolved = resolve_model(agent_def)
            suggested_fallback = None
            if resolved.fallback_provider:
                fb_model = resolved.fallback_model or "default"
                suggested_fallback = f"{resolved.fallback_provider}/{fb_model}"

            override_summary = override_map.get(agent_def.id)
            fallback_is_custom = bool(
                override_summary and override_summary.fallback_provider
            )
            fallback_unavailable = bool(
                fallback_is_custom
                and not has_api_key(override_summary.fallback_provider)
            )

            agents.append(AgentModelInfo(
                agent_id=agent_def.id,
                agent_name=agent_def.name,
                category=category,
                profile=agent_def.llm_profile,
                resolved_provider=resolved.provider,
                resolved_model=resolved.model,
                source=resolved.source,
                override=override_summary,
                override_unavailable=resolved.override_unavailable,
                suggested_fallback=suggested_fallback,
                fallback_is_custom=fallback_is_custom,
                fallback_unavailable=fallback_unavailable,
            ))

        # Build translation info — sync DB state to the singleton first
        translation_override_row = next(
            (o for o in overrides if o.target_type == "translation" and o.enabled),
            None,
        )
        translation_override = _to_summary(translation_override_row) if translation_override_row else None

        ts = get_translation_service()
        if translation_override_row and translation_override_row.enabled:
            ts.configure(
                translation_override_row.provider,
                translation_override_row.model,
                translation_override_row.fallback_provider,
                translation_override_row.fallback_model,
            )
        elif not translation_override_row:
            ts.configure(None, None)

        t_override_unavailable = False
        t_suggested_fallback = None
        try:
            t_provider, t_model, t_source = ts.get_current_config()
        except Exception:
            if translation_override_row and not has_api_key(translation_override_row.provider):
                t_provider = translation_override_row.provider
                t_model = translation_override_row.model
                t_source = "db_override"
                t_override_unavailable = True
                t_suggested_fallback = self._compute_translation_fallback()
            else:
                t_provider, t_model, t_source = "none", "none", "unavailable"

        t_fallback_is_custom = bool(
            translation_override and translation_override.fallback_provider
        )
        t_fallback_unavailable = bool(
            t_fallback_is_custom
            and not has_api_key(translation_override.fallback_provider)
        )

        translation = TranslationModelInfo(
            provider=t_provider,
            model=t_model,
            source=t_source,
            override=translation_override,
            override_unavailable=t_override_unavailable,
            suggested_fallback=t_suggested_fallback,
            fallback_is_custom=t_fallback_is_custom,
            fallback_unavailable=t_fallback_unavailable,
        )

        providers = self.get_provider_statuses()
        override_summaries = [_to_summary(o) for o in overrides]

        return ModelManagementView(
            agents=agents,
            translation=translation,
            providers=providers,
            overrides=override_summaries,
        )

    def set_agent_override(
        self,
        agent_id: str,
        provider: str,
        model: str,
        admin_user_id: UUID | None = None,
        fallback_provider: str | None = None,
        fallback_model: str | None = None,
    ) -> ModelOverrideSummary:
        available = AgentDefinitionLoader.list_agents()
        if agent_id not in available:
            raise ValueError(f"Unknown agent: {agent_id}")

        if provider not in PROVIDER_CONFIGS:
            raise ValueError(f"Unknown provider: {provider}")

        _validate_fallback(provider, model, fallback_provider, fallback_model)

        row = self.override_repo.upsert(
            "agent", agent_id, provider, model, admin_user_id,
            fallback_provider=fallback_provider,
            fallback_model=fallback_model,
        )
        self.override_repo.commit()
        self._refresh_resolver_cache()
        return _to_summary(row)

    def remove_agent_override(self, agent_id: str) -> bool:
        deleted = self.override_repo.delete_by_target("agent", agent_id)
        self.override_repo.commit()
        self._refresh_resolver_cache()
        return deleted

    def set_translation_override(
        self,
        provider: str,
        model: str,
        admin_user_id: UUID | None = None,
        fallback_provider: str | None = None,
        fallback_model: str | None = None,
    ) -> ModelOverrideSummary:
        if provider not in PROVIDER_CONFIGS:
            raise ValueError(f"Unknown provider: {provider}")

        _validate_fallback(provider, model, fallback_provider, fallback_model)

        row = self.override_repo.upsert(
            "translation", "translation", provider, model, admin_user_id,
            fallback_provider=fallback_provider,
            fallback_model=fallback_model,
        )
        self.override_repo.commit()

        ts = get_translation_service()
        ts.configure(provider, model, fallback_provider, fallback_model)

        return _to_summary(row)

    def remove_translation_override(self) -> bool:
        deleted = self.override_repo.delete_by_target("translation", "translation")
        self.override_repo.commit()

        ts = get_translation_service()
        ts.configure(None, None)

        return deleted

    def get_provider_statuses(self) -> list[ProviderStatus]:
        from druppie.llm.resolver import get_profiles

        profiles = get_profiles()

        # Collect all models used per provider across profiles + env overrides
        models_by_provider: dict[str, set[str]] = {name: set() for name in PROVIDER_CONFIGS}
        for chain in profiles.values():
            for entry in chain:
                prov = entry.get("provider")
                model = entry.get("model")
                if prov in models_by_provider and model:
                    models_by_provider[prov].add(model)

        # Add known models, env-configured models, and defaults
        for name, config in PROVIDER_CONFIGS.items():
            for m in config.get("known_models", []):
                models_by_provider[name].add(m)
            default = config.get("default_model", "")
            if default:
                models_by_provider[name].add(default)
            env_model = os.getenv(config.get("model_env", ""), "")
            if env_model:
                models_by_provider[name].add(env_model)

        statuses = []
        for name, config in PROVIDER_CONFIGS.items():
            statuses.append(ProviderStatus(
                provider=name,
                api_key_env=config.get("api_key_env", ""),
                api_key_configured=has_api_key(name),
                default_model=config.get("default_model", ""),
                base_url=os.getenv(
                    config.get("base_url_env", ""), ""
                ) or config.get("default_base_url", ""),
                available_models=sorted(models_by_provider.get(name, set())),
            ))
        return statuses

    async def validate_api_key(self, provider: str, model: str | None = None) -> dict:
        """Test whether a provider's API key is valid by making a minimal LLM call."""
        if provider not in PROVIDER_CONFIGS:
            return {"provider": provider, "model": model, "valid": False, "error": "Unknown provider", "latency_ms": 0}

        if not has_api_key(provider):
            config = PROVIDER_CONFIGS[provider]
            env_var = config.get("api_key_env", "")
            return {
                "provider": provider,
                "model": model,
                "valid": False,
                "error": f"{env_var} is not set",
                "latency_ms": 0,
            }

        from druppie.llm.litellm_provider import ChatLiteLLM

        start = time.monotonic()
        try:
            llm = ChatLiteLLM(provider=provider, model=model, max_tokens=1, timeout=15.0, max_retries=0)
            await llm.achat(
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=1,
            )
            latency = int((time.monotonic() - start) * 1000)
            return {"provider": provider, "model": llm._model, "valid": True, "error": None, "latency_ms": latency}
        except Exception as e:
            latency = int((time.monotonic() - start) * 1000)
            err = str(e)
            if "max_tokens" in err.lower() or "model output limit" in err.lower():
                return {"provider": provider, "model": getattr(llm, '_model', model), "valid": True, "error": None, "latency_ms": latency}
            return {"provider": provider, "model": model, "valid": False, "error": _clean_llm_error(err), "latency_ms": latency}

    def _compute_translation_fallback(self) -> str | None:
        """What provider/model translation would use if the override were removed."""
        env_provider = os.getenv("TRANSLATION_PROVIDER")
        env_model = os.getenv("TRANSLATION_MODEL")
        if env_provider and env_model and has_api_key(env_provider):
            return f"{env_provider}/{env_model}"

        if os.getenv("DEEPINFRA_API_KEY"):
            return "deepinfra/google/gemma-3-27b-it"

        for name, config in PROVIDER_CONFIGS.items():
            if has_api_key(name):
                return f"{name}/{config['default_model']}"

        return None

    def _refresh_resolver_cache(self, overrides=None):
        """Update the resolver's in-memory cache from DB."""
        if overrides is None:
            overrides = self.override_repo.get_agent_overrides()

        override_map = {}
        for o in overrides:
            if o.target_type != "agent" or not o.enabled:
                continue
            if o.provider not in PROVIDER_CONFIGS:
                logger.warning(
                    "db_override_unknown_provider",
                    target_id=o.target_id,
                    provider=o.provider,
                    hint="Provider was removed from PROVIDER_CONFIGS; override is ignored.",
                )
                continue
            override_map[o.target_id] = (o.provider, o.model, o.fallback_provider, o.fallback_model)
        set_db_overrides(override_map)

        logger.info("resolver_cache_refreshed", override_count=len(override_map))
