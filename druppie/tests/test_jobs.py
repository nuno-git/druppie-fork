"""Tests for the cron job pipeline.

Covers JobRepository, JobService, JobScheduler, and domain model
serialization using an in-memory SQLite database with a UUID shim.
"""
from __future__ import annotations

import os
import tempfile
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import String, TypeDecorator, create_engine
from sqlalchemy.orm import Session as DbSession, sessionmaker

from druppie.db.models import Base, JobDefinition, JobDefinitionConfig, JobRun
from druppie.db.models.job import JobDefinition as JobDefinitionModel, JobRun as JobRunModel
from druppie.domain.job import (
    JobDefinitionDetail,
    JobDefinitionList,
    JobDefinitionSummary,
    JobRunDetail,
    JobRunList,
)
from druppie.repositories.job_repository import JobRepository
from druppie.services.job_service import JobService

# ---------------------------------------------------------------------------
# SQLite / PostgreSQL-UUID compatibility (same shim as test_assertions.py)
# ---------------------------------------------------------------------------

from sqlalchemy.dialects.postgresql import UUID as PG_UUID  # noqa: E402


class _SQLiteUUID(TypeDecorator):
    """Store Python uuid.UUID as a String(36) in SQLite."""

    impl = String(36)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None:
            return str(value)
        return value

    def process_result_value(self, value, dialect):
        if value is not None:
            return uuid.UUID(value) if not isinstance(value, uuid.UUID) else value
        return value


_patched = False


def _patch_uuid_columns_for_sqlite(base):
    global _patched
    if _patched:
        return
    for table in base.metadata.tables.values():
        for col in table.columns:
            if isinstance(col.type, PG_UUID):
                col.type = _SQLiteUUID()
    _patched = True


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _patch_uuid():
    _patch_uuid_columns_for_sqlite(Base)
    yield


