"""Pydantic schemas for v2 testing framework.

Four concepts:
- Sessions: world state definitions (uses existing seed_schema.SessionFixture)
- Evals: what to check (assertions + judge checks, no correct answers)
- Profiles: HITL simulator and judge configurations
- Tests: combine sessions + run + evals with expected values
"""
from __future__ import annotations

from pydantic import BaseModel, Field, ConfigDict
from typing import Literal


# --- Eval Schema ---


class EvalAssertion(BaseModel):
    """An assertion in an eval definition. Arguments are NOT specified here -- tests provide expected values."""

    model_config = ConfigDict(populate_by_name=True)
    agent: str
    completed: bool | None = None
    tool_called: str | None = None  # e.g. "builtin:set_intent"
    result_valid: list[str] | None = None  # list of validator names
    status: str | None = None  # expected tool call status
    error_contains: str | None = None  # expected error message substring
    error_matches: str | None = None  # expected error message regex
    # No arguments here -- tests fill in expected values


class EvalJudge(BaseModel):
    """Judge checks in an eval definition."""

    checks: list[str] = Field(default_factory=list)


class EvalDefinition(BaseModel):
    """An eval definition -- what to check, not what the correct answer is."""

    name: str
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    assertions: list[EvalAssertion] = Field(default_factory=list)
    judge: EvalJudge | None = None


class EvalFile(BaseModel):
    """Wrapper for eval YAML files."""

    eval: EvalDefinition


# --- Profile Schema ---


class HITLProfile(BaseModel):
    """HITL simulator profile."""

    model: str
    provider: str = "zai"
    prompt: str


class JudgeProfile(BaseModel):
    """Judge profile."""

    model: str
    provider: str = "zai"


class HITLProfilesFile(BaseModel):
    """YAML file with HITL profiles."""

    profiles: dict[str, HITLProfile]


class JudgeProfilesFile(BaseModel):
    """YAML file with judge profiles."""

    profiles: dict[str, JudgeProfile]


# --- Test Schema ---


class SeedSessionRef(BaseModel):
    """Reference to a session with explicit seed mode."""

    __test__ = False
    session: str
    mode: str = "replay"


class VerifyCheck(BaseModel):
    """A side-effect verification check."""

    __test__ = False
    file_exists: str | None = None
    file_not_empty: str | None = None
    file_contains: dict | None = None  # {path, content}
    file_matches: dict | None = None  # {path, pattern}
    mermaid_valid: str | None = None
    git_branch_exists: str | None = None
    gitea_repo_exists: bool | None = None


class TestEvalRef(BaseModel):
    """Reference to an eval with expected values for this test."""

    __test__ = False  # Not a pytest test class
    model_config = ConfigDict(populate_by_name=True)
    eval: str  # eval name to reference
    expected: dict[str, object] = Field(default_factory=dict)
    # Values can be: "exact_value", "*" (wildcard), ["option1", "option2"] (any-of)


class TestInlineJudge(BaseModel):
    """Inline judge checks specific to this test."""

    __test__ = False  # Not a pytest test class
    checks: list[str] = Field(default_factory=list)


class TestInlineEvaluate(BaseModel):
    """Inline evaluation specific to this test (not reusable)."""

    __test__ = False  # Not a pytest test class
    assertions: list[EvalAssertion] = Field(default_factory=list)
    judge: TestInlineJudge | None = None
    verify: list[VerifyCheck] | None = None


class TestRun(BaseModel):
    """What to run in the test."""

    __test__ = False  # Not a pytest test class
    message: str
    real_agents: list[str] = Field(default_factory=list)  # empty = all agents run for real


class TestDefinition(BaseModel):
    """A test definition -- combines sessions + run + evals."""

    __test__ = False  # Not a pytest test class
    name: str
    description: str = ""

    # Tag/category for UI filtering (live, replay, record_only)
    mode: str = "live"

    # World: sessions to seed
    sessions: list[str] = Field(default_factory=list)

    # Sessions with explicit mode
    seed_sessions: list[SeedSessionRef] = Field(default_factory=list)

    # What to run
    run: TestRun

    # HITL: single profile name, list of names, or inline config
    hitl: str | list[str] | HITLProfile | None = None

    # Judge: single or multiple profiles
    judge: str | None = None
    judges: list[str] | None = None

    # Evals with expected values
    evals: list[TestEvalRef] = Field(default_factory=list)

    # Inline evaluation (test-specific, not reusable)
    evaluate: TestInlineEvaluate | None = None

    def get_hitl_profiles(self) -> list[str]:
        """Normalize hitl field to list of profile names."""
        if self.hitl is None:
            return ["default"]
        if isinstance(self.hitl, str):
            return [self.hitl]
        if isinstance(self.hitl, list):
            return self.hitl
        return ["inline"]  # inline HITLProfile

    def get_judge_profiles(self) -> list[str]:
        """Normalize judge/judges to list of profile names."""
        if self.judges:
            return self.judges
        if self.judge:
            return [self.judge]
        return ["default"]


class TestFile(BaseModel):
    """Wrapper for test YAML files."""

    __test__ = False  # Not a pytest test class
    test: TestDefinition
