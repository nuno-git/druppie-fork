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
from sqlalchemy import create_engine
from sqlalchemy.orm import Session as DbSession, sessionmaker

from druppie.db.models import Base, JobDefinition, JobRun
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

# SQLite/PG-UUID compatibility comes from the shared autouse fixture in
# conftest.py.

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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


def _make_definition(repo: JobRepository, job_id: str = "test_job"):
    return repo.create_definition(
        job_id=job_id,
        name="Test Job",
        description="A test job",
        schedule="0 0 * * *",
        agent_id="developer",
        prompt="Do the thing",
        approval_required=False,
        required_role=None,
        enabled=True,
        yaml_path="/tmp/test.yaml",
    )


# ---------------------------------------------------------------------------
# JobRepository — definitions
# ---------------------------------------------------------------------------


class TestJobRepositoryDefinitions:
    def test_create_definition_no_extra_fields(self, job_repo: JobRepository):
        definition = _make_definition(job_repo)
        job_repo.commit()

        assert definition.job_id == "test_job"
        assert definition.name == "Test Job"

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
        definition = _make_definition(job_repo, job_id="to_delete")
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
            "agent_id: summarizer\nprompt: Say hello\nenabled: true\n"
        )

        with patch("druppie.services.job_service.DEFAULT_JOBS_DIR", str(defs_dir)):
            result = job_service.load_definitions_from_yaml(str(defs_dir))

        assert result.total == 1
        item = result.items[0]
        assert item.job_id == "hello"

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
            "agent_id: summarizer\nprompt: New\nenabled: true\n"
        )

        with patch("druppie.services.job_service.DEFAULT_JOBS_DIR", str(defs_dir)):
            result = job_service.load_definitions_from_yaml(str(defs_dir))

        assert result.total == 1
        assert result.items[0].name == "New Name"

    def test_set_enabled_pauses_and_resumes(self, job_service: JobService):
        definition = job_service.job_repo.create_definition(
            job_id="toggle", name="Toggle", description=None,
            schedule="0 0 * * *", agent_id="summarizer", prompt="Hi",
            approval_required=False, required_role=None, enabled=True,
            yaml_path=None,
        )
        job_service.job_repo.commit()

        paused = job_service.set_enabled(definition.id, False)
        assert paused.enabled is False

        resumed = job_service.set_enabled(definition.id, True)
        assert resumed.enabled is True

    def test_set_enabled_unknown_definition_raises(self, job_service: JobService):
        from druppie.api.errors import NotFoundError

        with pytest.raises(NotFoundError):
            job_service.set_enabled(uuid.uuid4(), False)

    def test_pause_survives_yaml_resync(self, job_service: JobService, tmp_path):
        """A user pause must not be clobbered when YAML re-syncs on startup."""
        defs_dir = tmp_path / "defs"
        defs_dir.mkdir()
        (defs_dir / "p.yaml").write_text(
            "id: p\nname: P\nschedule: '0 0 * * *'\n"
            "agent_id: summarizer\nprompt: Do\nenabled: true\n"
        )
        with patch("druppie.services.job_service.DEFAULT_JOBS_DIR", str(defs_dir)):
            created = job_service.load_definitions_from_yaml(str(defs_dir))

        # User pauses the schedule.
        job_service.set_enabled(created.items[0].id, False)

        # A redeploy re-runs the YAML sync; the file still says enabled: true.
        with patch("druppie.services.job_service.DEFAULT_JOBS_DIR", str(defs_dir)):
            result = job_service.load_definitions_from_yaml(str(defs_dir))

        assert result.items[0].enabled is False  # pause preserved

    def test_env_override_still_wins_over_pause(self, job_service: JobService, tmp_path):
        """The ops kill-switch JOB_<ID>_ENABLED stays authoritative."""
        defs_dir = tmp_path / "defs"
        defs_dir.mkdir()
        (defs_dir / "e.yaml").write_text(
            "id: e\nname: E\nschedule: '0 0 * * *'\n"
            "agent_id: summarizer\nprompt: Do\nenabled: true\n"
        )
        with patch("druppie.services.job_service.DEFAULT_JOBS_DIR", str(defs_dir)):
            created = job_service.load_definitions_from_yaml(str(defs_dir))
        job_service.set_enabled(created.items[0].id, False)

        with patch("druppie.services.job_service.DEFAULT_JOBS_DIR", str(defs_dir)), \
                patch.dict(os.environ, {"JOB_E_ENABLED": "true"}):
            result = job_service.load_definitions_from_yaml(str(defs_dir))

        assert result.items[0].enabled is True  # env override re-enables

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

    def test_load_definitions_from_yaml_skips_invalid_cron(self, job_service: JobService, tmp_path):
        defs_dir = tmp_path / "defs"
        defs_dir.mkdir()
        (defs_dir / "bad_cron.yaml").write_text(
            "id: bad_cron\nname: Bad Cron\nschedule: 'not a cron at all'\n"
            "agent_id: summarizer\nprompt: Do it\nenabled: true\n"
        )

        with patch("druppie.services.job_service.DEFAULT_JOBS_DIR", str(defs_dir)):
            result = job_service.load_definitions_from_yaml(str(defs_dir))

        assert result.total == 0

    def test_load_definitions_from_yaml_skips_impossible_cron(self, job_service: JobService, tmp_path):
        # "0 0 31 2 *" = Feb 31: syntactically valid but an impossible date.
        # croniter constructs it fine, so it must be rejected via get_next(),
        # otherwise the scheduler raises CroniterBadDateError on every tick.
        defs_dir = tmp_path / "defs"
        defs_dir.mkdir()
        (defs_dir / "impossible_cron.yaml").write_text(
            "id: impossible_cron\nname: Impossible Cron\nschedule: '0 0 31 2 *'\n"
            "agent_id: summarizer\nprompt: Do it\nenabled: true\n"
        )

        with patch("druppie.services.job_service.DEFAULT_JOBS_DIR", str(defs_dir)):
            result = job_service.load_definitions_from_yaml(str(defs_dir))

        assert result.total == 0

    def test_load_definitions_from_yaml_skips_invalid_agent(self, job_service: JobService, tmp_path):
        defs_dir = tmp_path / "defs"
        defs_dir.mkdir()
        (defs_dir / "bad_agent.yaml").write_text(
            "id: bad_agent\nname: Bad Agent\nschedule: '0 0 * * *'\n"
            "agent_id: nonexistent_agent\nprompt: Do it\nenabled: true\n"
        )

        with patch("druppie.services.job_service.DEFAULT_JOBS_DIR", str(defs_dir)):
            result = job_service.load_definitions_from_yaml(str(defs_dir))

        assert result.total == 0

    def test_load_definitions_from_yaml_skips_missing_name(self, job_service: JobService, tmp_path):
        defs_dir = tmp_path / "defs"
        defs_dir.mkdir()
        (defs_dir / "no_name.yaml").write_text(
            "id: no_name\nschedule: '0 0 * * *'\n"
            "agent_id: summarizer\nprompt: Do it\nenabled: true\n"
        )

        with patch("druppie.services.job_service.DEFAULT_JOBS_DIR", str(defs_dir)):
            result = job_service.load_definitions_from_yaml(str(defs_dir))

        assert result.total == 0

    def test_load_definitions_from_yaml_skips_missing_prompt(self, job_service: JobService, tmp_path):
        defs_dir = tmp_path / "defs"
        defs_dir.mkdir()
        (defs_dir / "no_prompt.yaml").write_text(
            "id: no_prompt\nname: No Prompt\nschedule: '0 0 * * *'\n"
            "agent_id: summarizer\nenabled: true\n"
        )

        with patch("druppie.services.job_service.DEFAULT_JOBS_DIR", str(defs_dir)):
            result = job_service.load_definitions_from_yaml(str(defs_dir))

        assert result.total == 0


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
    def test_definition_detail_serializes(self):
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
            enabled=True,
            yaml_path="/tmp/j.yaml",
            last_triggered_at=None,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
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
    def test_job_definition_to_dict(self, db_session: DbSession):
        definition = JobDefinitionModel(
            job_id="dict_test",
            name="Dict Test",
            schedule="0 0 * * *",
            agent_id="dev",
            prompt="prompt",
            enabled=True,
        )
        db_session.add(definition)
        db_session.commit()

        d = definition.to_dict()
        assert d["job_id"] == "dict_test"

    def test_job_definition_to_dict_no_extra(self, db_session: DbSession):
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
        assert "config" not in d

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


