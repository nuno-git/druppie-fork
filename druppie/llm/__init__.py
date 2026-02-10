"""LLM module for Druppie platform.

Providers:
- ChatLiteLLM: Unified LLM interface (recommended) - supports 100+ providers
- ChatZAI: Z.AI GLM models (legacy)
- ChatDeepInfra: DeepInfra API (legacy)

Usage:
    from druppie.llm import get_llm_service

    # Get configured LLM
    llm = get_llm_service().get_llm()

    # Use it
    response = await llm.achat(messages=[...], tools=[...])
"""

from .base import BaseLLM, LLMResponse, LLMError, RateLimitError, AuthenticationError, ServerError
from .zai import ChatZAI
from .deepinfra import ChatDeepInfra
from .litellm_provider import ChatLiteLLM, LITELLM_AVAILABLE
from .service import LLMService, get_llm_service, LLMConfigurationError

__all__ = [
    # Base classes
    "BaseLLM",
    "LLMResponse",
    # Providers
    "ChatLiteLLM",  # Recommended
    "ChatZAI",      # Legacy
    "ChatDeepInfra",  # Legacy
    "LITELLM_AVAILABLE",
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
