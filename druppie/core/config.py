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


class MCPSettings(BaseSettings):
    """MCP microservice configuration."""

    model_config = SettingsConfigDict(env_prefix="MCP_")

    coding_url: str = Field(
        default="http://mcp-coding:9001",
        description="Coding MCP server URL",
    )
    docker_url: str = Field(
        default="http://mcp-docker:9002",
        description="Docker MCP server URL",
    )
    filesearch_url: str = Field(
        default="http://mcp-filesearch:9004",
        description="Filesearch MCP server URL",
    )
    timeout: int = Field(
        default=300,
        description="MCP request timeout in seconds",
    )


class LanguageSettings(BaseSettings):
    """Language persistence and detection configuration."""

    model_config = SettingsConfigDict(env_prefix="LANGUAGE_")

    fallback_language: str = Field(
        default="nl",
        alias="LANGUAGE_FALLBACK",
        description="Fallback language when detection fails (e.g., 'nl', 'en')",
    )
    lock_to_first_message: bool = Field(
        default=False,
        alias="LANGUAGE_LOCK_TO_FIRST_MESSAGE",
        description="Lock session to language detected in first user message",
    )
    allow_language_switch: bool = Field(
        default=True,
        alias="LANGUAGE_ALLOW_SWITCH",
        description="Allow users to explicitly switch languages during session",
    )
    markdown_language: str = Field(
        default="nl",
        alias="LANGUAGE_MARKDOWN",
        description="Language used for agent-generated Markdown content",
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

    model_config = SettingsConfigDict(env_prefix="API_")

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
    llm: LLMSettings = Field(default_factory=LLMSettings)
    mcp: MCPSettings = Field(default_factory=MCPSettings)
    language: LanguageSettings = Field(default_factory=LanguageSettings)
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
            language_fallback=self.language.fallback_language,
            language_lock=self.language.lock_to_first_message,
            language_allow_switch=self.language.allow_language_switch,
            language_markdown=self.language.markdown_language,
        )

        # Security warnings for missing credentials
        if not self.gitea.is_configured:
            logger.warning(
                "gitea_credentials_not_configured",
                message="GITEA_ADMIN_PASSWORD or GITEA_TOKEN not set - Gitea operations will fail",
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


def get_fallback_language() -> str:
    """Get configured fallback language."""
    return get_settings().language.fallback_language


def should_lock_to_first_message() -> bool:
    """Check if language should be locked to first message."""
    return get_settings().language.lock_to_first_message


def allow_language_switch() -> bool:
    """Check if language switching is allowed."""
    return get_settings().language.allow_language_switch
