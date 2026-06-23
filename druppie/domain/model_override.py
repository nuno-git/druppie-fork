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


class TranslationModelInfo(BaseModel):
    provider: str
    model: str
    source: str  # "db_override" | "env" | "legacy" | "fallback"
    override: ModelOverrideSummary | None = None


class ModelManagementView(BaseModel):
    agents: list[AgentModelInfo]
    translation: TranslationModelInfo
    providers: list[ProviderStatus]
    overrides: list[ModelOverrideSummary]
