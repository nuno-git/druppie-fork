#!/usr/bin/env python3
"""V2 Test Runner -- run user-isolated tests.

Usage:
    # List all tests
    python scripts/test_runner.py --list

    # Run a specific test
    python scripts/test_runner.py --test=router-update-weather-5-projects

    # Run tests by tag
    python scripts/test_runner.py --tag=router

    # Run all tests
    python scripts/test_runner.py --all

    # Dry run (validate without executing)
    python scripts/test_runner.py --all --dry-run

    # With specific HITL/judge override
    python scripts/test_runner.py --all --hitl=non-technical-pm --judge=strict-opus

    # Cleanup test users
    python scripts/test_runner.py --cleanup
"""

import argparse
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Add project root to path so druppie package is importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Load .env file so LLM API keys and provider config are available.
# Uses override=False so explicit env vars (e.g. from CLI) take precedence.
from dotenv import load_dotenv  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env", override=False)

# Set DATABASE_URL before importing druppie modules (database.py reads it at
# import time via os.getenv)
if not os.getenv("DATABASE_URL"):
    os.environ["DATABASE_URL"] = (
        "postgresql://druppie:druppie_secret@localhost:5533/druppie"
    )

# Set GITEA_URL before importing druppie modules (gitea.py reads it at
# import time via os.getenv and defaults to http://gitea:3000 which is
# only reachable inside Docker).  When running from the host, derive a
# localhost URL from GITEA_PORT (loaded by dotenv above).
if not os.getenv("GITEA_URL"):
    _gitea_port = os.getenv("GITEA_PORT", "3200")
    os.environ["GITEA_URL"] = f"http://localhost:{_gitea_port}"

from druppie.testing.v2_runner import (  # noqa: E402
    EvalLoader,
    TestRunner,
    TestRunResult,
)
from druppie.testing.v2_schema import TestDefinition, TestFile  # noqa: E402

TESTING_DIR = PROJECT_ROOT / "testing"
TESTS_DIR = TESTING_DIR / "tests"
EVALS_DIR = TESTING_DIR / "evals"
REPORTS_DIR = TESTING_DIR / "reports"


# ---------------------------------------------------------------------------
# ANSI colours (disabled when stdout is not a TTY)
# ---------------------------------------------------------------------------

_USE_COLOR = hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


def _green(text: str) -> str:
    return f"\033[92m{text}\033[0m" if _USE_COLOR else text


def _red(text: str) -> str:
    return f"\033[91m{text}\033[0m" if _USE_COLOR else text


def _yellow(text: str) -> str:
    return f"\033[93m{text}\033[0m" if _USE_COLOR else text


def _bold(text: str) -> str:
    return f"\033[1m{text}\033[0m" if _USE_COLOR else text


# ---------------------------------------------------------------------------
# Gitea URL detection (same logic as seed.py)
# ---------------------------------------------------------------------------


def _default_gitea_url() -> str | None:
    """Derive the default Gitea URL from .env or environment.

    Prefers GITEA_INTERNAL_URL (Docker-internal address like http://gitea:3000)
    when available, since tests typically run inside the Docker network.
    Falls back to GITEA_URL or GITEA_PORT-based localhost URL.
    """
    # Inside Docker, GITEA_INTERNAL_URL points to the Docker network address
    internal_url = os.getenv("GITEA_INTERNAL_URL")
    if internal_url:
        return internal_url

    url = os.getenv("GITEA_URL")
    if url:
        return url

    env_path = PROJECT_ROOT / ".env"
    gitea_port = None
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line.startswith("GITEA_PORT="):
                gitea_port = line.split("=", 1)[1].strip()
                break
    if gitea_port:
        return f"http://localhost:{gitea_port}"
    return None


# ---------------------------------------------------------------------------
# Test discovery & loading
# ---------------------------------------------------------------------------


def _load_test(path: Path) -> TestDefinition:
    """Load a test definition from a YAML file."""
    import yaml

    data = yaml.safe_load(path.read_text())
    return TestFile(**data).test


def _discover_tests() -> list[tuple[Path, TestDefinition]]:
    """Discover all test YAML files and load their definitions."""
    if not TESTS_DIR.exists():
        return []
    tests = []
    for path in sorted(TESTS_DIR.glob("*.yaml")):
        try:
            test_def = _load_test(path)
            tests.append((path, test_def))
        except Exception as exc:
            print(f"  {_red('WARN')}: Failed to load {path.name}: {exc}")
    return tests


