"""V2 Test Runner -- user-isolated test execution.

Each test gets its own user with their own sessions, projects, and repos.
Supports multi-HITL and multi-judge matrix execution.
"""
from __future__ import annotations

import logging
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import yaml
from sqlalchemy.orm import Session as DbSession

from druppie.db.models import BenchmarkRun, TestRun, TestRunTag
from druppie.testing.seed_ids import fixture_uuid
from druppie.testing.seed_loader import seed_fixture
from druppie.testing.seed_schema import SessionFixture
from druppie.testing.v2_assertions import AssertionResult, match_assertions
from druppie.testing.v2_schema import (
    EvalDefinition,
    EvalFile,
    HITLProfile,
    HITLProfilesFile,
    JudgeProfile,
    JudgeProfilesFile,
    TestDefinition,
    TestFile,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Profile Loader
# ---------------------------------------------------------------------------


class ProfileLoader:
    """Loads HITL and judge profiles from YAML files."""

    def __init__(self, profiles_dir: Path | None = None):
        self._profiles_dir = profiles_dir or (
            Path(__file__).resolve().parents[2] / "testing" / "profiles"
        )
        self._hitl: dict[str, HITLProfile] = {}
        self._judges: dict[str, JudgeProfile] = {}
        self._load()

    def _load(self) -> None:
        hitl_path = self._profiles_dir / "hitl.yaml"
        if hitl_path.exists():
            data = yaml.safe_load(hitl_path.read_text())
            parsed = HITLProfilesFile(**data)
            self._hitl = dict(parsed.profiles)

        judges_path = self._profiles_dir / "judges.yaml"
        if judges_path.exists():
            data = yaml.safe_load(judges_path.read_text())
            parsed = JudgeProfilesFile(**data)
            self._judges = dict(parsed.profiles)

    def get_hitl(self, name: str) -> HITLProfile:
        """Get an HITL profile by name. Returns a sensible default for 'default'."""
        if name == "default":
            return HITLProfile(
                model="claude-sonnet-4-6",
                provider="zai",
                prompt="You are a helpful user who gives clear, concise answers.",
            )
        if name not in self._hitl:
            raise KeyError(
                f"Unknown HITL profile: {name}. "
                f"Available: {sorted(self._hitl.keys())}"
            )
        return self._hitl[name]

    def get_judge(self, name: str) -> JudgeProfile:
        """Get a judge profile by name. Returns a sensible default for 'default'."""
        if name == "default":
            return JudgeProfile(model="claude-sonnet-4-6", provider="zai")
        if name not in self._judges:
            raise KeyError(
                f"Unknown judge profile: {name}. "
                f"Available: {sorted(self._judges.keys())}"
            )
        return self._judges[name]


# ---------------------------------------------------------------------------
# Eval Loader
# ---------------------------------------------------------------------------


class EvalLoader:
    """Loads eval definitions from YAML files."""

    def __init__(self, evals_dir: Path | None = None):
        self._evals_dir = evals_dir or (
            Path(__file__).resolve().parents[2] / "testing" / "evals"
        )
        self._evals: dict[str, EvalDefinition] = {}
        self._load()

    def _load(self) -> None:
        if not self._evals_dir.exists():
            logger.warning("Evals directory not found: %s", self._evals_dir)
            return
        for path in sorted(self._evals_dir.glob("*.yaml")):
            data = yaml.safe_load(path.read_text())
            parsed = EvalFile(**data)
            self._evals[parsed.eval.name] = parsed.eval

    def get(self, name: str) -> EvalDefinition:
        """Get an eval definition by name."""
        if name not in self._evals:
            raise KeyError(
                f"Unknown eval: {name}. Available: {sorted(self._evals.keys())}"
            )
        return self._evals[name]


# ---------------------------------------------------------------------------
# Session Loader
# ---------------------------------------------------------------------------


class SessionLoader:
    """Loads session definitions and resolves ``after:`` chains."""

    def __init__(self, sessions_dir: Path | None = None):
        self._sessions_dir = sessions_dir or (
            Path(__file__).resolve().parents[2] / "testing" / "seeds"
        )
        self._sessions: dict[str, SessionFixture] = {}
        self._load()

    def _load(self) -> None:
        if not self._sessions_dir.exists():
            logger.warning("Sessions directory not found: %s", self._sessions_dir)
            return
        for path in sorted(self._sessions_dir.glob("*.yaml")):
            data = yaml.safe_load(path.read_text())
            fixture = SessionFixture(**data)
            # Register by metadata.id
            self._sessions[fixture.metadata.id] = fixture

    def get(self, name: str) -> SessionFixture:
        """Get a session fixture by name (metadata.id)."""
        if name not in self._sessions:
            raise KeyError(
                f"Unknown session: {name}. "
                f"Available: {sorted(self._sessions.keys())}"
            )
        return self._sessions[name]

    def resolve_chain(self, session_names: list[str]) -> list[SessionFixture]:
        """Resolve session chains (``after:`` references) and return ordered list.

        Each session is included at most once, even if referenced multiple times.
        Parents are always seeded before their children.
        """
        resolved: list[SessionFixture] = []
        seen: set[str] = set()
        for name in session_names:
            self._resolve_one(name, resolved, seen)
        return resolved

    def _resolve_one(
        self,
        name: str,
        resolved: list[SessionFixture],
        seen: set[str],
    ) -> None:
        if name in seen:
            return
        seen.add(name)
        session = self.get(name)
        # Recurse into parent if this session chains via after:
        if session.metadata.after:
            self._resolve_one(session.metadata.after, resolved, seen)
        resolved.append(session)


# ---------------------------------------------------------------------------
# Test Run Result
# ---------------------------------------------------------------------------


@dataclass
class TestRunResult:
    """Result from running a single test with a specific HITL profile."""

    test_name: str
    test_user: str
    hitl_profile: str
    judge_profiles: list[str]
    assertion_results: list[AssertionResult]
    status: str
    duration_ms: int

    @property
    def passed(self) -> bool:
        return self.status == "passed"


# ---------------------------------------------------------------------------
# Test Runner
# ---------------------------------------------------------------------------


class TestRunner:
    """Main v2 test orchestrator.

    Creates isolated users per test, seeds sessions, resolves ``after:`` chains,
    and evaluates with assertions. Multi-HITL profile support with per-profile
    execution.
    """

    def __init__(
        self,
        db: DbSession,
        testing_dir: Path | None = None,
        gitea_url: str | None = None,
    ):
        self._db = db
        self._testing_dir = testing_dir or (
            Path(__file__).resolve().parents[2] / "testing"
        )
        self._gitea_url = gitea_url
        self._profiles = ProfileLoader(self._testing_dir / "profiles")
        self._evals = EvalLoader(self._testing_dir / "evals")
        self._sessions = SessionLoader(self._testing_dir / "seeds")

    def load_test(self, path: Path) -> TestDefinition:
        """Load a single test definition from a YAML file."""
        data = yaml.safe_load(path.read_text())
        return TestFile(**data).test

    def load_all_tests(
        self, tests_dir: Path | None = None
    ) -> list[tuple[Path, TestDefinition]]:
        """Load all test definitions from a directory."""
        d = tests_dir or self._testing_dir / "tests"
        return [(p, self.load_test(p)) for p in sorted(d.glob("*.yaml"))]

    def run_test(self, test: TestDefinition) -> list[TestRunResult]:
        """Run a test. Returns one TestRunResult per HITL profile."""
        results = []
        hitl_profiles = test.get_hitl_profiles()
        judge_profiles = test.get_judge_profiles()

        for hitl_name in hitl_profiles:
            result = self._run_single(test, hitl_name, judge_profiles)
            results.append(result)

        return results

    def _run_single(
        self,
        test: TestDefinition,
        hitl_name: str,
        judge_profiles: list[str],
    ) -> TestRunResult:
        """Run one execution of a test with a specific HITL profile."""
        start = time.time()
        timestamp = int(start)
        test_user = f"test-{test.name}-{hitl_name}-{timestamp}"

        # Create benchmark run
        git_commit, git_branch = _git_info()
        benchmark_run = BenchmarkRun(
            name=f"test-{test.name}",
            run_type="test",
            git_commit=git_commit,
            git_branch=git_branch,
            started_at=datetime.now(timezone.utc),
        )
        self._db.add(benchmark_run)
        self._db.flush()

        # Resolve and seed sessions
        sessions = self._sessions.resolve_chain(test.sessions)
        for session_fixture in sessions:
            # Override the user for isolation
            session_fixture.metadata.user = test_user
            seed_fixture(self._db, session_fixture, gitea_url=self._gitea_url)
        self._db.flush()

        # TODO: Real agent execution (Phase 2 of v2)
        # For now, the test seeds state and evaluates it.
        # Real execution requires integration with the orchestrator.

        # Evaluate with assertions
        all_assertion_results: list[AssertionResult] = []

        # Determine the session to evaluate against (last seeded session)
        last_session_id: UUID | None = None
        if sessions:
            last_session_id = fixture_uuid(sessions[-1].metadata.id)

        # Run eval assertions
        for eval_ref in test.evals:
            eval_def = self._evals.get(eval_ref.eval)
            if last_session_id is not None:
                assertion_results = match_assertions(
                    self._db,
                    last_session_id,
                    eval_def.assertions,
                    eval_ref.expected,
                )
                all_assertion_results.extend(assertion_results)

        # Run inline assertions if any
        if test.evaluate and test.evaluate.assertions and last_session_id is not None:
            inline_results = match_assertions(
                self._db,
                last_session_id,
                test.evaluate.assertions,
                {},
            )
            all_assertion_results.extend(inline_results)

        # Store test run
        duration_ms = int((time.time() - start) * 1000)
        assertions_passed = sum(1 for r in all_assertion_results if r.passed)
        assertions_total = len(all_assertion_results)
        status = (
            "passed"
            if assertions_total > 0 and assertions_passed == assertions_total
            else "failed"
            if assertions_total > 0
            else "passed"  # No assertions = vacuously passed
        )

        test_run = TestRun(
            benchmark_run_id=benchmark_run.id,
            test_name=test.name,
            test_description=test.description,
            test_user=test_user,
            hitl_profile=hitl_name,
            sessions_seeded=len(sessions),
            assertions_total=assertions_total,
            assertions_passed=assertions_passed,
            judge_checks_total=0,  # TODO when judge execution is wired
            judge_checks_passed=0,
            status=status,
            duration_ms=duration_ms,
        )
        self._db.add(test_run)
        self._db.flush()

        # Store tags (from all referenced evals)
        tags: set[str] = set()
        for eval_ref in test.evals:
            eval_def = self._evals.get(eval_ref.eval)
            tags.update(eval_def.tags)
        for tag in tags:
            self._db.add(TestRunTag(test_run_id=test_run.id, tag=tag))
        self._db.flush()

        benchmark_run.completed_at = datetime.now(timezone.utc)
        self._db.flush()

        return TestRunResult(
            test_name=test.name,
            test_user=test_user,
            hitl_profile=hitl_name,
            judge_profiles=judge_profiles,
            assertion_results=all_assertion_results,
            status=status,
            duration_ms=duration_ms,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _git_info() -> tuple[str | None, str | None]:
    """Return (commit, branch) from git, or (None, None) on failure."""
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()[:40]
        branch = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        return commit, branch
    except Exception:
        return None, None
