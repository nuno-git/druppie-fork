"""LLM module for Druppie platform.

All providers use LiteLLM internally for standardized tool calling.

Usage:
    from druppie.llm import get_llm_service

    # Get configured LLM (reads LLM_PROVIDER from env)
    llm = get_llm_service().get_llm()

    # Use it
    response = await llm.achat(messages=[...], tools=[...])

Environment variables:
    LLM_PROVIDER: zai, deepinfra, openai, anthropic

    Provider-specific (e.g., for ZAI):
        ZAI_API_KEY, ZAI_MODEL, ZAI_BASE_URL
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