def _collect_tags_for_test(test: TestDefinition, eval_loader: EvalLoader) -> set[str]:
    """Collect all tags from evals referenced by a test."""
    tags: set[str] = set()
    for eval_ref in test.evals:
        try:
            eval_def = eval_loader.get(eval_ref.eval)
            tags.update(eval_def.tags)
        except KeyError:
            pass
    return tags


# ---------------------------------------------------------------------------
# --list
# ---------------------------------------------------------------------------


def cmd_list() -> None:
    """List all tests with name, description, and tags."""
    eval_loader = EvalLoader(EVALS_DIR)
    tests = _discover_tests()
    if not tests:
        print("No tests found in", TESTS_DIR)
        return

    print("=" * 60)
    print("Druppie -- V2 Test Runner")
    print("=" * 60)
    print()
    print(f"Found {len(tests)} test(s) in {TESTS_DIR}")
    print()

    for path, test_def in tests:
        tags = _collect_tags_for_test(test_def, eval_loader)
        tag_str = ", ".join(sorted(tags)) if tags else "(none)"
        print(f"  {_bold(test_def.name)}")
        if test_def.description:
            print(f"    {test_def.description}")
        print(f"    tags: {tag_str}")
        print()

    print("=" * 60)


# ---------------------------------------------------------------------------
# --dry-run
# ---------------------------------------------------------------------------


def cmd_dry_run(tests: list[tuple[Path, TestDefinition]]) -> None:
    """Validate test files without executing."""
    eval_loader = EvalLoader(EVALS_DIR)
    errors: list[tuple[str, str]] = []

    print("=" * 60)
    print("Druppie -- V2 Test Runner (dry run)")
    print("=" * 60)
    print()
    print(f"Validating {len(tests)} test(s)...")
    print()

    for path, test_def in tests:
        issues: list[str] = []

        # Validate eval references exist
        for eval_ref in test_def.evals:
            try:
                eval_loader.get(eval_ref.eval)
            except KeyError as exc:
                issues.append(str(exc))

        # Validate run section
        if not test_def.run.message:
            issues.append("run.message is empty")

        if issues:
            print(f"  {_red('[FAIL]')} {test_def.name}")
            for issue in issues:
                errors.append((test_def.name, issue))
                print(f"    {_red('ERROR')}: {issue}")
        else:
            tags = _collect_tags_for_test(test_def, eval_loader)
            tag_str = ", ".join(sorted(tags)) if tags else "(none)"
            print(f"  {_green('[OK]')}   {test_def.name}")
            print(f"    sessions: {len(test_def.sessions)} | "
                  f"evals: {len(test_def.evals)} | "
                  f"tags: {tag_str}")
    print()
    if errors:
        print(f"{_red('Validation failed')}: {len(errors)} error(s)")
    else:
        print(f"{_green('All tests valid')}")
    print("=" * 60)


# ---------------------------------------------------------------------------
# Run tests
# ---------------------------------------------------------------------------


