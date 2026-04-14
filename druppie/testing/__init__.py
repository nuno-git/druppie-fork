"""Consolidated testing framework.

Submodules:
    seed_ids, seed_schema  -- Fixture schemas and deterministic UUIDs
    replay_executor  -- Real MCP tool execution from YAML
    eval_schema, eval_context, eval_judge, eval_config, eval_live  -- LLM-as-Judge evaluation
    schema, runner, assertions  -- Test runner
    loaders  -- YAML config loaders (ProfileLoader, CheckLoader, ToolTestLoader)
    hitl_simulator  -- HITL simulation via LLM
    bounded_orchestrator  -- Orchestrator wrapper for bounded agent execution
    judge_runner  -- LLM judge for execution traces
"""

# Fixture helpers (used by replay_executor and runner)
from druppie.testing.seed_ids import fixture_uuid
from druppie.testing.seed_schema import SessionFixture

# Evaluation
from druppie.testing.eval_config import LiveEvaluationConfig, get_evaluation_config
from druppie.testing.eval_judge import JudgeEngine
from druppie.testing.eval_live import run_live_evaluation

# Loaders
from druppie.testing.loaders import CheckLoader, ProfileLoader, ToolTestLoader

# HITL
from druppie.testing.hitl_simulator import HITLSimulator

# Bounded orchestrator
from druppie.testing.bounded_orchestrator import BoundedOrchestrator

# Judge
from druppie.testing.judge_runner import JudgeCheckResult, JudgeRunner

# Runner
from druppie.testing.runner import TestRunResult, TestRunner

__all__ = [
    # Fixture helpers
    "fixture_uuid",
    "SessionFixture",
    # Evaluation
    "get_evaluation_config",
    "JudgeEngine",
    "LiveEvaluationConfig",
    "run_live_evaluation",
    # Loaders
    "CheckLoader",
    "ProfileLoader",
    "ToolTestLoader",
    # HITL
    "HITLSimulator",
    # Bounded orchestrator
    "BoundedOrchestrator",
    # Judge
    "JudgeCheckResult",
    "JudgeRunner",
    # Runner
    "TestRunResult",
    "TestRunner",
]
