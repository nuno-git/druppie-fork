"""Repository for model override CRUD operations."""

from uuid import UUID

from druppie.db.models.model_override import ModelOverride

from .base import BaseRepository


class ModelOverrideRepository(BaseRepository):

    def get_all(self) -> list[ModelOverride]:
        return self.db.query(ModelOverride).order_by(ModelOverride.target_type, ModelOverride.target_id).all()

    def get_agent_overrides(self) -> list[ModelOverride]:
        return (
            self.db.query(ModelOverride)
            .filter(ModelOverride.target_type == "agent")
            .order_by(ModelOverride.target_id)
            .all()
        )

    def get_translation_override(self) -> ModelOverride | None:
        return (
            self.db.query(ModelOverride)
            .filter(ModelOverride.target_type == "translation", ModelOverride.target_id == "translation")
            .first()
        )

    def get_by_target(self, target_type: str, target_id: str) -> ModelOverride | None:
        return (
            self.db.query(ModelOverride)
            .filter(ModelOverride.target_type == target_type, ModelOverride.target_id == target_id)
            .first()
        )

    def upsert(
        self,
        target_type: str,
        target_id: str,
        provider: str,
        model: str,
        updated_by: UUID | None = None,
        fallback_provider: str | None = None,
        fallback_model: str | None = None,
    ) -> ModelOverride:
        existing = self.get_by_target(target_type, target_id)
        if existing:
            existing.provider = provider
            existing.model = model
            existing.fallback_provider = fallback_provider
            existing.fallback_model = fallback_model
            existing.enabled = True
            existing.updated_by = updated_by
            self.db.flush()
            return existing

        override = ModelOverride(
            target_type=target_type,
            target_id=target_id,
            provider=provider,
            model=model,
            fallback_provider=fallback_provider,
            fallback_model=fallback_model,
            enabled=True,
            updated_by=updated_by,
        )
        self.db.add(override)
        self.db.flush()
        return override

    def delete_by_target(self, target_type: str, target_id: str) -> bool:
        row = self.get_by_target(target_type, target_id)
        if row:
            self.db.delete(row)
            self.db.flush()
            return True
        return False
