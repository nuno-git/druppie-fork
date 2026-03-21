"""Consolidated testing framework: seeds, evaluations, and benchmarks.

Submodules:
    seed_ids, seed_schema, seed_loader  -- DB seeding from YAML fixtures
    eval_schema, eval_context, eval_judge, eval_config, eval_live  -- LLM-as-Judge evaluation
    bench_schema, bench_runner, bench_assertions, bench_simulator  -- Benchmark scenarios
"""

# Seeding
from druppie.testing.seed_ids import fixture_uuid
from druppie.testing.seed_loader import load_fixtures, seed_all, seed_fixture
from druppie.testing.seed_schema import SessionFixture

# Evaluation
from druppie.testing.eval_config import LiveEvaluationConfig, get_evaluation_config
from druppie.testing.eval_judge import JudgeEngine
from druppie.testing.eval_live import run_live_evaluation

# Benchmarks
from druppie.testing.bench_assertions import AssertionResult, check_assertions
from druppie.testing.bench_runner import (
    ScenarioResult,
    ScenarioRunner,
    load_all_scenarios,
    load_scenario,
)
from druppie.testing.bench_schema import ScenarioDefinition, ScenarioFile
from druppie.testing.bench_simulator import UserSimulator

__all__ = [
    # Seeding
    "fixture_uuid",
    "load_fixtures",
    "seed_all",
    "seed_fixture",
    "SessionFixture",
    # Evaluation
    "get_evaluation_config",
    "JudgeEngine",
    "LiveEvaluationConfig",
    "run_live_evaluation",
    # Benchmarks
    "AssertionResult",
    "check_assertions",
    "load_all_scenarios",
    "load_scenario",
    "ScenarioDefinition",
    "ScenarioFile",
    "ScenarioResult",
    "ScenarioRunner",
    "UserSimulator",
]
