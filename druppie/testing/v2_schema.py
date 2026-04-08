"""Pydantic schemas for v2 testing framework.

Five concepts:
- Setup: session fixtures for world state (uses existing seed_schema.SessionFixture)
- Checks: reusable assertion + judge bundles (no correct answers)
- Tool tests: MCP tool call chains replayed through real services
- Agent tests: real LLM agent execution with assertions + judge
- Profiles: HITL simulator and judge configurations
"""
from __future__ import annotations

from pydantic import BaseModel, Field, ConfigDict


# --- Check Schema (was "Eval") ---


class CheckAssertion(BaseModel):
    """An assertion in a check definition. Tests provide expected values."""

    model_config = ConfigDict(populate_by_name=True)
    agent: str
    completed: bool | None = None
    tool: str | None = None  # e.g. "builtin:set_intent"
    result_valid: list[str] | None = None
    status: str | None = None
    error_contains: str | None = None
    error_matches: str | None = None


class CheckDefinition(BaseModel):
    """A check definition -- what to check, not what the correct answer is."""

    name: str
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    assert_: list[CheckAssertion] = Field(default_factory=list, alias="assert")
    judge: list[str] = Field(default_factory=list)


class CheckFile(BaseModel):
    """Wrapper for check YAML files."""

    check: CheckDefinition


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


# --- Verify Check ---


class VerifyCheck(BaseModel):
    """A side-effect verification check."""

    __test__ = False
    file_exists: str | None = None
    file_not_empty: str | None = None
    file_contains: dict | None = None
    file_matches: dict | None = None
    mermaid_valid: str | None = None
    git_branch_exists: str | None = None
    gitea_repo_exists: bool | None = None


# --- Shared: CheckRef (used by both tool and agent tests) ---


class CheckRef(BaseModel):
    """Reference to a check with expected values for this test."""

    __test__ = False
    model_config = ConfigDict(populate_by_name=True)
    check: str  # check name to reference
    expected: dict[str, object] = Field(default_factory=dict)


# --- Tool Test Schema ---


class ChainStepAssert(BaseModel):
    """Inline assertion on a specific chain step."""

    __test__ = False
    completed: bool | None = None
    result: list[str | dict] | None = None  # result validators


class ChainStep(BaseModel):
    """A single tool call in a tool test chain."""

    agent: str
    tool: str  # "builtin:set_intent", "coding:list_dir", etc.
    arguments: dict = Field(default_factory=dict)
    status: str = "completed"
    result: str | None = None
    error_message: str | None = None
    mock: bool = False  # force mock even if not blocklisted
    mock_result: str | None = None
    outcome: dict | None = None  # for execute_coding_task file creation
    assert_: ChainStepAssert | None = Field(default=None, alias="assert")


class ToolTestDefinition(BaseModel):
    """A tool test -- chain of tool calls replayed through real MCP."""

    __test__ = False
    name: str
    description: str = ""
    tags: list[str] = Field(default_factory=list)

    setup: list[str] = Field(default_factory=list)  # session IDs to seed (DB insert)
    extends: str | None = None  # another tool-test name to run first
    chain: list[ChainStep] = Field(default_factory=list)

    # Top-level assertions (in addition to inline assert on chain steps)
    assert_: list[CheckRef] | None = Field(default=None, alias="assert")
    verify: list[VerifyCheck] | None = None


class ToolTestFile(BaseModel):
    """Wrapper for tool-test YAML files."""

    __test__ = False
    tool_test: ToolTestDefinition = Field(alias="tool-test")


# --- Agent Test Schema ---


class TestInput(BaseModel):
    """A user-provided input field for manual tests."""

    __test__ = False
    name: str
    label: str = ""
    type: str = "text"
    required: bool = True
    default: str | None = None
    options: list[str] | None = None


class AgentTestDefinition(BaseModel):
    """An agent test -- real LLM agent execution with assertions + judge."""

    __test__ = False
    name: str
    description: str = ""
    tags: list[str] = Field(default_factory=list)

    # Manual input
    inputs: list[TestInput] = Field(default_factory=list)

    # Setup: session IDs to seed (DB insert)
    setup: list[str] = Field(default_factory=list)

    # Extend a tool test chain (runs before agent execution)
    extends: str | None = None

    # What to run
    message: str = ""
    agents: list[str] = Field(default_factory=list)

    # HITL: single profile name, list of names, or inline config
    hitl: str | list[str] | HITLProfile | None = None

    # Judge profiles
    judge_profile: str | None = None

    # Assertions (check references with expected values)
    assert_: list[CheckRef] = Field(default_factory=list, alias="assert")

    # Verify checks (Gitea side-effects)
    verify: list[VerifyCheck] | None = None

    # Inline judge checks (natural language, test-specific)
    judge: list[str] = Field(default_factory=list)

    @property
    def is_manual(self) -> bool:
        return len(self.inputs) > 0

    def resolve_inputs(self, values: dict[str, str]) -> "AgentTestDefinition":
        """Return a copy with {{placeholder}} replaced by provided values."""
        import copy

        def _replace(text: str) -> str:
            if not text:
                return text
            for key, val in values.items():
                text = text.replace(f"{{{{{key}}}}}", val)
            return text

        resolved = copy.deepcopy(self)
        resolved.message = _replace(resolved.message)
        resolved.description = _replace(resolved.description)
        return resolved

    def get_hitl_profiles(self) -> list[str]:
        """Normalize hitl field to list of profile names."""
        if self.hitl is None:
            return ["default"]
        if isinstance(self.hitl, str):
            return [self.hitl]
        if isinstance(self.hitl, list):
            return self.hitl
        return ["inline"]

    def get_judge_profiles(self) -> list[str]:
        """Normalize judge profile to list."""
        if self.judge_profile:
            return [self.judge_profile]
        return ["default"]


class AgentTestFile(BaseModel):
    """Wrapper for agent-test YAML files."""

    __test__ = False
    agent_test: AgentTestDefinition = Field(alias="agent-test")


# --- Backwards compat: keep old names as aliases for imports ---
# These will be removed once all callers are updated.

# Backwards compat aliases (used by v2_assertions, v2_runner, API routes)
EvalAssertion = CheckAssertion
EvalDefinition = CheckDefinition
EvalJudge = None  # removed, judge is now list[str] on CheckDefinition
EvalFile = CheckFile
TestDefinition = AgentTestDefinition
TestFile = AgentTestFile
TestEvalRef = CheckRef
SeedSessionRef = None  # removed, use setup list instead
TestRun = None  # removed, use message + agents directly
TestInlineEvaluate = None  # removed, use assert + judge + verify directly
TestInlineJudge = None  # removed
