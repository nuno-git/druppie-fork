"""Consolidated testing framework: seeds and evaluations.

Submodules:
    seed_ids, seed_schema, seed_loader  -- DB seeding from YAML fixtures
    eval_schema, eval_context, eval_judge, eval_config, eval_live  -- LLM-as-Judge evaluation
    v2_schema, v2_runner, v2_assertions  -- V2 test runner
"""

# Seeding
from druppie.testing.seed_ids import fixture_uuid
from druppie.testing.seed_loader import load_fixtures, seed_all, seed_fixture
from druppie.testing.seed_schema import SessionFixture

# Evaluation
from druppie.testing.eval_config import LiveEvaluationConfig, get_evaluation_config
from druppie.testing.eval_judge import JudgeEngine
from druppie.testing.eval_live import run_live_evaluation

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
]
