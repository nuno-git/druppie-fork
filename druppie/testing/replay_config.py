"""Pydantic model for replay configuration."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class ReplayConfig(BaseModel):
    """Configuration for replay mode tool execution."""
    blocklist: list[str] = Field(default_factory=list)
    default_results: dict[str, str] = Field(default_factory=dict)
    timeout: int = 30
    on_error: str = "mock"  # mock, fail, skip


class ReplayConfigFile(BaseModel):
    """Top-level wrapper for replay_config.yaml."""
    replay: ReplayConfig


def load_replay_config(profiles_dir: Path | None = None) -> ReplayConfig:
    """Load replay config from YAML file."""
    if profiles_dir is None:
        profiles_dir = Path(__file__).resolve().parents[2] / "testing" / "profiles"
    config_path = profiles_dir / "replay_config.yaml"
    if not config_path.exists():
        return ReplayConfig()
    data = yaml.safe_load(config_path.read_text())
    parsed = ReplayConfigFile.model_validate(data)
    return parsed.replay
