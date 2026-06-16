"""Tests for TranslationService provider resolution.

The translation service uses whatever LLM provider is available. When no
provider has an API key configured, translation must fail loudly rather than
silently returning untranslated text.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from druppie.core.translation import (
    TranslationNotAvailableError,
    TranslationService,
)


def _env_without_llm_keys() -> dict:
    """Return a copy of os.environ with all LLM API keys removed."""
    env = os.environ.copy()
    for key in list(env):
        if key.endswith("_API_KEY") and key != "INTERNAL_API_KEY":
            env.pop(key)
    env.pop("LLM_PROVIDER", None)
    return env


def test_translation_raises_when_no_provider_available():
    """Accessing the LLM without any provider API key raises immediately."""
    svc = TranslationService()
    with patch.dict(os.environ, _env_without_llm_keys(), clear=True):
        with pytest.raises(TranslationNotAvailableError, match="No LLM provider"):
            _ = svc.llm


def test_translation_service_initializes_with_key_present():
    """With any provider key set, the LLM property should not raise."""
    svc = TranslationService()
    with patch.dict(os.environ, {"ZAI_API_KEY": "test-key-123", "LLM_PROVIDER": "zai"}):
        try:
            _ = svc.llm
        except ImportError:
            pass  # litellm may not be installed in test env


def test_startup_validation_warns_when_no_provider(caplog):
    """Settings.validate_startup() logs a warning when no LLM provider is available."""
    from druppie.core.config import Settings
    import structlog
    import logging

    structlog.configure(
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
    )

    settings = Settings()
    settings.github_app.id = ""
    settings.github_app.private_key_path = ""
    settings.github_app.installation_id = ""

    with patch.dict(os.environ, _env_without_llm_keys(), clear=True):
        with caplog.at_level(logging.WARNING):
            settings.validate_startup()

    assert any("translation" in r.message.lower() for r in caplog.records)
