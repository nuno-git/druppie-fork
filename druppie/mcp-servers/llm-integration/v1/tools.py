"""MCP tool definitions for LLM Integration Module.

Implements the MCP tools exposed by this module:
- chat_completion: Execute chat completion with automatic failover
- count_tokens: Count tokens for given text
- list_providers: List available providers and their status
"""

from typing import Any, Literal, cast

from fastmcp import FastMCP

from .config import get_config
from .logging import configure_logging, get_logger
from .models import (
    ChatCompletionRequest,
    ChatMessage,
    TokenCountRequest,
)
from .providers import ProviderError, ProviderManager

KNOWN_MODELS: dict[str, list[str]] = {
    "openai": [
        "gpt-4",
        "gpt-4-turbo",
        "gpt-4-turbo-preview",
        "gpt-4o",
        "gpt-4o-mini",
        "gpt-3.5-turbo",
        "gpt-3.5-turbo-16k",
    ],
    "anthropic": [
        "claude-3-opus-20240229",
        "claude-3-sonnet-20240229",
        "claude-3-haiku-20240307",
        "claude-3-5-sonnet-20241022",
        "claude-3-5-haiku-20241022",
    ],
    "ollama": [
        "llama2",
        "llama3",
        "llama3.1",
        "mistral",
        "codellama",
        "phi3",
    ],
}

ALL_KNOWN_MODELS: set[str] = {model for models in KNOWN_MODELS.values() for model in models}

configure_logging()
logger = get_logger()

provider_manager = ProviderManager(get_config())


def validate_model(model: str | None) -> tuple[bool, str | None]:
    """Validate that a model name is recognized.

    Checks if the model is in the known models list for any provider.
    A model is considered valid if it's a known model or if no model
    is specified (None), which will use the provider's default.

    Args:
        model: Model identifier to validate, or None.

    Returns:
        Tuple of (is_valid, error_message). error_message is None if valid.
    """
    if model is None:
        return True, None

    if model in ALL_KNOWN_MODELS:
        return True, None

    for provider, models in KNOWN_MODELS.items():
        for known_model in models:
            if model.startswith(known_model) or known_model in model:
                return True, None

    valid_models = ", ".join(sorted(ALL_KNOWN_MODELS)[:10]) + "..."
    return False, f"Unknown model '{model}'. Known models include: {valid_models}"


async def chat_completion(
    messages: list[dict[str, str]],
    model: str | None = None,
    stream: bool = False,
    max_tokens: int | None = None,
    temperature: float | None = None,
) -> dict[str, Any]:
    """Execute chat completion with automatic failover.

    Sends messages to LLM providers with automatic failover on errors.

    Args:
        messages: List of message dicts with 'role' and 'content' keys.
            Roles: 'system', 'user', 'assistant'
        model: Model identifier (optional, uses first available).
        stream: Whether to stream the response (default: False).
        max_tokens: Maximum tokens to generate (optional).
        temperature: Sampling temperature 0-2 (optional).

    Returns:
        Dict with content, model, provider, usage, estimated_cost, finish_reason.

    Example:
        chat_completion(
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "Hello!"}
            ],
            model="gpt-3.5-turbo"
        )
    """
    try:
        if model is not None:
            is_valid, error_msg = validate_model(model)
            if not is_valid:
                logger.warning("Model validation failed", model=model, error=error_msg)
                return {
                    "success": False,
                    "error": error_msg,
                }

        validated_messages = []
        for msg in messages:
            role = msg.get("role", "")
            if role not in ("system", "user", "assistant"):
                return {
                    "success": False,
                    "error": f"Invalid role: {role}. Must be 'system', 'user', or 'assistant'",
                }
            validated_messages.append(
                ChatMessage(
                    role=cast(Literal["system", "user", "assistant"], role),
                    content=msg.get("content", ""),
                )
            )

        # Build request
        request = ChatCompletionRequest(
            messages=validated_messages,
            model=model,
            stream=stream,
            max_tokens=max_tokens,
            temperature=temperature,
        )

        logger.info(
            "Chat completion request",
            message_count=len(messages),
            model=model or "default",
            stream=stream,
        )

        # Execute completion
        response = await provider_manager.chat_completion(request)

        # Return as dict
        return {
            "success": True,
            "content": response.content,
            "model": response.model,
            "provider": response.provider,
            "usage": {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            },
            "estimated_cost": response.estimated_cost,
            "finish_reason": response.finish_reason,
        }

    except ProviderError as e:
        logger.error("All providers failed", error=str(e))
        return {
            "success": False,
            "error": str(e),
            "providers_tried": e.provider if hasattr(e, "provider") else "all",
        }
    except Exception as e:
        logger.error("Unexpected error in chat_completion", error=str(e))
        return {
            "success": False,
            "error": f"Internal error: {str(e)}",
        }


async def count_tokens(
    text: str,
    model: str | None = None,
) -> dict[str, Any]:
    """Count tokens for given text.

    Uses tiktoken for OpenAI models, falls back to character-based estimate.

    Args:
        text: Text to count tokens for.
        model: Model identifier (optional, defaults to gpt-3.5-turbo).

    Returns:
        Dict with token_count and model used.

    Example:
        count_tokens(text="Hello, world!", model="gpt-3.5-turbo")
    """
    try:
        request = TokenCountRequest(text=text, model=model)

        logger.info("Token count request", model=model or "default")

        response = await provider_manager.count_tokens(request)

        return {
            "success": True,
            "token_count": response.token_count,
            "model": response.model,
        }

    except Exception as e:
        logger.error("Error counting tokens", error=str(e))
        return {
            "success": False,
            "error": f"Failed to count tokens: {str(e)}",
        }


async def list_providers() -> dict[str, Any]:
    """List available providers and their status.

    Returns information about configured LLM providers including
    their priority and availability status.

    Returns:
        Dict with list of providers (name, priority, available, models).

    Example:
        list_providers()
    """
    try:
        providers = provider_manager.list_providers()

        logger.info("List providers request", provider_count=len(providers))

        return {
            "success": True,
            "providers": providers,
        }

    except Exception as e:
        logger.error("Error listing providers", error=str(e))
        return {
            "success": False,
            "error": f"Failed to list providers: {str(e)}",
        }


def register_tools(mcp: FastMCP) -> None:
    """Register all tools with the MCP server.

    Args:
        mcp: FastMCP server instance.
    """
    mcp.tool()(chat_completion)
    mcp.tool()(count_tokens)
    mcp.tool()(list_providers)

    logger.info("LLM integration tools registered")