def cmd_run(
    tests: list[tuple[Path, TestDefinition]],
    gitea_url: str | None,
    hitl_override: str | None,
    judge_override: str | None,
) -> None:
    """Run tests and produce results + report."""
    from druppie.db.database import SessionLocal

    db = SessionLocal()
    try:
        runner = TestRunner(db, testing_dir=TESTING_DIR, gitea_url=gitea_url)

        print("=" * 60)
        print("Druppie -- V2 Test Runner")
        print("=" * 60)
        print()
        if gitea_url:
            print(f"  Gitea URL: {gitea_url}")
        else:
            print("  Gitea URL: not set (record-only mode)")
        print()
        print(f"Running {len(tests)} test(s)...")
        print()

        all_results: list[TestRunResult] = []
        run_start = time.time()

        for _path, test_def in tests:
            # Apply overrides
            if hitl_override:
                test_def.hitl = hitl_override
            if judge_override:
                test_def.judge = judge_override
                test_def.judges = None

            try:
                results = runner.run_test(test_def)
                db.commit()
                all_results.extend(results)

                for result in results:
                    _print_result(result)
            except Exception as exc:
                db.rollback()
                # Build a synthetic failure result
                error_result = TestRunResult(
                    test_name=test_def.name,
                    test_user="(error)",
                    hitl_profile=hitl_override or "default",
                    judge_profiles=[judge_override or "default"],
                    assertion_results=[],
                    status="error",
                    duration_ms=0,
                )
                all_results.append(error_result)
                print(f"  {_red('[ERROR]')} {test_def.name}")
                print(f"    {exc}")
                print()

        total_duration = time.time() - run_start
        total_passed = sum(1 for r in all_results if r.passed)
        total = len(all_results)

        # Generate report
        report_path = _generate_report(all_results, total_duration)

        print("=" * 60)
        status_line = f"Results: {total_passed}/{total} passed"
        if total_passed == total:
            print(_green(status_line))
        else:
            print(_red(status_line))
        if report_path:
            print(f"Report: {report_path.relative_to(PROJECT_ROOT)}")
        print("=" * 60)

    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _print_result(result: TestRunResult) -> None:
    """Print a single test result to stdout."""
    duration_s = result.duration_ms / 1000
    assertions_passed = sum(1 for a in result.assertion_results if a.passed)
    assertions_total = len(result.assertion_results)
    judge_results = getattr(result, "judge_results", [])
    judge_passed = sum(1 for j in judge_results if j.passed)
    judge_total = len(judge_results)

    status_tag = _green("[PASS]") if result.passed else _red("[FAIL]")
    if result.status == "error":
        status_tag = _red("[ERROR]")

    print(f"  {status_tag} {result.test_name} ({duration_s:.1f}s)")
    parts = [f"hitl: {result.hitl_profile}"]
    parts.append(f"assertions: {assertions_passed}/{assertions_total}")
    if judge_total > 0:
        parts.append(f"judge: {judge_passed}/{judge_total}")
    print(f"    {' | '.join(parts)}")

    if not result.passed:
        for a in result.assertion_results:
            if not a.passed:
                print(f"    {_red('FAIL')}: {a.name}: {a.message}")
        for j in judge_results:
            if not j.passed:
                check_short = j.check[:60] + "..." if len(j.check) > 60 else j.check
                print(f"    {_red('JUDGE')}: {check_short}")
                if j.reasoning:
                    print(f"      {j.reasoning[:120]}")
    print()


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------


def _generate_report(
    results: list[TestRunResult],
    total_duration: float,
) -> Path | None:
    """Generate a markdown report and save to testing/reports/."""
    if not results:
        return None

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    filename = now.strftime("%Y-%m-%d-%H%M%S") + ".md"
    report_path = REPORTS_DIR / filename

    total_passed = sum(1 for r in results if r.passed)
    total = len(results)

    lines: list[str] = []
    lines.append(f"# Test Run: {now.strftime('%Y-%m-%d %H:%M')}")
    lines.append("")
    lines.append(
        f"**Total: {total_passed}/{total} passed** | "
        f"Duration: {total_duration:.1f}s | "
        f"Timestamp: {now.isoformat()}"
    )
    lines.append("")

    # Group results by tags
    # First, collect tags for each result by loading evals
    eval_loader = EvalLoader(EVALS_DIR)
    tag_results: dict[str, list[TestRunResult]] = {}
    untagged: list[TestRunResult] = []

    for result in results:
        # Find test definition to get eval refs
        test_path = TESTS_DIR / f"{result.test_name}.yaml"
        tags: set[str] = set()
        if test_path.exists():
            try:
                test_def = _load_test(test_path)
                tags = _collect_tags_for_test(test_def, eval_loader)
            except Exception:
                pass

        if tags:
            for tag in tags:
                tag_results.setdefault(tag, []).append(result)
        else:
            untagged.append(result)

    lines.append("## Results by Tag")
    lines.append("")

    for tag in sorted(tag_results.keys()):
        tag_res = tag_results[tag]
        tag_passed = sum(1 for r in tag_res if r.passed)
        tag_total = len(tag_res)
        pass_rate = (tag_passed / tag_total * 100) if tag_total > 0 else 0
        lines.append(f"### {tag} ({tag_total} tests) -- {pass_rate:.0f}% pass rate")
        lines.append("")
        lines.append("| Test | Status | HITL Profile | Assertions | Judge | Duration |")
        lines.append("|------|--------|--------------|------------|-------|----------|")

        for r in tag_res:
            a_passed = sum(1 for a in r.assertion_results if a.passed)
            a_total = len(r.assertion_results)
            j_results = getattr(r, "judge_results", [])
            j_passed = sum(1 for j in j_results if j.passed)
            j_total = len(j_results)
            judge_str = f"{j_passed}/{j_total}" if j_total > 0 else "-"
            duration_s = r.duration_ms / 1000
            status = "PASS" if r.passed else "FAIL" if r.status == "failed" else "ERROR"
            lines.append(
                f"| {r.test_name} | {status} | {r.hitl_profile} | "
                f"{a_passed}/{a_total} | {judge_str} | {duration_s:.1f}s |"
            )

            # Show failures
            if not r.passed:
                for a in r.assertion_results:
                    if not a.passed:
                        lines.append(f"  > FAIL: {a.name}: {a.message}")
                for j in j_results:
                    if not j.passed:
                        lines.append(f"  > JUDGE: {j.check[:80]}")

        lines.append("")

    if untagged:
        lines.append("### (untagged)")
        lines.append("")
        lines.append("| Test | Status | HITL Profile | Assertions | Judge | Duration |")
        lines.append("|------|--------|--------------|------------|-------|----------|")
        for r in untagged:
            a_passed = sum(1 for a in r.assertion_results if a.passed)
            a_total = len(r.assertion_results)
            j_results = getattr(r, "judge_results", [])
            j_passed = sum(1 for j in j_results if j.passed)
            j_total = len(j_results)
            judge_str = f"{j_passed}/{j_total}" if j_total > 0 else "-"
            duration_s = r.duration_ms / 1000
            status = "PASS" if r.passed else "FAIL" if r.status == "failed" else "ERROR"
            lines.append(
                f"| {r.test_name} | {status} | {r.hitl_profile} | "
                f"{a_passed}/{a_total} | {judge_str} | {duration_s:.1f}s |"
            )
            if not r.passed:
                for a in r.assertion_results:
                    if not a.passed:
                        lines.append(f"  > FAIL: {a.name}: {a.message}")
                for j in j_results:
                    if not j.passed:
                        lines.append(f"  > JUDGE: {j.check[:80]}")
        lines.append("")

    report_content = "\n".join(lines) + "\n"
    report_path.write_text(report_content)
    return report_path


