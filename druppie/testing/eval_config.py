"""Live evaluation configuration loader."""

import random
import time
from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class LiveEvaluationConfig(BaseModel):
    """Configuration for live background evaluation."""

    enabled: bool = False
    sample_rate: float = 1.0
    judge_model: str = "glm-5"
    agent_evaluations: dict[str, list[str]] = Field(default_factory=dict)

    def should_evaluate(self, agent_id: str) -> bool:
        """Check whether a given agent run should be evaluated.

        Returns False if live evaluation is disabled, the agent has no
        configured evaluations, or the random sample rate check fails.
        """
        if not self.enabled:
            return False
        if agent_id not in self.agent_evaluations:
            return False
        if not self.agent_evaluations[agent_id]:
            return False
        return random.random() < self.sample_rate

    def get_evaluations(self, agent_id: str) -> list[str]:
        """Return the list of evaluation names configured for an agent."""
        return self.agent_evaluations.get(agent_id, [])


class EvaluationConfigFile(BaseModel):
    """Wrapper for the YAML file root (has 'live_evaluation' key)."""

    live_evaluation: LiveEvaluationConfig = Field(
        default_factory=LiveEvaluationConfig
    )


_cached_config: LiveEvaluationConfig | None = None
_cached_at: float = 0
_CACHE_TTL = 60  # seconds


def get_evaluation_config() -> LiveEvaluationConfig:
    """Load the live evaluation configuration from YAML.

    Caches for 60 seconds to avoid re-reading on every call while still
    picking up changes without a full process restart.

    Looks for ``evaluation_config.yaml`` two levels up from this file
    (i.e. the project root).  Returns a default (disabled) config when
    the file is absent.
    """
    global _cached_config, _cached_at
    now = time.monotonic()
    if _cached_config is not None and (now - _cached_at) < _CACHE_TTL:
        return _cached_config

    config_path = Path(__file__).resolve().parents[2] / "evaluation_config.yaml"
    if not config_path.exists():
        _cached_config = LiveEvaluationConfig()
    else:
        data = yaml.safe_load(config_path.read_text())
        parsed = EvaluationConfigFile(**data)
        _cached_config = parsed.live_evaluation
    _cached_at = now
    return _cached_config
