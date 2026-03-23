"""Configuration management for LLM Integration Module.

Handles environment variables and provider configuration.
"""

import json
import os
from dataclasses import dataclass
from typing import Any


@dataclass
class ProviderConfig:
    """Provider configuration."""

    name: str
    priority: int
    api_key: str | None = None
    base_url: str | None = None


class Config:
    """Module configuration manager."""

    def __init__(self) -> None:
        """Initialize configuration from environment variables."""
        self.log_level = os.getenv("LLM_LOG_LEVEL", "INFO")
        self.log_retention_days = int(os.getenv("LLM_LOG_RETENTION_DAYS", "30"))
        self.providers = self._load_providers()

    def _load_providers(self) -> list[ProviderConfig]:
        """Load provider configuration from environment.

        Reads LLM_PROVIDERS JSON array or uses defaults.
        Also reads individual API keys from environment.

        Returns:
            List of provider configurations sorted by priority.
        """
        providers = []

        # Try to load from LLM_PROVIDERS environment variable
        providers_json = os.getenv("LLM_PROVIDERS")
        if providers_json:
            try:
                provider_list = json.loads(providers_json)
                for p in provider_list:
                    name = p.get("name", "").lower()
                    if name:
                        providers.append(
                            ProviderConfig(
                                name=name,
                                priority=p.get("priority", 999),
                                api_key=self._get_api_key(name),
                                base_url=self._get_base_url(name),
                            )
                        )
            except json.JSONDecodeError:
                # Fall back to default providers
                providers = self._get_default_providers()
        else:
            # Use default providers
            providers = self._get_default_providers()

        # Sort by priority
        providers.sort(key=lambda p: p.priority)
        return providers

    def _get_api_key(self, provider_name: str) -> str | None:
        """Get API key for provider from environment.

        Args:
            provider_name: Name of the provider.

        Returns:
            API key or None if not set.
        """
        key_mapping = {
            "openai": "OPENAI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
        }
        env_var = key_mapping.get(provider_name.lower())
        if env_var:
            return os.getenv(env_var)
        return None

    def _get_base_url(self, provider_name: str) -> str | None:
        """Get base URL for provider from environment.

        Args:
            provider_name: Name of the provider.

        Returns:
            Base URL or None if not set.
        """
        if provider_name.lower() == "ollama":
            return os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        return None

    def _get_default_providers(self) -> list[ProviderConfig]:
        """Get default provider configuration.

        Returns:
            List of default providers with API keys from environment.
        """
        defaults = []

        # OpenAI (priority 1)
        openai_key = os.getenv("OPENAI_API_KEY")
        if openai_key:
            defaults.append(
                ProviderConfig(
                    name="openai",
                    priority=1,
                    api_key=openai_key,
                )
            )

        # Anthropic (priority 2)
        anthropic_key = os.getenv("ANTHROPIC_API_KEY")
        if anthropic_key:
            defaults.append(
                ProviderConfig(
                    name="anthropic",
                    priority=2,
                    api_key=anthropic_key,
                )
            )

        # Ollama (priority 3, local)
        ollama_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        defaults.append(
            ProviderConfig(
                name="ollama",
                priority=3,
                base_url=ollama_url,
            )
        )

        return defaults

    def get_provider_config(self, name: str) -> ProviderConfig | None:
        """Get configuration for a specific provider.

        Args:
            name: Provider name.

        Returns:
            Provider configuration or None if not found.
        """
        for provider in self.providers:
            if provider.name.lower() == name.lower():
                return provider
        return None

    def to_dict(self) -> dict[str, Any]:
        """Convert configuration to dictionary.

        Returns:
            Configuration dictionary (without sensitive data).
        """
        return {
            "log_level": self.log_level,
            "log_retention_days": self.log_retention_days,
            "providers": [
                {
                    "name": p.name,
                    "priority": p.priority,
                    "has_api_key": p.api_key is not None,
                    "base_url": p.base_url,
                }
                for p in self.providers
            ],
        }


# Global config instance
_config: Config | None = None


def get_config() -> Config:
    """Get or create global configuration instance.

    Returns:
        Configuration instance.
    """
    global _config
    if _config is None:
        _config = Config()
    return _config


def reset_config() -> None:
    """Reset global configuration (for testing)."""
    global _config
    _config = None