# ---------------------------------------------------------------------------
# --cleanup
# ---------------------------------------------------------------------------


def cmd_cleanup() -> None:
    """Delete all test users (matching test-*) and their data from DB.

    Deletes in FK-safe order to avoid foreign key violations:
    1. TestRunTag, TestRun, BenchmarkRun (test metadata)
    2. EvaluationResult (references sessions, agent_runs, benchmark_runs)
    3. SandboxSession (references sessions, users, tool_calls)
    4. Approval, Question (reference tool_calls, sessions, users)
    5. ToolCallNormalization (references tool_calls)
    6. ToolCall (references sessions, agent_runs, llm_calls)
    7. LlmRetry (references llm_calls)
    8. LlmCall (references sessions, agent_runs)
    9. Message (references sessions, agent_runs)
    10. AgentRun (references sessions)
    11. Session (references users, projects)
    12. Project (references users via owner_id)
    13. UserRole, UserToken (reference users -- CASCADE, but explicit is safer)
    14. User
    """
    from sqlalchemy import text

    from druppie.db.database import SessionLocal
    from druppie.db.models import (
        AgentRun,
        Approval,
        BenchmarkRun,
        EvaluationResult,
        LlmCall,
        Message,
        Project,
        Question,
        SandboxSession,
        Session,
        TestRun,
        TestRunTag,
        ToolCall,
        ToolCallNormalization,
        User,
        UserRole,
        UserToken,
    )
    from druppie.db.models.llm_retry import LlmRetry

    db = SessionLocal()
    try:
        # Get test user IDs
        test_users = db.query(User).filter(
            User.username.like("test-%") | User.username.like("t-%")
        ).all()
        if not test_users:
            print("No test users found.")
            return

        user_ids = [u.id for u in test_users]
        print(f"Found {len(test_users)} test user(s), cleaning up...")

        # -- Get session IDs owned by test users --
        session_ids = [
            sid
            for (sid,) in db.query(Session.id)
            .filter(Session.user_id.in_(user_ids))
            .all()
        ]

        # -- Get project IDs owned by test users --
        project_ids = [
            pid
            for (pid,) in db.query(Project.id)
            .filter(Project.owner_id.in_(user_ids))
            .all()
        ]

        # -- 1. Delete test run metadata (benchmark_runs named "test-*") --
        test_run_ids = [
            trid
            for (trid,) in db.query(TestRun.id)
            .filter(TestRun.test_user.like("test-%") | TestRun.test_user.like("t-%"))
            .all()
        ]
        if test_run_ids:
            tag_count = (
                db.query(TestRunTag)
                .filter(TestRunTag.test_run_id.in_(test_run_ids))
                .delete(synchronize_session=False)
            )
            print(f"  Deleted {tag_count} test run tag(s)")

        tr_count = (
            db.query(TestRun)
            .filter(TestRun.test_user.like("test-%") | TestRun.test_user.like("t-%"))
            .delete(synchronize_session=False)
        )
        print(f"  Deleted {tr_count} test run(s)")

        br_count = (
            db.query(BenchmarkRun)
            .filter(BenchmarkRun.name.like("test-%"))
            .delete(synchronize_session=False)
        )
        print(f"  Deleted {br_count} benchmark run(s)")

        if session_ids:
            # -- 2. Evaluation results --
            er_count = (
                db.query(EvaluationResult)
                .filter(EvaluationResult.session_id.in_(session_ids))
                .delete(synchronize_session=False)
            )
            print(f"  Deleted {er_count} evaluation result(s)")

            # -- 3. Sandbox sessions --
            ss_count = (
                db.query(SandboxSession)
                .filter(SandboxSession.session_id.in_(session_ids))
                .delete(synchronize_session=False)
            )
            print(f"  Deleted {ss_count} sandbox session(s)")

            # -- 4. Approvals and Questions --
            ap_count = (
                db.query(Approval)
                .filter(Approval.session_id.in_(session_ids))
                .delete(synchronize_session=False)
            )
            print(f"  Deleted {ap_count} approval(s)")

            q_count = (
                db.query(Question)
                .filter(Question.session_id.in_(session_ids))
                .delete(synchronize_session=False)
            )
            print(f"  Deleted {q_count} question(s)")

            # -- 5. Tool call normalizations (via tool_calls in these sessions) --
            tc_ids = [
                tcid
                for (tcid,) in db.query(ToolCall.id)
                .filter(ToolCall.session_id.in_(session_ids))
                .all()
            ]
            if tc_ids:
                tcn_count = (
                    db.query(ToolCallNormalization)
                    .filter(ToolCallNormalization.tool_call_id.in_(tc_ids))
                    .delete(synchronize_session=False)
                )
                print(f"  Deleted {tcn_count} tool call normalization(s)")

            # -- 6. Tool calls --
            tc_count = (
                db.query(ToolCall)
                .filter(ToolCall.session_id.in_(session_ids))
                .delete(synchronize_session=False)
            )
            print(f"  Deleted {tc_count} tool call(s)")

            # -- 7-8. LLM retries and calls --
            llm_ids = [
                lid
                for (lid,) in db.query(LlmCall.id)
                .filter(LlmCall.session_id.in_(session_ids))
                .all()
            ]
            if llm_ids:
                lr_count = (
                    db.query(LlmRetry)
                    .filter(LlmRetry.llm_call_id.in_(llm_ids))
                    .delete(synchronize_session=False)
                )
                print(f"  Deleted {lr_count} LLM retry(ies)")

            llm_count = (
                db.query(LlmCall)
                .filter(LlmCall.session_id.in_(session_ids))
                .delete(synchronize_session=False)
            )
            print(f"  Deleted {llm_count} LLM call(s)")

            # -- 9. Messages --
            msg_count = (
                db.query(Message)
                .filter(Message.session_id.in_(session_ids))
                .delete(synchronize_session=False)
            )
            print(f"  Deleted {msg_count} message(s)")

            # -- 10. Agent runs --
            ar_count = (
                db.query(AgentRun)
                .filter(AgentRun.session_id.in_(session_ids))
                .delete(synchronize_session=False)
            )
            print(f"  Deleted {ar_count} agent run(s)")

        # -- 11. Sessions --
        session_count = (
            db.query(Session)
            .filter(Session.user_id.in_(user_ids))
            .delete(synchronize_session=False)
        )
        print(f"  Deleted {session_count} session(s)")

        # -- 12. Projects owned by test users --
        project_count = (
            db.query(Project)
            .filter(Project.owner_id.in_(user_ids))
            .delete(synchronize_session=False)
        )
        print(f"  Deleted {project_count} project(s)")

        # -- 13. Also delete sandbox sessions referencing test users directly --
        ss_user_count = (
            db.query(SandboxSession)
            .filter(SandboxSession.user_id.in_(user_ids))
            .delete(synchronize_session=False)
        )
        if ss_user_count:
            print(f"  Deleted {ss_user_count} additional sandbox session(s) by user")

        # -- 14. Clear approval resolved_by references to test users --
        # (approvals in non-test sessions that were resolved by a test user)
        db.execute(
            text("UPDATE approvals SET resolved_by = NULL WHERE resolved_by = ANY(:ids)"),
            {"ids": user_ids},
        )

        # -- 15. User roles and tokens (CASCADE would handle this, but be explicit) --
        role_count = (
            db.query(UserRole)
            .filter(UserRole.user_id.in_(user_ids))
            .delete(synchronize_session=False)
        )
        token_count = (
            db.query(UserToken)
            .filter(UserToken.user_id.in_(user_ids))
            .delete(synchronize_session=False)
        )
        print(f"  Deleted {role_count} user role(s), {token_count} user token(s)")

        # -- 16. Users --
        user_count = (
            db.query(User)
            .filter(User.id.in_(user_ids))
            .delete(synchronize_session=False)
        )
        print(f"  Deleted {user_count} user(s)")

        db.commit()
        print(f"\nCleanup complete: {user_count} test user(s) removed.")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Filter helpers
