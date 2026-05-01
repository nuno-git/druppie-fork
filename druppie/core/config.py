"""Centralized configuration management for Druppie platform.

This module provides a single source of truth for all configuration values.
Uses Pydantic Settings for validation and environment variable support.
"""

import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
import structlog

logger = structlog.get_logger()


class DatabaseSettings(BaseSettings):
    """Database configuration."""

    model_config = SettingsConfigDict(env_prefix="DB_")

    url: str = Field(
        default="sqlite:///./druppie.db",
        description="Database connection URL",
    )
    echo: bool = Field(
        default=False,
        description="Enable SQLAlchemy query logging",
    )
    pool_size: int = Field(
        default=5,
        description="Connection pool size",
    )
    max_overflow: int = Field(
        default=10,
        description="Maximum pool overflow connections",
    )


class KeycloakSettings(BaseSettings):
    """Keycloak authentication configuration."""

    model_config = SettingsConfigDict(env_prefix="KEYCLOAK_")

    url: str = Field(
        default="http://localhost:8080",
        description="Keycloak server URL",
    )
    realm: str = Field(
        default="druppie",
        description="Keycloak realm name",
    )
    issuer_url: Optional[str] = Field(
        default=None,
        description="Custom issuer URL (defaults to Keycloak URL)",
    )

    @property
    def effective_issuer_url(self) -> str:
        """Get the effective issuer URL."""
        return self.issuer_url or self.url


class GiteaSettings(BaseSettings):
    """Gitea version control configuration."""

    model_config = SettingsConfigDict(env_prefix="GITEA_")

    url: str = Field(
        default="http://gitea:3000",
        description="External Gitea URL",
    )
    internal_url: Optional[str] = Field(
        default=None,
        description="Internal Gitea URL (defaults to url)",
    )
    admin_user: str = Field(
        default="gitea_admin",
        description="Gitea admin username",
    )
    admin_password: str = Field(
        default="",
        description="Gitea admin password (required for Gitea operations)",
    )
    org: str = Field(
        default="druppie",
        description="Gitea organization for projects",
    )
    token: str = Field(
        default="",
        description="Gitea API token",
    )

    @property
    def effective_internal_url(self) -> str:
        """Get the effective internal URL."""
        return self.internal_url or self.url

    @property
    def is_configured(self) -> bool:
        """Check if Gitea credentials are configured."""
        return bool(self.admin_password or self.token)


class LLMSettings(BaseSettings):
    """LLM provider configuration."""

    model_config = SettingsConfigDict(env_prefix="")

    provider: str = Field(
        default="auto",
        alias="LLM_PROVIDER",
        description="LLM provider (auto, zai, mock)",
    )
    zai_api_key: str = Field(
        default="",
        alias="ZAI_API_KEY",
        description="Z.AI API key",
    )
    zai_model: str = Field(
        default="GLM-4.7",
        alias="ZAI_MODEL",
        description="Z.AI model name",
    )
    zai_base_url: str = Field(
        default="https://api.z.ai/api/coding/paas/v4",
        alias="ZAI_BASE_URL",
        description="Z.AI API base URL",
    )
    foundry_model: str = Field(
        default="GPT-5-MINI",
        alias="FOUNDRY_MODEL",
        description="Azure Foundry model name",
    )
    foundry_api_url: str = Field(
        default="",
        alias="FOUNDRY_API_URL",
        description="Azure Foundry API URL",
    )
    foundry_project_endpoint: str = Field(
        default="",
        alias="FOUNDRY_PROJECT_ENDPOINT",
        description="Azure AI Foundry project endpoint for agent deployment",
    )


class GitHubAppSettings(BaseSettings):
    """GitHub App configuration for update_core_builder agent.

    When all three values are set, the backend can generate short-lived
    installation tokens for pushing to GitHub repos. When any are missing,
    the GitHubAppService is disabled (no error, just returns None).
    """

    model_config = SettingsConfigDict(env_prefix="GITHUB_APP_")

    # Numeric app ID from GitHub (Settings → Developer settings → GitHub Apps)
    id: str = Field(
        default="",
        description="GitHub App ID",
    )
    # Absolute path to the .pem private key file downloaded from GitHub
    private_key_path: str = Field(
        default="",
        description="Path to GitHub App private key (.pem file)",
    )
    # Numeric installation ID (visible in the URL after installing the app)
    installation_id: str = Field(
        default="",
        description="GitHub App installation ID",
    )

    @property
    def is_configured(self) -> bool:
        """All three values must be set for the service to work."""
        return bool(self.id and self.private_key_path and self.installation_id)

    @property
    def is_partially_configured(self) -> bool:
        """Any of the three values set but not all. Indicates operator intent
        to use the feature but a misconfiguration that would silently fall
        back to a disabled service — we prefer to fail startup."""
        set_count = sum(bool(v) for v in (self.id, self.private_key_path, self.installation_id))
        return 0 < set_count < 3


class MCPSettings(BaseSettings):
    """MCP microservice configuration."""

    model_config = SettingsConfigDict(env_prefix="MCP_")

    coding_url: str = Field(
        default="http://module-coding:9001",
        description="Coding MCP server URL",
    )
    docker_url: str = Field(
        default="http://module-docker:9002",
        description="Docker MCP server URL",
    )
    filesearch_url: str = Field(
        default="http://module-filesearch:9004",
        description="Filesearch MCP server URL",
    )
    timeout: int = Field(
        default=300,
        description="MCP request timeout in seconds",
    )


