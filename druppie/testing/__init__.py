"""Consolidated testing framework.

Submodules:
    seed_ids, seed_schema  -- Fixture schemas and deterministic UUIDs
    replay_executor  -- Real MCP tool execution from YAML
    eval_schema, eval_context, eval_judge, eval_config, eval_live  -- LLM-as-Judge evaluation
    v2_schema, v2_runner, v2_assertions  -- V2 test runner
"""

# Fixture helpers (used by replay_executor and v2_runner)
from druppie.testing.seed_ids import fixture_uuid
from druppie.testing.seed_schema import SessionFixture

# Evaluation
from druppie.testing.eval_config import LiveEvaluationConfig, get_evaluation_config
from druppie.testing.eval_judge import JudgeEngine
from druppie.testing.eval_live import run_live_evaluation

__all__ = [
    # Fixture helpers
    "fixture_uuid",
    "SessionFixture",
    # Evaluation
    "get_evaluation_config",
    "JudgeEngine",
    "LiveEvaluationConfig",
    "run_live_evaluation",
]
