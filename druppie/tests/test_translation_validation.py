"""Tests for TranslationService API key validation.

The translation service uses DeepInfra regardless of LLM_PROVIDER. When
DEEPINFRA_API_KEY is not set, translation must fail loudly rather than
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


def test_translation_raises_when_deepinfra_key_missing():
    """Accessing the LLM without DEEPINFRA_API_KEY raises immediately."""
    svc = TranslationService()
    with patch.dict(os.environ, {}, clear=False):
        env = os.environ.copy()
        env.pop("DEEPINFRA_API_KEY", None)
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(TranslationNotAvailableError, match="DEEPINFRA_API_KEY"):
                _ = svc.llm


def test_translation_service_initializes_with_key_present():
    """With the key set, the LLM property should not raise."""
    svc = TranslationService()
    with patch.dict(os.environ, {"DEEPINFRA_API_KEY": "test-key-123"}):
        try:
            _ = svc.llm
        except ImportError:
            pass  # litellm may not be installed in test env — that's fine


def test_startup_validation_warns_when_deepinfra_key_missing(caplog):
    """Settings.validate_startup() logs a warning when DEEPINFRA_API_KEY is empty."""
    from druppie.core.config import Settings
    import structlog
    import logging

    structlog.configure(
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
    )

    settings = Settings()
    settings.llm.deepinfra_api_key = ""

    with caplog.at_level(logging.WARNING):
        settings.validate_startup()

    assert any("DEEPINFRA_API_KEY" in r.message for r in caplog.records)
