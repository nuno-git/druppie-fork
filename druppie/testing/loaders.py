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


class YAMLLoadError(Exception):
    """Raised when a YAML test file cannot be parsed or validated.

    Carries the file path and original error for clear diagnostics.
    """

    def __init__(self, path: Path, detail: str, original: Exception | None = None):
        self.path = path
        self.original = original
        super().__init__(f"{path.name}: {detail}")


def _load_yaml_file(path: Path) -> dict:
    """Load and validate a single YAML file into a dict.

    Catches three classes of mistake early with actionable messages:
      1. YAML syntax errors (e.g. bare text outside a comment)
      2. File parses but result is not a dict (bare scalar document)
      3. File is empty or all-comments (yaml.safe_load returns None)
    """
    raw = path.read_text()
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as e:
        line = getattr(e, "problem_mark", None)
        line_info = f" (line {line.line + 1})" if line else ""
        raise YAMLLoadError(
            path,
            f"YAML syntax error{line_info}: {e}",
            original=e,
        ) from e

    if data is None:
        raise YAMLLoadError(
            path,
            "File is empty or contains only comments — no YAML content found. "
            "Make sure the file starts with a top-level key like 'tool-test:', 'check:', or 'agent-test:'.",
        )

    if not isinstance(data, dict):
        # This is the exact failure mode when a comment line loses its ## prefix.
        # yaml.safe_load returns the bare string as the document, ignoring the
        # real content below it.
        preview = str(data)[:80]
        raise YAMLLoadError(
            path,
            f"File parsed as a '{type(data).__name__}' ({preview!r}…) instead of a mapping. "
            "This usually means a line that should be a comment (##) is missing its prefix, "
            "causing YAML to treat it as the document body. "
            "Check for un-commented text above your top-level key.",
            original=None,
        )

    return data


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
            try:
                data = _load_yaml_file(hitl_path)
                parsed = HITLProfilesFile(**data)
                self._hitl = dict(parsed.profiles)
            except (YAMLLoadError, Exception) as e:
                logger.error("Failed to load %s: %s", hitl_path.name, e)

        judges_path = self._profiles_dir / "judges.yaml"
        if judges_path.exists():
            try:
                data = _load_yaml_file(judges_path)
                parsed = JudgeProfilesFile(**data)
                self._judges = dict(parsed.profiles)
            except (YAMLLoadError, Exception) as e:
                logger.error("Failed to load %s: %s", judges_path.name, e)

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
            try:
                data = _load_yaml_file(path)
                parsed = CheckFile(**data)
                self._checks[parsed.check.name] = parsed.check
            except (YAMLLoadError, Exception) as e:
                logger.error("Failed to load check %s: %s", path.name, e)

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
            try:
                data = _load_yaml_file(path)
                parsed = ToolTestFile(**data)
                self._tests[parsed.tool_test.name] = parsed.tool_test
            except (YAMLLoadError, Exception) as e:
                logger.error("Failed to load tool test %s: %s", path.name, e)

    def get(self, name: str) -> ToolTestDefinition:
        if name not in self._tests:
            raise KeyError(
                f"Unknown tool test: {name}. Available: {sorted(self._tests.keys())}"
            )
        return self._tests[name]

    def all(self) -> list[ToolTestDefinition]:
        return list(self._tests.values())
