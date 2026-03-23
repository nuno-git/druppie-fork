"""MCP tool definitions for LLM Integration Module.

Implements the MCP tools exposed by this module.
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

# Initialize logger
configure_logging()
logger = get_logger()

# Initialize provider manager
provider_manager = ProviderManager(get_config())


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
        # Validate and convert messages
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
