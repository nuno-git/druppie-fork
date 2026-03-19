"""LLM Service for managing LLM instances.

Supports per-agent LLM profiles with ordered provider chains.
Profiles are defined in agents/definitions/llm_profiles.yaml.

Environment variables:
    LLM_PROVIDER: Global default provider (zai, deepinfra, azure_foundry, ollama)
    LLM_FORCE_PROVIDER: Force all agents to use this provider (overrides profiles)
    LLM_FORCE_MODEL: Force all agents to use this model (requires LLM_FORCE_PROVIDER)
"""

import os
from typing import TYPE_CHECKING, Any

import structlog

from .base import BaseLLM
from .fallback import FallbackLLM
from .litellm_provider import ChatLiteLLM, LITELLM_AVAILABLE, PROVIDER_CONFIGS
from .resolver import get_profiles, resolve_model

if TYPE_CHECKING:
    from druppie.domain.agent_definition import AgentDefinition

logger = structlog.get_logger()


class LLMConfigurationError(Exception):
    """Raised when LLM is not properly configured."""

    pass


class LLMService:
    """Service for managing LLM instances.

    All providers go through LiteLLM for standardized tool calling.
    """

    # Supported providers and their required API key env vars
    # None means the API key is optional (e.g. Ollama)
    PROVIDERS = {
        "zai": "ZAI_API_KEY",
        "deepinfra": "DEEPINFRA_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY",
        "azure_foundry": "FOUNDRY_API_KEY",
        "ollama": None,
    }

    def __init__(self):
        """Initialize LLM service."""
        self._llm: BaseLLM | None = None
        self._provider: str | None = None

    def get_provider(self) -> str:
        """Get the configured LLM provider name."""
        if self._provider is not None:
            return self._provider

        if not LITELLM_AVAILABLE:
            raise LLMConfigurationError(
                "litellm is not installed. Install it with: pip install litellm"
            )

        provider = os.getenv("LLM_PROVIDER", "zai").lower()

        # Validate provider
        if provider not in self.PROVIDERS:
            raise LLMConfigurationError(
                f"Unknown LLM_PROVIDER: {provider}. "
                f"Valid options: {', '.join(self.PROVIDERS.keys())}"
            )

        # Check API key (skip for providers with optional keys like Ollama)
        api_key_env = self.PROVIDERS[provider]
        if api_key_env and not os.getenv(api_key_env):
            raise LLMConfigurationError(
                f"{api_key_env} environment variable is required for LLM_PROVIDER={provider}"
            )

        self._provider = provider
        logger.info("llm_provider_selected", provider=self._provider)
        return self._provider

    def get_llm(self) -> BaseLLM:
        """Get or create the global default LLM client."""
        if self._llm is not None:
            return self._llm

        provider = self.get_provider()

        # All providers use LiteLLM
        self._llm = ChatLiteLLM(provider=provider)

        logger.info(
            "llm_initialized",
            provider=provider,
            model=self._llm.model,
            api_base=self._llm.api_base or "default",
        )

        return self._llm

    def get_profiles(self) -> dict:
        """Get all loaded profiles (for status endpoint)."""
        return get_profiles()

    def create_llm_for_agent(self, agent_def: "AgentDefinition") -> BaseLLM:
        """Create an LLM instance using the model resolution chain.

        Resolution order: override → profile → global default.
        If a fallback provider is available, wraps in FallbackLLM.
        """
        if not LITELLM_AVAILABLE:
            raise LLMConfigurationError(
                "litellm is not installed. Install it with: pip install litellm"
            )

        resolved = resolve_model(agent_def)

        # Validate API key for the resolved provider
        api_key_env = self.PROVIDERS.get(resolved.provider)
        if api_key_env and not os.getenv(api_key_env):
            raise LLMConfigurationError(
                f"{api_key_env} environment variable is required for "
                f"provider={resolved.provider} (source={resolved.source})"
            )

        primary = ChatLiteLLM(
            provider=resolved.provider,
            model=resolved.model,
            temperature=agent_def.temperature,
        )

        has_fallback = False
        result: BaseLLM = primary

        if resolved.fallback_provider:
            fallback_key_env = self.PROVIDERS.get(resolved.fallback_provider)
            # Allow fallback if: key env is None (optional, e.g. Ollama) or key is set
            if fallback_key_env is None or os.getenv(fallback_key_env):
                fallback = ChatLiteLLM(
                    provider=resolved.fallback_provider,
                    model=resolved.fallback_model,
                    temperature=agent_def.temperature,
                )
                result = FallbackLLM(primary, fallback)
                has_fallback = True

        logger.info(
            "llm_created_for_agent",
            agent_id=agent_def.id,
            profile=agent_def.llm_profile,
            provider=resolved.provider,
            model=primary.model,
            source=resolved.source,
            has_fallback=has_fallback,
            fallback_provider=resolved.fallback_provider if has_fallback else None,
        )

        return result

    def get_call_history(self) -> list[dict[str, Any]]:
        """Get the history of LLM API calls."""
        if self._llm is None:
            return []
        return self._llm.get_call_history()

    def clear_call_history(self) -> None:
        """Clear the LLM call history."""
        if self._llm is not None:
            self._llm.clear_call_history()


# Global singleton instance
_llm_service: LLMService | None = None


def get_llm_service() -> LLMService:
    """Get the global LLM service instance."""
    global _llm_service
    if _llm_service is None:
        _llm_service = LLMService()
    return _llm_service
