"""YAML config loaders for profiles, checks, and tool tests."""
from __future__ import annotations

import logging
from pathlib import Path

import yaml

from druppie.testing.schema import (
    CheckDefinition,
    CheckFile,
    HITLProfile,
    HITLProfilesFile,
    JudgeProfile,
    JudgeProfilesFile,
    ToolTestDefinition,
    ToolTestFile,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Profile Loader
# ---------------------------------------------------------------------------


class ProfileLoader:
    """Loads HITL and judge profiles from YAML files."""

    def __init__(self, profiles_dir: Path | None = None):
        self._profiles_dir = profiles_dir or (
            Path(__file__).resolve().parents[2] / "testing" / "profiles"
        )
        self._hitl: dict[str, HITLProfile] = {}
        self._judges: dict[str, JudgeProfile] = {}
        self._load()

    def _load(self) -> None:
        hitl_path = self._profiles_dir / "hitl.yaml"
        if hitl_path.exists():
            data = yaml.safe_load(hitl_path.read_text())
            parsed = HITLProfilesFile(**data)
            self._hitl = dict(parsed.profiles)

        judges_path = self._profiles_dir / "judges.yaml"
        if judges_path.exists():
            data = yaml.safe_load(judges_path.read_text())
            parsed = JudgeProfilesFile(**data)
            self._judges = dict(parsed.profiles)

    def get_hitl(self, name: str) -> HITLProfile:
        if name == "default":
            return HITLProfile(
                model="glm-4.5-air",
                provider="zai",
                prompt="You are a helpful user who gives clear, concise answers.",
            )
        if name not in self._hitl:
            raise KeyError(
                f"Unknown HITL profile: {name}. "
                f"Available: {sorted(self._hitl.keys())}"
            )
        return self._hitl[name]

    def get_judge(self, name: str) -> JudgeProfile:
        if name == "default":
            return JudgeProfile(model="glm-4.5-air", provider="zai")
        if name not in self._judges:
            raise KeyError(
                f"Unknown judge profile: {name}. "
                f"Available: {sorted(self._judges.keys())}"
            )
        return self._judges[name]


# ---------------------------------------------------------------------------
# Check Loader
# ---------------------------------------------------------------------------


class CheckLoader:
    """Loads check definitions from YAML files."""

    def __init__(self, checks_dir: Path | None = None):
        self._checks_dir = checks_dir or (
            Path(__file__).resolve().parents[2] / "testing" / "checks"
        )
        self._checks: dict[str, CheckDefinition] = {}
        self._load()

    def _load(self) -> None:
        if not self._checks_dir.exists():
            logger.warning("Checks directory not found: %s", self._checks_dir)
            return
        for path in sorted(self._checks_dir.glob("*.yaml")):
            data = yaml.safe_load(path.read_text())
            parsed = CheckFile(**data)
            self._checks[parsed.check.name] = parsed.check

    def get(self, name: str) -> CheckDefinition:
        if name not in self._checks:
            raise KeyError(
                f"Unknown check: {name}. Available: {sorted(self._checks.keys())}"
            )
        return self._checks[name]


# ---------------------------------------------------------------------------
# Tool Test Loader
# ---------------------------------------------------------------------------


class ToolTestLoader:
    """Loads tool test definitions from YAML files."""

    def __init__(self, tools_dir: Path | None = None):
        self._tools_dir = tools_dir or (
            Path(__file__).resolve().parents[2] / "testing" / "tools"
        )
        self._tests: dict[str, ToolTestDefinition] = {}
        self._load()

    def _load(self) -> None:
        if not self._tools_dir.exists():
            logger.warning("Tools directory not found: %s", self._tools_dir)
            return
        for path in sorted(self._tools_dir.glob("*.yaml")):
            data = yaml.safe_load(path.read_text())
            parsed = ToolTestFile(**data)
            self._tests[parsed.tool_test.name] = parsed.tool_test

    def get(self, name: str) -> ToolTestDefinition:
        if name not in self._tests:
            raise KeyError(
                f"Unknown tool test: {name}. Available: {sorted(self._tests.keys())}"
            )
        return self._tests[name]

    def all(self) -> list[ToolTestDefinition]:
        return list(self._tests.values())
