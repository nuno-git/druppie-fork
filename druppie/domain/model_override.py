"""Domain models for model management and runtime overrides."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class ModelOverrideSummary(BaseModel):
    id: UUID
    target_type: str
    target_id: str
    provider: str
    model: str
    fallback_provider: str | None = None
    fallback_model: str | None = None
    enabled: bool
    updated_at: datetime | None = None


class ModelOverrideDetail(ModelOverrideSummary):
    updated_by: UUID | None = None
    created_at: datetime | None = None


class ProviderStatus(BaseModel):
    provider: str
    api_key_env: str
    api_key_configured: bool
    default_model: str
    base_url: str
    available_models: list[str] = []


class AgentModelInfo(BaseModel):
    agent_id: str
    agent_name: str
    category: str
    profile: str
    resolved_provider: str
    resolved_model: str | None
    source: str  # "db_override" | "override" | "profile" | "global_default"
    override: ModelOverrideSummary | None = None
    override_unavailable: bool = False
    suggested_fallback: str | None = None
    fallback_is_custom: bool = False
    fallback_unavailable: bool = False


class TranslationModelInfo(BaseModel):
    provider: str
    model: str
    source: str  # "db_override" | "env" | "legacy" | "fallback"
    override: ModelOverrideSummary | None = None
    override_unavailable: bool = False
    suggested_fallback: str | None = None
    fallback_is_custom: bool = False
    fallback_unavailable: bool = False


class ModelManagementView(BaseModel):
    agents: list[AgentModelInfo]
    translation: TranslationModelInfo
    providers: list[ProviderStatus]
    overrides: list[ModelOverrideSummary]


class LocalServiceStatus(BaseModel):
    replicas: int
    ready: bool


class LocalModelStatus(BaseModel):
    current_mode: str | None = None
    switching: str | None = None
    active_models: list[str] = []
    available_models: list[str] = []
    services: dict[str, LocalServiceStatus] = {}
    loading_progress: dict | None = None


class LocalServiceLogs(BaseModel):
    pod: str | None = None
    ready: bool = False
    logs: list[str] = []
    error: str | None = None


class LocalModelLogs(BaseModel):
    services: dict[str, LocalServiceLogs] = {}
