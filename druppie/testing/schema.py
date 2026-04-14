"""Pydantic schemas for testing framework.

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


class JudgeCheck(BaseModel):
    """A single judge check with optional expected outcome."""

    check: str  # natural language check description
    expected: bool | None = None  # None = LLM Judge (verdict is result), bool = Judge Eval (testing the judge)

    @property
    def is_eval(self) -> bool:
        """True when we're evaluating the judge itself (expected was explicitly set)."""
        return self.expected is not None

    @classmethod
    def from_value(cls, v):
        if isinstance(v, str):
            return cls(check=v, expected=None)  # LLM Judge — no expected
        return cls(**v)  # Judge Eval — has expected


class JudgeDefinition(BaseModel):
    """Judge configuration — what context the LLM judge sees and what to check."""

    context: str | list[str] = "all"  # "all", "business_analyst", or ["business_analyst", "architect"]
    checks: list[str | dict] = Field(default_factory=list)

    def resolved_checks(self) -> list[JudgeCheck]:
        """Resolve checks to JudgeCheck objects (handles string shorthand)."""
        return [JudgeCheck.from_value(c) for c in self.checks]


class CheckDefinition(BaseModel):
    """A check definition -- what to check, not what the correct answer is."""

    name: str
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    assert_: list[CheckAssertion] = Field(default_factory=list, alias="assert")
    judge: JudgeDefinition | list[str] | None = None  # new format or legacy list


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


class ChainStepApproval(BaseModel):
    """How to handle approval for a tool call that requires it."""

    __test__ = False
    status: str = "approved"  # "approved" or "rejected"
    by: str | None = None  # username of approver (defaults to test user)
    reason: str | None = None  # rejection reason


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
    approval: ChainStepApproval | None = None  # how to handle approval gate
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

    # Judge checks — LLM evaluates quality
    judge: JudgeDefinition | list[str] | None = None


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

    # Setup: tool test names to run first (each creates a session)
    setup: list[str] = Field(default_factory=list)

    # Continue the last setup session instead of creating a new one
    # When true, the message is sent as a continuation of the setup session
    continue_session: bool = False

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

    # Inline judge checks — new format (JudgeDefinition) or legacy (list of strings)
    judge: JudgeDefinition | list[str] | None = None

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


