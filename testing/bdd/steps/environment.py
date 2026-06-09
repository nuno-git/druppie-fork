"""Behave environment hooks for BDD tests.

Sets up the FastAPI TestClient and test database fixtures.

Usage:
    cd druppie && python -m behave ../testing/bdd/features/ --tags=-wip

Architecture:
    - before_all: Create test app, TestClient, and test DB
    - after_all: Clean up test DB and close client
    - before_scenario: Reset DB state between scenarios
    - after_scenario: Tear down per-scenario state
"""

import os
import sys

# Ensure the druppie package is importable when running from testing/bdd/
_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
_druppie_path = os.path.join(_project_root, "druppie")
if _druppie_path not in sys.path:
    sys.path.insert(0, _druppie_path)


def before_all(context):
    """Set up shared test infrastructure.

    Creates:
    - FastAPI TestClient pointing to the real app
    - Test database (SQLite in-memory or temp file)
    - Mock auth that bypasses Keycloak
    """
    from fastapi.testclient import TestClient
    from unittest.mock import patch, MagicMock

    # Use a temporary SQLite database for tests
    context.test_db_url = "sqlite:///./test_bdd.db"

    # Patch the database URL before importing the app
    os.environ["DATABASE_URL"] = context.test_db_url

    # Patch auth to bypass Keycloak — returns a fixed test user
    context._auth_patch = patch("druppie.api.deps.get_current_user")
    mock_auth = context._auth_patch.start()
    mock_auth.return_value = {
        "sub": "00000000-0000-0000-0000-000000000001",
        "preferred_username": "bdd_test_user",
        "email": "bdd@test.local",
        "realm_access": {"roles": ["admin"]},
    }

    # Import and create the app after patching
    from druppie.api.main import create_app
    app = create_app()
    context.client = TestClient(app, raise_server_exceptions=False)

    # Store references for step definitions
    context.app = app


def after_all(context):
    """Tear down shared test infrastructure."""
    from unittest.mock import patch

    # Stop auth mock
    if hasattr(context, "_auth_patch"):
        context._auth_patch.stop()

    # Clean up test database file
    if hasattr(context, "test_db_url"):
        db_file = context.test_db_url.replace("sqlite:///", "")
        if os.path.exists(db_file):
            os.remove(db_file)


def before_scenario(context, scenario):
    """Reset state before each scenario.

    TODO: Add test DB fixture reset here:
    - Truncate all tables (or use transaction rollback)
    - Re-seed any required base data
    """
    context.exception = None
    context.result = None


def after_scenario(context, scenario):
    """Clean up after each scenario.

    TODO: Add per-scenario cleanup:
    - Roll back any uncommitted transactions
    - Release any held resources
    """
    pass
