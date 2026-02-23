"""LLM module for Druppie platform.

Per-agent LLM profiles with ordered provider chains and automatic fallback.

Usage:
    from druppie.llm import get_llm_service

    # Create LLM for an agent (uses its llm_profile)
    llm = get_llm_service().create_llm_for_agent(agent_definition)

    # Use it
    response = await llm.achat(messages=[...], tools=[...])

Environment variables:
    LLM_PROVIDER: Global default (zai, deepinfra, azure_foundry)
    LLM_FORCE_PROVIDER: Override all profiles
    LLM_FORCE_MODEL: Override model (requires LLM_FORCE_PROVIDER)
"""

from .base import (
    AuthenticationError,
    BaseLLM,
    LLMError,
    LLMResponse,
    RateLimitError,
    ServerError,
)
from .fallback import FallbackLLM
from .litellm_provider import ChatLiteLLM, LITELLM_AVAILABLE
from .resolver import ResolvedModel, resolve_model
from .service import LLMConfigurationError, LLMService, get_llm_service

__all__ = [
    # Base classes
    "BaseLLM",
    "LLMResponse",
    # Provider (LiteLLM-based)
    "ChatLiteLLM",
    "LITELLM_AVAILABLE",
    # Fallback
    "FallbackLLM",
    # Resolver
    "ResolvedModel",
    "resolve_model",
    # Service
    "LLMService",
    "get_llm_service",
    # Exceptions
    "LLMError",
    "LLMConfigurationError",
    "RateLimitError",
    "AuthenticationError",
    "ServerError",
]