# ---------------------------------------------------------------------------


def _filter_by_tag(
    tests: list[tuple[Path, TestDefinition]],
    tag: str,
) -> list[tuple[Path, TestDefinition]]:
    """Filter tests to those whose evals have the given tag."""
    eval_loader = EvalLoader(EVALS_DIR)
    filtered = []
    for path, test_def in tests:
        tags = _collect_tags_for_test(test_def, eval_loader)
        if tag in tags:
            filtered.append((path, test_def))
    return filtered


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Druppie V2 Test Runner -- run user-isolated tests",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Mode flags (mutually exclusive group for clarity, but allowing combos)
    parser.add_argument(
        "--list",
        action="store_true",
        help="List all tests with name, description, and tags",
    )
    parser.add_argument(
        "--test",
        type=str,
        metavar="NAME",
        help="Run a specific test by name (filename without .yaml)",
    )
    parser.add_argument(
        "--tag",
        type=str,
        metavar="TAG",
        help="Run all tests whose evals have this tag",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Run all tests",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate test files without executing",
    )
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="Delete all test users (matching test-*) from DB",
    )

    # Overrides
    parser.add_argument(
        "--hitl",
        type=str,
        metavar="PROFILE",
        help="Override HITL profile for all tests",
    )
    parser.add_argument(
        "--judge",
        type=str,
        metavar="PROFILE",
        help="Override judge profile for all tests",
    )
    parser.add_argument(
        "--gitea-url",
        type=str,
        default=None,
        help=(
            "Gitea base URL (e.g. http://localhost:3200). "
            "Auto-detected from GITEA_URL env var or GITEA_PORT in .env."
        ),
    )

    args = parser.parse_args()

    # If no action specified, show help
    if not any([args.list, args.test, args.tag, args.all, args.cleanup]):
        parser.print_help()
        sys.exit(0)

    # --list
    if args.list:
        cmd_list()
        return

    # --cleanup
    if args.cleanup:
        cmd_cleanup()
        return

    # Resolve Gitea URL
    gitea_url = args.gitea_url or _default_gitea_url()

    # Determine which tests to run
    if args.test:
        test_path = TESTS_DIR / f"{args.test}.yaml"
        if not test_path.exists():
            print(f"Error: test not found: {test_path}")
            sys.exit(1)
        tests = [(test_path, _load_test(test_path))]
    elif args.tag:
        all_tests = _discover_tests()
        tests = _filter_by_tag(all_tests, args.tag)
        if not tests:
            print(f"No tests found with tag: {args.tag}")
            sys.exit(1)
    elif args.all:
        tests = _discover_tests()
        if not tests:
            print(f"No tests found in {TESTS_DIR}")
            sys.exit(1)
    else:
        parser.print_help()
        sys.exit(0)

    # --dry-run
    if args.dry_run:
        cmd_dry_run(tests)
        return

    # Run tests
    cmd_run(tests, gitea_url, args.hitl, args.judge)


if __name__ == "__main__":
    main()