class WorkspaceSettings(BaseSettings):
    """Workspace configuration."""

    model_config = SettingsConfigDict(env_prefix="WORKSPACE_")

    root: Path = Field(
        default=Path("/app/workspace"),
        description="Root directory for workspaces",
    )

    @field_validator("root", mode="before")
    @classmethod
    def parse_path(cls, v):
        if isinstance(v, str):
            return Path(v)
        return v


class APISettings(BaseSettings):
    """API server configuration."""

    model_config = SettingsConfigDict(env_prefix="API_", populate_by_name=True)

    host: str = Field(
        default="0.0.0.0",
        description="API server host",
    )
    port: int = Field(
        default=8000,
        description="API server port",
    )
    cors_origins: str = Field(
        default="http://localhost:5173,http://localhost:5273,http://localhost:8100,http://localhost:3000",
        alias="CORS_ORIGINS",
        description="Comma-separated list of allowed CORS origins",
    )
    dev_mode: bool = Field(
        default=False,
        alias="DEV_MODE",
        description="Enable development mode (bypasses auth)",
    )

    @property
    def cors_origins_list(self) -> list[str]:
        """Parse CORS origins into a list."""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


class Settings(BaseSettings):
    """Main settings container aggregating all configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Sub-settings
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    keycloak: KeycloakSettings = Field(default_factory=KeycloakSettings)
    gitea: GiteaSettings = Field(default_factory=GiteaSettings)
    github_app: GitHubAppSettings = Field(default_factory=GitHubAppSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    mcp: MCPSettings = Field(default_factory=MCPSettings)
    workspace: WorkspaceSettings = Field(default_factory=WorkspaceSettings)
    api: APISettings = Field(default_factory=APISettings)

    def log_config(self):
        """Log configuration (masking sensitive values)."""
        logger.info(
            "config_loaded",
            db_url=self.database.url.split("@")[-1] if "@" in self.database.url else "***",
            keycloak_url=self.keycloak.url,
            keycloak_realm=self.keycloak.realm,
            gitea_url=self.gitea.url,
            gitea_configured=self.gitea.is_configured,
            llm_provider=self.llm.provider,
            llm_model=self.llm.zai_model,
            dev_mode=self.api.dev_mode,
            workspace_root=str(self.workspace.root),
        )

        # Log GitHub App status so operators know if update_core_builder is available
        logger.info(
            "github_app_config",
            configured=self.github_app.is_configured,
        )

        # Security warnings for missing credentials
        if not self.gitea.is_configured:
            logger.warning(
                "gitea_credentials_not_configured",
                message="GITEA_ADMIN_PASSWORD or GITEA_TOKEN not set - Gitea operations will fail",
            )

    def validate_startup(self) -> None:
        """Raise at startup if misconfiguration would cause silent runtime failures.

        Current checks:
        - GitHub App: if any of GITHUB_APP_ID / _PRIVATE_KEY_PATH / _INSTALLATION_ID
          is set but not all, fail. Operator clearly intended to enable
          update_core_builder; a partial config silently disables it and the
          agent hangs later when it tries to push. Fail now instead.
        - GitHub App: if all three are set, the private key file must exist and
          be readable. A dangling GITHUB_APP_PRIVATE_KEY_PATH is the same
          silent-failure footgun.
        """
        gh = self.github_app
        if gh.is_partially_configured:
            set_vars = [
                name for name, val in [
                    ("GITHUB_APP_ID", gh.id),
                    ("GITHUB_APP_PRIVATE_KEY_PATH", gh.private_key_path),
                    ("GITHUB_APP_INSTALLATION_ID", gh.installation_id),
                ] if val
            ]
            missing = [
                name for name, val in [
                    ("GITHUB_APP_ID", gh.id),
                    ("GITHUB_APP_PRIVATE_KEY_PATH", gh.private_key_path),
                    ("GITHUB_APP_INSTALLATION_ID", gh.installation_id),
                ] if not val
            ]
            raise RuntimeError(
                "GitHub App is partially configured: set "
                f"{set_vars} but missing {missing}. "
                "Set all three (to enable update_core_builder) or none "
                "(to disable it). A partial configuration silently disables "
                "the service and hangs update_core_builder at runtime."
            )
        if gh.is_configured:
            import os
            if not os.path.isfile(gh.private_key_path):
                raise RuntimeError(
                    f"GITHUB_APP_PRIVATE_KEY_PATH={gh.private_key_path} does not point "
                    "to a readable file. The GitHub App key must exist at this path "
                    "when the backend starts. Fix the path or unset all three "
                    "GITHUB_APP_* variables to disable the feature."
                )


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance.

    Call this function to access configuration throughout the application.

    Example:
        from druppie.core.config import get_settings

        settings = get_settings()
        db_url = settings.database.url
    """
    settings = Settings()
    settings.log_config()
    return settings


# Convenience aliases for common settings access patterns
def get_database_url() -> str:
    """Get database URL."""
    return get_settings().database.url


def is_dev_mode() -> bool:
    """Check if running in development mode."""
    return get_settings().api.dev_mode


def get_workspace_root() -> Path:
    """Get workspace root directory."""
    return get_settings().workspace.root


# =============================================================================
# SANDBOX AGENT CONSTANTS
# =============================================================================

# Default sandbox agent names - single source of truth
DEFAULT_SANDBOX_AGENT = "druppie-builder"
DEFAULT_SANDBOX_TESTER_AGENT = "druppie-tester"
