"""Tests for Settings.validate_startup() — guards against silent
GitHub App misconfiguration that would otherwise hang
update_core_builder at runtime.

Four paths are covered, matching the code in druppie/core/config.py:
  1. All three GITHUB_APP_* vars unset          → startup succeeds (feature disabled).
  2. Any subset set (partial configuration)     → RuntimeError naming what's set vs missing.
  3. All three set + key file exists            → startup succeeds.
  4. All three set + key file path non-existent → RuntimeError naming the bad path.
"""

from __future__ import annotations

import pytest

from druppie.core.config import GitHubAppSettings, Settings


def _settings_with_github_app(**github_app_kwargs) -> Settings:
    """Build a real Settings and swap in a GitHubAppSettings with explicit
    fields. Explicit kwargs override any GITHUB_APP_* env the dev shell
    happens to have set, so these tests are hermetic."""
    settings = Settings()
    settings.github_app = GitHubAppSettings(**github_app_kwargs)
    return settings


def test_validate_startup_all_unset_is_allowed():
    """With no GitHub App configured, the backend still starts (the feature
    is simply disabled — update_core_builder will refuse at runtime instead)."""
    settings = _settings_with_github_app(id="", private_key_path="", installation_id="")
    settings.validate_startup()  # no raise


@pytest.mark.parametrize(
    "kwargs,expected_set,expected_missing",
    [
        (
            {"id": "1234", "private_key_path": "", "installation_id": ""},
            ["GITHUB_APP_ID"],
            ["GITHUB_APP_PRIVATE_KEY_PATH", "GITHUB_APP_INSTALLATION_ID"],
        ),
        (
            {"id": "", "private_key_path": "/tmp/key.pem", "installation_id": ""},
            ["GITHUB_APP_PRIVATE_KEY_PATH"],
            ["GITHUB_APP_ID", "GITHUB_APP_INSTALLATION_ID"],
        ),
        (
            {"id": "1234", "private_key_path": "/tmp/key.pem", "installation_id": ""},
            ["GITHUB_APP_ID", "GITHUB_APP_PRIVATE_KEY_PATH"],
            ["GITHUB_APP_INSTALLATION_ID"],
        ),
        (
            {"id": "", "private_key_path": "", "installation_id": "99"},
            ["GITHUB_APP_INSTALLATION_ID"],
            ["GITHUB_APP_ID", "GITHUB_APP_PRIVATE_KEY_PATH"],
        ),
    ],
)
def test_validate_startup_partial_config_is_rejected(kwargs, expected_set, expected_missing):
    """Any strict subset of the three vars being set is an operator mistake —
    the feature silently disables itself otherwise, and the failure only
    surfaces hours later when update_core_builder tries to push."""
    settings = _settings_with_github_app(**kwargs)
    with pytest.raises(RuntimeError) as exc:
        settings.validate_startup()

    msg = str(exc.value)
    assert "partially configured" in msg
    for name in expected_set:
        assert name in msg, f"error should list {name} as 'set'"
    for name in expected_missing:
        assert name in msg, f"error should list {name} as 'missing'"


def test_validate_startup_fully_configured_with_readable_key_is_allowed(tmp_path):
    """Happy path: all three vars set and the key file exists on disk."""
    key = tmp_path / "app.pem"
    key.write_text("-----BEGIN RSA PRIVATE KEY-----\n")
    settings = _settings_with_github_app(
        id="1234",
        private_key_path=str(key),
        installation_id="99",
    )
    settings.validate_startup()  # no raise


def test_validate_startup_fully_configured_with_missing_key_file_is_rejected(tmp_path):
    """All three vars are set but the key path doesn't point at a real file.
    Without this check the service would silently disable and
    update_core_builder would hang at push time."""
    bogus = tmp_path / "does-not-exist.pem"
    settings = _settings_with_github_app(
        id="1234",
        private_key_path=str(bogus),
        installation_id="99",
    )
    with pytest.raises(RuntimeError) as exc:
        settings.validate_startup()

    msg = str(exc.value)
    assert str(bogus) in msg, "error should name the bad path so ops can fix it"
    assert "GITHUB_APP_PRIVATE_KEY_PATH" in msg


def test_validate_startup_rejects_directory_as_private_key(tmp_path):
    """A directory at the key path is the same silent-failure class as a
    missing file — os.path.isfile() catches both."""
    settings = _settings_with_github_app(
        id="1234",
        private_key_path=str(tmp_path),  # tmp_path is a directory
        installation_id="99",
    )
    with pytest.raises(RuntimeError) as exc:
        settings.validate_startup()
    assert str(tmp_path) in str(exc.value)