@pytest.fixture()
def db_session():
    """Create an in-memory SQLite DB, create all tables, yield a session."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autoflush=False)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def job_repo(db_session: DbSession) -> JobRepository:
    return JobRepository(db_session)


@pytest.fixture()
def job_service(db_session: DbSession) -> JobService:
    job_repo = JobRepository(db_session)
    from druppie.repositories import SessionRepository, ExecutionRepository

    session_repo = SessionRepository(db_session)
    execution_repo = ExecutionRepository(db_session)
    return JobService(job_repo, session_repo, execution_repo)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_definition(repo: JobRepository, job_id: str = "test_job", config: dict | None = None):
    return repo.create_definition(
        job_id=job_id,
        name="Test Job",
        description="A test job",
        schedule="0 0 * * *",
        agent_id="developer",
        prompt="Do the thing",
        approval_required=False,
        required_role=None,
        config=config,
        enabled=True,
        yaml_path="/tmp/test.yaml",
    )


# ---------------------------------------------------------------------------
# JobRepository — definitions
# ---------------------------------------------------------------------------


class TestJobRepositoryDefinitions:
    def test_create_definition_without_config(self, job_repo: JobRepository):
        definition = _make_definition(job_repo, config=None)
        job_repo.commit()

        assert definition.job_id == "test_job"
        assert definition.name == "Test Job"
        assert definition.configs == []

    def test_create_definition_with_config_normalizes_rows(self, job_repo: JobRepository):
        definition = _make_definition(job_repo, config={"dry_run": False, "timeout": 30})
        job_repo.commit()

        assert len(definition.configs) == 2
        keys = {c.config_key for c in definition.configs}
        assert keys == {"dry_run", "timeout"}
        values = {c.config_key: c.config_value for c in definition.configs}
        assert values["dry_run"] == "False"
        assert values["timeout"] == "30"

    def test_get_definition_by_job_id_found(self, job_repo: JobRepository):
        _make_definition(job_repo, job_id="find_me")
        job_repo.commit()

        found = job_repo.get_definition_by_job_id("find_me")
        assert found is not None
        assert found.job_id == "find_me"

    def test_get_definition_by_job_id_not_found(self, job_repo: JobRepository):
        assert job_repo.get_definition_by_job_id("missing") is None

    def test_list_definitions_returns_all(self, job_repo: JobRepository):
        _make_definition(job_repo, job_id="job_a")
        _make_definition(job_repo, job_id="job_b")
        job_repo.commit()

        result = job_repo.list_definitions()
        assert result.total == 2
        assert {d.job_id for d in result.items} == {"job_a", "job_b"}

    def test_delete_definition_by_job_id(self, job_repo: JobRepository):
        _make_definition(job_repo, job_id="to_delete")
        job_repo.commit()

        job_repo.delete_definition_by_job_id("to_delete")
        job_repo.commit()

        assert job_repo.get_definition_by_job_id("to_delete") is None

    def test_delete_definition_removes_parent(self, job_repo: JobRepository):
        definition = _make_definition(job_repo, job_id="to_delete", config={"key": "val"})
        job_repo.commit()

        job_repo.delete_definition_by_job_id("to_delete")
        job_repo.commit()

        assert job_repo.get_definition_by_job_id("to_delete") is None


# ---------------------------------------------------------------------------
# JobRepository — job runs
# ---------------------------------------------------------------------------


class TestJobRepositoryJobRuns:
    def test_create_job_run(self, job_repo: JobRepository):
        definition = _make_definition(job_repo)
        job_repo.commit()

        run = job_repo.create_job_run(
            job_definition_id=definition.id,
            session_id=None,
            trigger_type="manual",
            status="pending",
        )
        job_repo.commit()

        assert run.status == "pending"
        assert run.job_definition_id == definition.id

    def test_get_job_run_by_agent_run_id(self, job_repo: JobRepository):
        definition = _make_definition(job_repo)
        job_repo.commit()
        agent_run_id = uuid.uuid4()

        run = job_repo.create_job_run(
            job_definition_id=definition.id,
            session_id=None,
            trigger_type="scheduled",
            status="running",
        )
        job_repo.set_job_run_session(run.id, session_id=uuid.uuid4(), agent_run_id=agent_run_id)
        job_repo.commit()

        found = job_repo.get_job_run_by_agent_run_id(agent_run_id)
        assert found is not None
        assert found.id == run.id

    def test_update_job_run_status(self, job_repo: JobRepository):
        definition = _make_definition(job_repo)
        job_repo.commit()
        run = job_repo.create_job_run(
            job_definition_id=definition.id,
            session_id=None,
            trigger_type="manual",
            status="pending",
        )
        job_repo.commit()

        job_repo.update_job_run_status(run.id, "completed", error_message="none", logs="done")
        job_repo.commit()

        refreshed = job_repo.get_job_run_by_id(run.id)
        assert refreshed.status == "completed"
        assert refreshed.completed_at is not None

    def test_mark_job_run_finalized_by_agent_run_id(self, job_repo: JobRepository):
        definition = _make_definition(job_repo)
        job_repo.commit()
        agent_run_id = uuid.uuid4()
        run = job_repo.create_job_run(
            job_definition_id=definition.id,
            session_id=None,
            trigger_type="scheduled",
            status="running",
        )
        job_repo.set_job_run_session(run.id, session_id=uuid.uuid4(), agent_run_id=agent_run_id)
        job_repo.commit()

        job_repo.mark_job_run_finalized_by_agent_run_id(agent_run_id, "failed", error_message="boom")
        job_repo.commit()

        refreshed = job_repo.get_job_run_by_id(run.id)
        assert refreshed.status == "failed"
        assert refreshed.error_message == "boom"
        assert refreshed.completed_at is not None

    def test_list_job_runs_pagination(self, job_repo: JobRepository):
        definition = _make_definition(job_repo)
        job_repo.commit()
        for _ in range(5):
            job_repo.create_job_run(
                job_definition_id=definition.id,
                session_id=None,
                trigger_type="scheduled",
                status="pending",
            )
        job_repo.commit()

        result = job_repo.list_job_runs(page=1, limit=3)
        assert result.total == 5
        assert len(result.items) == 3
        assert result.page == 1
        assert result.limit == 3


# ---------------------------------------------------------------------------
# JobRepository — claim_job_trigger (compare-and-swap)
# ---------------------------------------------------------------------------


class TestJobRepositoryClaimTrigger:
    def test_claim_wins_when_never_triggered(self, job_repo: JobRepository):
        definition = _make_definition(job_repo)
        job_repo.commit()

        now = datetime.now(timezone.utc)
        won = job_repo.claim_job_trigger(definition.id, last_scheduled=now, now=now)
        assert won is True

        refreshed = job_repo.get_definition_by_id(definition.id)
        assert refreshed.last_triggered_at is not None

    def test_claim_loses_when_already_triggered(self, job_repo: JobRepository):
        definition = _make_definition(job_repo)
        job_repo.db.flush()
        definition.last_triggered_at = datetime(2025, 1, 1, 12, 0, 0)
        job_repo.db.flush()
        job_repo.commit()

        last_scheduled = datetime(2025, 1, 1, 12, 0, 0)
        now = datetime(2025, 1, 1, 12, 0, 0)
        won = job_repo.claim_job_trigger(definition.id, last_scheduled=last_scheduled, now=now)
        assert won is False

    def test_claim_wins_when_last_triggered_is_older(self, job_repo: JobRepository):
        definition = _make_definition(job_repo)
        definition.last_triggered_at = datetime(2020, 1, 1)
        job_repo.commit()

        now = datetime.utcnow()
        won = job_repo.claim_job_trigger(
            definition.id, last_scheduled=now, now=now
        )
        assert won is True


# ---------------------------------------------------------------------------
# JobService — YAML loading
# ---------------------------------------------------------------------------


class TestJobServiceYamlLoading:
    def test_load_definitions_from_yaml_creates_new(self, job_service: JobService, tmp_path):
        defs_dir = tmp_path / "defs"
        defs_dir.mkdir()
        (defs_dir / "hello.yaml").write_text(
            "id: hello\nname: Hello Job\nschedule: '0 0 * * *'\n"
            "agent_id: summarizer\nprompt: Say hello\nconfig:\n  dry_run: true\nenabled: true\n"
        )

        with patch("druppie.services.job_service.DEFAULT_JOBS_DIR", str(defs_dir)):
            result = job_service.load_definitions_from_yaml(str(defs_dir))

        assert result.total == 1
        item = result.items[0]
        assert item.job_id == "hello"
        assert item.config == {"dry_run": "True"}  # normalized via str(bool) -> "True"

    def test_load_definitions_from_yaml_updates_existing(self, job_service: JobService, tmp_path):
        defs_dir = tmp_path / "defs"
        defs_dir.mkdir()
        (defs_dir / "upd.yaml").write_text(
            "id: upd\nname: Old Name\nschedule: '0 0 * * *'\n"
            "agent_id: summarizer\nprompt: Old\nenabled: true\n"
        )

        with patch("druppie.services.job_service.DEFAULT_JOBS_DIR", str(defs_dir)):
            job_service.load_definitions_from_yaml(str(defs_dir))

        # Update the file
        (defs_dir / "upd.yaml").write_text(
            "id: upd\nname: New Name\nschedule: '0 0 * * *'\n"
            "agent_id: summarizer\nprompt: New\nconfig:\n  timeout: 42\nenabled: true\n"
        )

        with patch("druppie.services.job_service.DEFAULT_JOBS_DIR", str(defs_dir)):
            result = job_service.load_definitions_from_yaml(str(defs_dir))

        assert result.total == 1
        assert result.items[0].name == "New Name"
        assert result.items[0].config == {"timeout": "42"}

    def test_load_definitions_removes_orphans(self, job_service: JobService, tmp_path):
        defs_dir = tmp_path / "defs"
        defs_dir.mkdir()
        (defs_dir / "keep.yaml").write_text(
            "id: keep\nname: Keep\nschedule: '0 0 * * *'\n"
            "agent_id: summarizer\nprompt: Keep\nenabled: true\n"
        )
        (defs_dir / "orphan.yaml").write_text(
            "id: orphan\nname: Orphan\nschedule: '0 0 * * *'\n"
            "agent_id: summarizer\nprompt: Orphan\nenabled: true\n"
        )

        with patch("druppie.services.job_service.DEFAULT_JOBS_DIR", str(defs_dir)):
            job_service.load_definitions_from_yaml(str(defs_dir))

        # Remove orphan.yaml
        (defs_dir / "orphan.yaml").unlink()

        with patch("druppie.services.job_service.DEFAULT_JOBS_DIR", str(defs_dir)):
            result = job_service.load_definitions_from_yaml(str(defs_dir))

        assert result.total == 1
        assert result.items[0].job_id == "keep"


# ---------------------------------------------------------------------------
# JobScheduler — should_run logic
# ---------------------------------------------------------------------------


class TestJobSchedulerShouldRun:
    def test_no_previous_trigger_runs_immediately(self):
        from druppie.services.job_service import JobScheduler

        mock_factory = MagicMock()
        scheduler = JobScheduler(mock_factory)

        mock_definition = MagicMock()
        mock_definition.schedule = "0 * * * *"  # hourly
        mock_definition.last_triggered_at = None
        mock_definition.enabled = True

        # Patch croniter to avoid heavy dependency in unit tests
        fake_prev = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
        with patch("druppie.services.job_service.croniter") as mock_cron:
            mock_cron.return_value.get_prev.return_value = fake_prev
            should_run, last_scheduled = scheduler._should_run(mock_definition, datetime.now(timezone.utc))

        assert should_run is True
        assert last_scheduled == fake_prev

    def test_already_triggered_after_scheduled_does_not_run(self):
        from druppie.services.job_service import JobScheduler

        mock_factory = MagicMock()
        scheduler = JobScheduler(mock_factory)

        fake_prev = datetime(2024, 1, 1, 11, 0, tzinfo=timezone.utc)
        mock_definition = MagicMock()
        mock_definition.schedule = "0 * * * *"
        mock_definition.last_triggered_at = datetime(2024, 1, 1, 12, 5, tzinfo=timezone.utc)
        mock_definition.enabled = True

        with patch("druppie.services.job_service.croniter") as mock_cron:
            mock_cron.return_value.get_prev.return_value = fake_prev
            should_run, last_scheduled = scheduler._should_run(mock_definition, datetime.now(timezone.utc))

        assert should_run is False
        assert last_scheduled == fake_prev

    def test_triggered_before_scheduled_runs(self):
        from druppie.services.job_service import JobScheduler

        mock_factory = MagicMock()
        scheduler = JobScheduler(mock_factory)

        fake_prev = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
        mock_definition = MagicMock()
        mock_definition.schedule = "0 * * * *"
        mock_definition.last_triggered_at = datetime(2024, 1, 1, 11, 30, tzinfo=timezone.utc)
        mock_definition.enabled = True

        with patch("druppie.services.job_service.croniter") as mock_cron:
            mock_cron.return_value.get_prev.return_value = fake_prev
            should_run, last_scheduled = scheduler._should_run(mock_definition, datetime.now(timezone.utc))

        assert should_run is True
        assert last_scheduled == fake_prev


# ---------------------------------------------------------------------------
# Domain models
# ---------------------------------------------------------------------------


class TestJobDomainModels:
    def test_definition_detail_serializes_config(self):
        detail = JobDefinitionDetail(
            id=uuid.uuid4(),
            job_id="my_job",
            name="My Job",
            description="Desc",
            schedule="0 0 * * *",
            agent_id="dev",
            approval_required=False,
            required_role=None,
            prompt="Do it",
            config={"dry_run": "true"},
            enabled=True,
            yaml_path="/tmp/j.yaml",
            last_triggered_at=None,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        assert detail.config == {"dry_run": "true"}
        assert detail.job_id == "my_job"

    def test_job_run_list_pagination_defaults(self):
        run = JobRunDetail(
            id=uuid.uuid4(),
            job_definition_id=uuid.uuid4(),
            session_id=None,
            agent_run_id=None,
            trigger_type="manual",
            status="pending",
            logs=None,
            started_at=None,
            completed_at=None,
            created_at=datetime.now(timezone.utc),
        )
        jrl = JobRunList(items=[run], total=1, page=1, limit=20)
        assert jrl.total == 1
        assert jrl.page == 1


# ---------------------------------------------------------------------------
# to_dict round-trip
# ---------------------------------------------------------------------------


class TestJobModelToDict:
    def test_job_definition_to_dict_includes_config(self, db_session: DbSession):
        definition = JobDefinitionModel(
            job_id="dict_test",
            name="Dict Test",
            schedule="0 0 * * *",
            agent_id="dev",
            prompt="prompt",
            enabled=True,
        )
        definition.configs = [
            JobDefinitionConfig(config_key="k1", config_value="v1"),
        ]
        db_session.add(definition)
        db_session.commit()

        d = definition.to_dict()
        assert d["job_id"] == "dict_test"
        assert d["config"] == {"k1": "v1"}

    def test_job_definition_to_dict_with_empty_config_returns_none(
        self, db_session: DbSession
    ):
        definition = JobDefinitionModel(
            job_id="empty_cfg",
            name="Empty",
            schedule="0 0 * * *",
            agent_id="dev",
            prompt="p",
            enabled=True,
        )
        db_session.add(definition)
        db_session.commit()

        d = definition.to_dict()
        assert d["config"] is None

    def test_job_run_to_dict(self, db_session: DbSession):
        run = JobRunModel(
            trigger_type="manual",
            status="completed",
        )
        db_session.add(run)
        db_session.commit()

        d = run.to_dict()
        assert d["trigger_type"] == "manual"
        assert d["status"] == "completed"
        assert "id" in d