# ---------------------------------------------------------------------------
# JobService — per-environment env overrides (JOB_<ID>_ENABLED / _SCHEDULE)
# ---------------------------------------------------------------------------


def _write_job_yaml(defs_dir, job_id: str = "ovr_job", enabled: str = "false"):
    (defs_dir / f"{job_id}.yaml").write_text(
        f"id: {job_id}\nname: Override Job\nschedule: '*/20 * * * *'\n"
        f"agent_id: summarizer\nprompt: Do it\nenabled: {enabled}\n"
    )


class TestJobEnvOverrides:
    def test_enabled_override_turns_job_on(self, job_service: JobService, tmp_path, monkeypatch):
        defs_dir = tmp_path / "defs"
        defs_dir.mkdir()
        _write_job_yaml(defs_dir, enabled="false")
        monkeypatch.setenv("JOB_OVR_JOB_ENABLED", "true")

        result = job_service.load_definitions_from_yaml(str(defs_dir))

        assert result.total == 1
        assert result.items[0].enabled is True

    def test_enabled_override_turns_job_off(self, job_service: JobService, tmp_path, monkeypatch):
        defs_dir = tmp_path / "defs"
        defs_dir.mkdir()
        _write_job_yaml(defs_dir, enabled="true")
        monkeypatch.setenv("JOB_OVR_JOB_ENABLED", "false")

        result = job_service.load_definitions_from_yaml(str(defs_dir))

        assert result.items[0].enabled is False

    def test_enabled_override_applies_on_resync(self, job_service: JobService, tmp_path, monkeypatch):
        """The override must survive a YAML re-sync (which resets DB state)."""
        defs_dir = tmp_path / "defs"
        defs_dir.mkdir()
        _write_job_yaml(defs_dir, enabled="false")
        monkeypatch.setenv("JOB_OVR_JOB_ENABLED", "true")

        job_service.load_definitions_from_yaml(str(defs_dir))
        result = job_service.load_definitions_from_yaml(str(defs_dir))

        assert result.items[0].enabled is True

    def test_invalid_enabled_value_keeps_yaml(self, job_service: JobService, tmp_path, monkeypatch):
        defs_dir = tmp_path / "defs"
        defs_dir.mkdir()
        _write_job_yaml(defs_dir, enabled="false")
        monkeypatch.setenv("JOB_OVR_JOB_ENABLED", "banana")

        result = job_service.load_definitions_from_yaml(str(defs_dir))

        assert result.items[0].enabled is False

    def test_schedule_override(self, job_service: JobService, tmp_path, monkeypatch):
        defs_dir = tmp_path / "defs"
        defs_dir.mkdir()
        _write_job_yaml(defs_dir)
        monkeypatch.setenv("JOB_OVR_JOB_SCHEDULE", "0 6 * * *")

        result = job_service.load_definitions_from_yaml(str(defs_dir))

        assert result.items[0].schedule == "0 6 * * *"

    def test_invalid_schedule_override_skips_job(self, job_service: JobService, tmp_path, monkeypatch):
        """An overridden schedule is validated like a YAML one."""
        defs_dir = tmp_path / "defs"
        defs_dir.mkdir()
        _write_job_yaml(defs_dir)
        monkeypatch.setenv("JOB_OVR_JOB_SCHEDULE", "not a cron")

        result = job_service.load_definitions_from_yaml(str(defs_dir))

        assert result.total == 0

    def test_override_ignores_other_jobs(self, job_service: JobService, tmp_path, monkeypatch):
        defs_dir = tmp_path / "defs"
        defs_dir.mkdir()
        _write_job_yaml(defs_dir, job_id="ovr_job", enabled="false")
        _write_job_yaml(defs_dir, job_id="other_job", enabled="false")
        monkeypatch.setenv("JOB_OVR_JOB_ENABLED", "true")

        result = job_service.load_definitions_from_yaml(str(defs_dir))

        by_id = {d.job_id: d for d in result.items}
        assert by_id["ovr_job"].enabled is True
        assert by_id["other_job"].enabled is False


