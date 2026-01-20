"""Application configuration."""

import os
from pathlib import Path


class Config:
    """Flask configuration."""

    # Secret key
    SECRET_KEY = os.getenv("SECRET_KEY", os.urandom(32).hex())

    # Database - Use SQLite for local development
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL", "sqlite:///druppie.db"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Development mode - skip Keycloak auth
    DEV_MODE = os.getenv("DEV_MODE", "true").lower() == "true"

    # Redis
    REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    # Keycloak
    KEYCLOAK_SERVER_URL = os.getenv("KEYCLOAK_SERVER_URL", "http://localhost:8080")
    KEYCLOAK_ISSUER_URL = os.getenv("KEYCLOAK_ISSUER_URL", "http://localhost:8080")
    KEYCLOAK_REALM = os.getenv("KEYCLOAK_REALM", "druppie")
    KEYCLOAK_CLIENT_ID = os.getenv("KEYCLOAK_CLIENT_ID", "druppie-backend")
    KEYCLOAK_CLIENT_SECRET = os.getenv("KEYCLOAK_CLIENT_SECRET", "")

    # Workspace
    WORKSPACE_PATH = os.getenv("WORKSPACE_PATH", "/app/workspace")

    # LLM
    LLM_PROVIDER = os.getenv("LLM_PROVIDER", "zai")
    ZAI_API_KEY = os.getenv("ZAI_API_KEY", "")
    ZAI_MODEL = os.getenv("ZAI_MODEL", "GLM-4.7")
    ZAI_BASE_URL = os.getenv("ZAI_BASE_URL", "https://api.z.ai/api/coding/paas/v4")
    OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")


# Load MCP permissions from YAML
def load_mcp_permissions():
    """Load MCP permission configuration."""
    import yaml

    config_path = Path(__file__).parent.parent.parent / "iac" / "users.yaml"

    if config_path.exists():
        with open(config_path) as f:
            data = yaml.safe_load(f) or {}
            return {
                "roles": data.get("roles", []),
                "approvalWorkflows": data.get("approvalWorkflows", {}),
                "mcpPermissionLevels": data.get("mcpPermissionLevels", {}),
            }

    return {"roles": [], "approvalWorkflows": {}, "mcpPermissionLevels": {}}
