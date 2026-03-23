"""Pydantic models for LLM Integration Module.

Request and response validation models.
"""

from typing import Any, Literal

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    """Single chat message."""

    role: Literal["system", "user", "assistant"]
    content: str


class ChatCompletionRequest(BaseModel):
    """Chat completion request model."""

    messages: list[ChatMessage] = Field(
        ...,
        description="List of chat messages for the conversation",
    )
    model: str | None = Field(
        default=None,
        description="Model identifier (optional, uses first available)",
    )
    stream: bool = Field(
        default=False,
        description="Whether to stream the response",
    )
    max_tokens: int | None = Field(
        default=None,
        description="Maximum tokens to generate",
    )
    temperature: float | None = Field(
        default=None,
        ge=0.0,
        le=2.0,
        description="Sampling temperature (0-2)",
    )


class TokenUsage(BaseModel):
    """Token usage information."""

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class ChatCompletionResponse(BaseModel):
    """Chat completion response model."""

    content: str
    model: str
    provider: str
    usage: TokenUsage
    estimated_cost: float
    finish_reason: str | None = None


class TokenCountRequest(BaseModel):
    """Token count request model."""

    text: str = Field(
        ...,
        description="Text to count tokens for",
    )
    model: str | None = Field(
        default=None,
        description="Model identifier (optional)",
    )


class TokenCountResponse(BaseModel):
    """Token count response model."""

    token_count: int
    model: str


class ProviderInfo(BaseModel):
    """Provider information model."""

    name: str
    priority: int
    available: bool
    models: list[str] | None = None


class ProviderListResponse(BaseModel):
    """Provider list response model."""

    providers: list[ProviderInfo]


class ErrorResponse(BaseModel):
    """Error response model."""

    error: str
    details: dict[str, Any] | None = None
