#!/usr/bin/env python3
"""Run LLM-as-Judge evaluations against completed sessions.

Usage:
    # List available evaluations
    python scripts/evaluate.py --list

    # Evaluate architect design quality for a specific session
    python scripts/evaluate.py \\
        --evaluation=architect_design_quality \\
        --session-id=<uuid>

    # With a specific judge model
    python scripts/evaluate.py \\
        --evaluation=architect_design_quality \\
        --session-id=<uuid> \\
        --judge-model=claude-opus-4-6

    # With a custom run name
    python scripts/evaluate.py \\
        --evaluation=architect_design_quality \\
        --session-id=<uuid> \\
        --run-name="manual-test-2026-03-21"
"""

import argparse
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

# Add project root to path so druppie package is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Set DATABASE_URL before importing druppie modules (database.py reads it at
# import time via os.getenv)
if not os.getenv("DATABASE_URL"):
    os.environ["DATABASE_URL"] = (
        "postgresql://druppie:druppie_secret@localhost:5533/druppie"
    )

from druppie.db.database import SessionLocal
from druppie.db.models import BenchmarkRun
from druppie.evaluation.judge import JudgeEngine


def _git_info():
    """Get current git commit and branch."""
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()[:40]
        branch = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        return commit, branch
    except Exception:
        return None, None


def _print_results(results):
    """Print evaluation results in a readable format."""
    print()
    print("-" * 60)
    print("RESULTS")
    print("-" * 60)

    for r in results:
        print(f"\n  Rubric:     {r.rubric_name}")
        print(f"  Score type: {r.score_type}")
        if r.score_type == "binary":
            passed = "PASS" if r.score_binary else "FAIL"
            print(f"  Score:      {passed}")
        else:
            print(f"  Score:      {r.score_graded}/{r.max_score}")
        print(f"  Reasoning:  {r.judge_reasoning}")
        print(f"  Duration:   {r.judge_duration_ms}ms")
        print(f"  Tokens:     {r.judge_tokens_used}")

    print()
    print("-" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="Run LLM-as-Judge evaluations against completed sessions"
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List available evaluations and exit",
    )
    parser.add_argument(
        "--evaluation",
        type=str,
        help="Name of the evaluation to run",
    )
    parser.add_argument(
        "--session-id",
        type=str,
        help="UUID of the session to evaluate",
    )
    parser.add_argument(
        "--judge-model",
        type=str,
        default=None,
        help="Override the judge model (default: from evaluation YAML)",
    )
    parser.add_argument(
        "--run-name",
        type=str,
        default=None,
        help="Custom name for the benchmark run",
    )
    args = parser.parse_args()

    engine = JudgeEngine()

    # --list mode
    if args.list:
        print("Available evaluations:")
        for name in engine.available_evaluations:
            print(f"  - {name}")
        return

    # Validation
    if not args.evaluation:
        parser.error("--evaluation is required (use --list to see options)")
    if not args.session_id:
        parser.error("--session-id is required")

    try:
        session_id = UUID(args.session_id)
    except ValueError:
        print(f"Error: invalid UUID: {args.session_id}")
        sys.exit(1)

    if args.evaluation not in engine.available_evaluations:
        print(
            f"Error: unknown evaluation '{args.evaluation}'. "
            f"Available: {engine.available_evaluations}"
        )
        sys.exit(1)

    # Build run name
    git_commit, git_branch = _git_info()
    run_name = args.run_name or f"manual-{args.evaluation}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"

    print("=" * 60)
    print("Druppie — LLM-as-Judge Evaluation")
    print("=" * 60)
    print(f"  Evaluation:  {args.evaluation}")
    print(f"  Session:     {session_id}")
    print(f"  Judge model: {args.judge_model or '(from YAML)'}")
    print(f"  Run name:    {run_name}")
    print(f"  Git commit:  {git_commit or '(unknown)'}")
    print(f"  Git branch:  {git_branch or '(unknown)'}")
    print("=" * 60)

    db = SessionLocal()
    try:
        # Create benchmark run record
        benchmark_run = BenchmarkRun(
            name=run_name,
            run_type="manual",
            git_commit=git_commit,
            git_branch=git_branch,
            judge_model=args.judge_model,
            config_summary=f"evaluation={args.evaluation}, session={session_id}",
            started_at=datetime.now(timezone.utc),
        )
        db.add(benchmark_run)
        db.flush()

        # Run evaluation
        print("\nRunning evaluation...")
        results = engine.evaluate(
            db=db,
            session_id=session_id,
            evaluation_name=args.evaluation,
            benchmark_run_id=benchmark_run.id,
            judge_model_override=args.judge_model,
        )

        benchmark_run.completed_at = datetime.now(timezone.utc)
        db.commit()

        _print_results(results)
        print(f"[DONE] Benchmark run: {benchmark_run.id}")

    except Exception as e:
        db.rollback()
        print(f"\n[ERROR] {e}")
        raise
    finally:
        db.close()

    print("=" * 60)


if __name__ == "__main__":
    main()
