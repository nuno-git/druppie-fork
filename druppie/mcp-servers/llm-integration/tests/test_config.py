"""Tests for configuration management."""

import os
import unittest
from unittest.mock import patch

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from v1.config import Config, ProviderConfig, get_config, reset_config


class TestConfig(unittest.TestCase):
    """Test configuration management."""

    def setUp(self):
        """Reset config before each test."""
        reset_config()
        # Clear environment variables
        for key in ["LLM_PROVIDERS", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "OLLAMA_BASE_URL"]:
            if key in os.environ:
                del os.environ[key]

    def test_default_config(self):
        """Test default configuration."""
        config = Config()
        self.assertEqual(config.log_level, "INFO")
        self.assertEqual(config.log_retention_days, 30)

    def test_custom_log_level(self):
        """Test custom log level from environment."""
        with patch.dict(os.environ, {"LLM_LOG_LEVEL": "DEBUG"}):
            config = Config()
            self.assertEqual(config.log_level, "DEBUG")

    def test_custom_retention_days(self):
        """Test custom retention days from environment."""
        with patch.dict(os.environ, {"LLM_LOG_RETENTION_DAYS": "60"}):
            config = Config()
            self.assertEqual(config.log_retention_days, 60)

    def test_provider_config_from_env(self):
        """Test provider configuration from LLM_PROVIDERS."""
        providers_json = '[{"name": "openai", "priority": 1}, {"name": "anthropic", "priority": 2}]'
        with patch.dict(
            os.environ,
            {
                "LLM_PROVIDERS": providers_json,
                "OPENAI_API_KEY": "test-key",
                "ANTHROPIC_API_KEY": "test-key-2",
            },
        ):
            config = Config()
            self.assertEqual(len(config.providers), 2)
            self.assertEqual(config.providers[0].name, "openai")
            self.assertEqual(config.providers[0].priority, 1)
            self.assertEqual(config.providers[1].name, "anthropic")
            self.assertEqual(config.providers[1].priority, 2)

    def test_default_providers_with_keys(self):
        """Test default providers when API keys are set."""
        with patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "test-openai-key",
                "ANTHROPIC_API_KEY": "test-anthropic-key",
            },
        ):
            config = Config()
            provider_names = [p.name for p in config.providers]
            self.assertIn("openai", provider_names)
            self.assertIn("anthropic", provider_names)
            self.assertIn("ollama", provider_names)

    def test_get_provider_config(self):
        """Test getting specific provider config."""
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
            config = Config()
            provider = config.get_provider_config("openai")
            self.assertIsNotNone(provider)
            self.assertEqual(provider.name, "openai")

    def test_get_nonexistent_provider(self):
        """Test getting non-existent provider config."""
        config = Config()
        provider = config.get_provider_config("nonexistent")
        self.assertIsNone(provider)

    def test_config_to_dict(self):
        """Test config serialization."""
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
            config = Config()
            data = config.to_dict()
            self.assertEqual(data["log_level"], "INFO")
            self.assertEqual(data["log_retention_days"], 30)
            self.assertIn("providers", data)


class TestGetConfig(unittest.TestCase):
    """Test get_config function."""

    def setUp(self):
        """Reset config before each test."""
        reset_config()

    def test_get_config_singleton(self):
        """Test that get_config returns singleton."""
        config1 = get_config()
        config2 = get_config()
        self.assertIs(config1, config2)


if __name__ == "__main__":
    unittest.main()