# ---------------------------------------------------------------------------
# JobRepository — usage aggregation (cost per run)
# ---------------------------------------------------------------------------


def _add_llm_call(db, session_id, **kwargs):
    from druppie.db.models.llm_call import LlmCall

    call = LlmCall(
        session_id=session_id,
        provider=kwargs.get("provider", "llmkube"),
        model=kwargs.get("model", "Qwen/Qwen3.6-27B"),
        prompt_tokens=kwargs.get("prompt_tokens", 100),
        completion_tokens=kwargs.get("completion_tokens", 10),
        total_tokens=kwargs.get("total_tokens", 110),
        duration_ms=kwargs.get("duration_ms", 500),
        fallback_used=kwargs.get("fallback_used", False),
    )
    db.add(call)
    return call


class TestJobRunUsage:
    def test_no_session_returns_none(self, job_repo: JobRepository):
        assert job_repo.get_job_run_usage(None) is None

    def test_no_llm_calls_returns_none(self, job_repo: JobRepository):
        assert job_repo.get_job_run_usage(uuid.uuid4()) is None

    def test_aggregates_calls_of_the_session_only(
        self, job_repo: JobRepository, db_session: DbSession
    ):
        session_id = uuid.uuid4()
        _add_llm_call(db_session, session_id, prompt_tokens=100, completion_tokens=10, total_tokens=110)
        _add_llm_call(
            db_session, session_id,
            provider="zai", model="glm-4.7",
            prompt_tokens=200, completion_tokens=20, total_tokens=220,
            duration_ms=700, fallback_used=True,
        )
        _add_llm_call(db_session, uuid.uuid4(), prompt_tokens=999)  # other session
        db_session.commit()

        usage = job_repo.get_job_run_usage(session_id)

        assert usage is not None
        assert usage.llm_calls == 2
        assert usage.prompt_tokens == 300
        assert usage.completion_tokens == 30
        assert usage.total_tokens == 330
        assert usage.duration_ms == 1200
        assert usage.fallback_calls == 1
        assert sorted(usage.models) == ["llmkube/Qwen/Qwen3.6-27B", "zai/glm-4.7"]

    def test_job_run_detail_includes_usage(
        self, job_repo: JobRepository, db_session: DbSession
    ):
        definition = _make_definition(job_repo)
        job_repo.commit()
        session_id = uuid.uuid4()
        run = job_repo.create_job_run(
            job_definition_id=definition.id,
            session_id=session_id,
            trigger_type="scheduled",
            status="completed",
        )
        _add_llm_call(db_session, session_id)
        db_session.commit()

        detail = job_repo.to_job_run_detail(run)

        assert detail.usage is not None
        assert detail.usage.llm_calls == 1
        assert detail.usage.total_tokens == 110
