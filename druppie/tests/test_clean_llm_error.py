"""Tests for clean_llm_error."""

import pytest

from druppie.llm.base import clean_llm_error


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("DeploymentNotFound: model xyz", "Model deployment not found"),
        ("The model does not exist in this region", "Model deployment not found"),
        ("Authentication Failed for provider openai", "Authentication failed — check the API key"),
        ("AuthenticationError: invalid key", "Authentication failed — check the API key"),
        ("NotFoundError: model gpt-99 not found", "Model not found"),
        ("RateLimitError: too many requests", "Rate limited — try again later"),
        ("Error: rate_limit exceeded", "Rate limited — try again later"),
        ("Request timeout after 30s", "Request timed out"),
        ("litellm.Timeout: connection timed out", "Request timed out"),
        ("Connection refused by remote host", "Connection failed — check the provider URL"),
        ("connection reset by peer", "Connection failed — check the provider URL"),
        ("Connection closed unexpectedly", "Connection failed — check the provider URL"),
        ("LLMConfigurationError: missing API base URL", "missing API base URL"),
        ("LLM error: something went wrong", "something went wrong"),
        ("litellm.APIError: bad request", "APIError: bad request"),
        ("AnthropicException - overloaded", "overloaded"),
        ("OpenAIException - server error", "server error"),
        ("simple short error", "simple short error"),
    ],
    ids=[
        "deployment-not-found",
        "does-not-exist",
        "auth-failed",
        "auth-error",
        "not-found",
        "rate-limit-error",
        "rate-limit-underscore",
        "timeout-lowercase",
        "timeout-litellm",
        "connection-refused",
        "connection-reset",
        "connection-closed",
        "config-error",
        "llm-error-prefix",
        "litellm-prefix",
        "anthropic-prefix",
        "openai-prefix",
        "passthrough-short",
    ],
)
def test_clean_llm_error(raw, expected):
    assert clean_llm_error(raw) == expected


def test_long_error_truncated():
    raw = "x" * 200
    result = clean_llm_error(raw)
    assert len(result) <= 121
    assert result.endswith("…")


def test_exact_120_not_truncated():
    raw = "x" * 120
    assert clean_llm_error(raw) == raw
