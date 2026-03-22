"""Live evaluation configuration loader."""

import random
from functools import lru_cache
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


@lru_cache(maxsize=1)
def get_evaluation_config() -> LiveEvaluationConfig:
    """Load and cache the live evaluation configuration from YAML.

    Looks for ``evaluation_config.yaml`` two levels up from this file
    (i.e. the project root).  Returns a default (disabled) config when
    the file is absent.
    """
    config_path = Path(__file__).resolve().parents[2] / "evaluation_config.yaml"
    if not config_path.exists():
        return LiveEvaluationConfig()
    data = yaml.safe_load(config_path.read_text())
    parsed = EvaluationConfigFile(**data)
    return parsed.live_evaluation
