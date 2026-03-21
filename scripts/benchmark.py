#!/usr/bin/env python3
"""Run benchmark scenarios.

Usage:
    python scripts/benchmark.py --list
    python scripts/benchmark.py --scenario=create-todo-app
    python scripts/benchmark.py --all
    python scripts/benchmark.py --all --judge-model=claude-opus-4-6
    python scripts/benchmark.py --all --dry-run
"""

import argparse
import os
import sys
from pathlib import Path

# Add project root to path so druppie package is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Set DATABASE_URL before importing druppie modules (database.py reads it at
# import time via os.getenv)
if not os.getenv("DATABASE_URL"):
    os.environ["DATABASE_URL"] = (
        "postgresql://druppie:druppie_secret@localhost:5533/druppie"
    )

from druppie.benchmarks.runner import ScenarioRunner, load_all_scenarios, load_scenario
from druppie.db.database import SessionLocal


def _print_result(result):
    status = "PASS" if result.passed else "FAIL"
    print(f"\n  [{status}] {result.scenario_name}")
    if result.assertion_results:
        print("  Assertions:")
        for ar in result.assertion_results:
            mark = "OK" if ar.passed else "FAIL"
            print(f"    [{mark}] {ar.assertion.agent}.{ar.assertion.assert_type}: {ar.message}")
    if result.evaluation_results:
        print("  Evaluations:")
        for er in result.evaluation_results:
            if er.score_type == "binary":
                score = "PASS" if er.score_binary else "FAIL"
            else:
                score = f"{er.score_graded}/{er.max_score}"
            print(f"    {er.rubric_name}: {score}")
    if result.errors:
        print("  Errors:")
        for e in result.errors:
            print(f"    - {e}")


def main():
    parser = argparse.ArgumentParser(description="Run Druppie benchmark scenarios")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--scenario", type=str)
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--judge-model", type=str, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--scenarios-dir",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "benchmarks" / "scenarios",
    )
    args = parser.parse_args()

    if not args.scenarios_dir.exists():
        print(f"Error: scenarios directory not found: {args.scenarios_dir}")
        sys.exit(1)

    if args.list:
        scenarios = load_all_scenarios(args.scenarios_dir)
        print("Available scenarios:")
        for path, s in scenarios:
            print(f"  {path.stem}: {s.description or s.name}")
        return

    if args.scenario:
        path = args.scenarios_dir / f"{args.scenario}.yaml"
        if not path.exists():
            print(f"Error: scenario not found: {path}")
            sys.exit(1)
        scenarios = [(path, load_scenario(path))]
    elif args.all:
        scenarios = load_all_scenarios(args.scenarios_dir)
    else:
        parser.error("Specify --scenario=<name>, --all, or --list")
        return

    if args.dry_run:
        print(f"Validated {len(scenarios)} scenarios:")
        for path, s in scenarios:
            print(f"  {path.stem}: {s.name}")
            print(f"    mocked: {[m.agent_id for m in s.mocked_agents]}")
            print(f"    under test: {s.agents_under_test}")
            print(f"    evaluations: {s.evaluations}")
            print(f"    assertions: {len(s.assertions)}")
        return

    print("=" * 60)
    print("Druppie — Benchmark Runner")
    print("=" * 60)

    db = SessionLocal()
    try:
        runner = ScenarioRunner(db=db, judge_model=args.judge_model)
        results = []
        for path, scenario in scenarios:
            print(f"\nRunning: {scenario.name}...")
            result = runner.run(scenario)
            results.append(result)
            _print_result(result)
        db.commit()

        print("\n" + "=" * 60)
        passed = sum(1 for r in results if r.passed)
        print(f"Results: {passed}/{len(results)} passed")
        print("=" * 60)

        if passed < len(results):
            sys.exit(1)
    except Exception as e:
        db.rollback()
        print(f"\n[ERROR] {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
