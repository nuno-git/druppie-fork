"""Tests for provider abstraction layer."""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from v1.config import Config, ProviderConfig
from v1.models import ChatCompletionRequest, ChatMessage, TokenCountRequest
from v1.providers import ProviderError, ProviderManager


class TestProviderManager(unittest.TestCase):
    """Test provider manager."""

    def setUp(self):
        """Set up test fixtures."""
        self.config = Config()
        self.config.providers = [
            ProviderConfig(name="openai", priority=1, api_key="test-key"),
        ]

    def test_initialization(self):
        """Test provider manager initialization."""
        manager = ProviderManager(self.config)
        self.assertEqual(manager.config, self.config)

    def test_get_model_for_provider(self):
        """Test getting model for provider."""
        manager = ProviderManager(self.config)
        model = manager._get_model_for_provider("openai", None)
        self.assertEqual(model, "gpt-3.5-turbo")

    def test_get_model_for_provider_custom(self):
        """Test getting custom model for provider."""
        manager = ProviderManager(self.config)
        model = manager._get_model_for_provider("openai", "gpt-4")
        self.assertEqual(model, "gpt-4")

    def test_estimate_cost(self):
        """Test cost estimation."""
        manager = ProviderManager(self.config)
        cost = manager._estimate_cost("gpt-3.5-turbo", 1000, 500)
        self.assertGreater(cost, 0)
        self.assertIsInstance(cost, float)

    def test_estimate_cost_unknown_model(self):
        """Test cost estimation for unknown model."""
        manager = ProviderManager(self.config)
        cost = manager._estimate_cost("unknown-model", 1000, 500)
        self.assertGreaterEqual(cost, 0)


class TestProviderManagerAsync(unittest.IsolatedAsyncioTestCase):
    """Async tests for provider manager."""

    async def test_count_tokens_openai(self):
        """Test token counting for OpenAI model."""
        config = Config()
        manager = ProviderManager(config)

        request = TokenCountRequest(text="Hello, world!", model="gpt-3.5-turbo")
        response = await manager.count_tokens(request)

        self.assertGreater(response.token_count, 0)
        self.assertEqual(response.model, "gpt-3.5-turbo")

    async def test_count_tokens_fallback(self):
        """Test token counting fallback for non-OpenAI models."""
        config = Config()
        manager = ProviderManager(config)

        request = TokenCountRequest(text="Hello, world!", model="claude-3-sonnet")
        response = await manager.count_tokens(request)

        # Should use character-based estimate
        self.assertGreater(response.token_count, 0)
        self.assertEqual(response.model, "claude-3-sonnet")

    def test_list_providers(self):
        """Test listing providers."""
        config = Config()
        config.providers = [
            ProviderConfig(name="openai", priority=1, api_key="test-key"),
            ProviderConfig(name="ollama", priority=2),
        ]
        manager = ProviderManager(config)

        providers = manager.list_providers()
        self.assertEqual(len(providers), 2)
        self.assertEqual(providers[0]["name"], "openai")
        self.assertEqual(providers[1]["name"], "ollama")

    def test_check_provider_available_with_key(self):
        """Test provider availability with API key."""
        config = Config()
        manager = ProviderManager(config)

        provider_config = ProviderConfig(name="openai", priority=1, api_key="test-key")
        self.assertTrue(manager._check_provider_available(provider_config))

    def test_check_provider_available_without_key(self):
        """Test provider availability without API key."""
        config = Config()
        manager = ProviderManager(config)

        provider_config = ProviderConfig(name="openai", priority=1, api_key=None)
        self.assertFalse(manager._check_provider_available(provider_config))


if __name__ == "__main__":
    unittest.main()
