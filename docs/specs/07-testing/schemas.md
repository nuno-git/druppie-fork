# Test Schemas

Pydantic models from `druppie/testing/schema.py`. They validate YAML structure and provide typed access throughout the framework. The summaries below mirror the classes as they exist in code — field names, types, and defaults are quoted verbatim.

## Check models

### `CheckAssertion` (schema.py:18)
```python
class CheckAssertion(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    agent: str                               # required
    completed: bool | None = None
    tool: str | None = None                  # e.g. "builtin:set_intent"
    status: str | None = None
    error_contains: str | None = None
    error_matches: str | None = None
```

### `JudgeCheck` (schema.py:30)
```python
class JudgeCheck(BaseModel):
    check: str                               # natural-language criterion
    expected: bool | None = None             # None → LLM Judge mode; bool → Judge Eval mode
    # `from_value` accepts either a string (→ LLM Judge) or a dict (→ Judge Eval)
```

### `JudgeDefinition` (schema.py:48)
```python
class JudgeDefinition(BaseModel):
    context: str | list[str] = "all"         # "all" | agent_id | list of agent_ids
    checks: list[str | dict] = []
    def resolved_checks(self) -> list[JudgeCheck]
```

### `CheckDefinition` (schema.py:59)
```python
class CheckDefinition(BaseModel):
    name: str
    description: str = ""
    tags: list[str] = []
    assert_: list[CheckAssertion] = []       # alias="assert"
    judge: JudgeDefinition | list[str] | None = None   # legacy list-of-strings is accepted
```

### `CheckFile`
Wrapper keyed `check:` for YAML files under `testing/checks/`.

## Profile models

### `HITLProfile` (schema.py:78)
```python
class HITLProfile(BaseModel):
    model: str
    provider: str = "zai"
    prompt: str
    temperature: float = 0.3                 # default is 0.3, not 0.2
```

### `JudgeProfile` (schema.py:87)
```python
class JudgeProfile(BaseModel):
    model: str
    provider: str = "zai"
    # no temperature field
```

There is no class called `JudgeConfig` — `JudgeDefinition` (above) is what the YAML `judge:` block maps to.

## Verify / reference

### `VerifyCheck` (schema.py:109)
Flat, field-keyed verification — each field corresponds to a different check type. Only one is set per entry in practice.
```python
class VerifyCheck(BaseModel):
    file_exists: str | None = None           # path
    file_not_empty: str | None = None        # path
    file_contains: dict | None = None        # {path, text}
    file_matches: dict | None = None         # {path, regex}
    mermaid_valid: str | None = None         # path
    git_branch_exists: str | None = None     # branch name
    gitea_repo_exists: bool | None = None    # boolean toggle (not a repo name)
```

### `CheckRef` (schema.py:125)
```python
class CheckRef(BaseModel):
    check: str                               # referenced check name
    expected: dict[str, object] = {}         # per-test overrides
```

## Tool-test schema

### `ChainStepAssert` (schema.py:137)
```python
class ChainStepAssert(BaseModel):
    completed: bool | None = None
    result: list[str | dict] | None = None   # list of result validators
```

### `ChainStepApproval` (schema.py:145)
```python
class ChainStepApproval(BaseModel):
    status: str = "approved"                 # "approved" | "rejected"
    by: str | None = None                    # username of approver
    reason: str | None = None
```

### `ChainStep` (schema.py:154)
```python
class ChainStep(BaseModel):
    agent: str
    tool: str                                # e.g. "coding:make_design", "builtin:done"
    arguments: dict = {}
    status: str = "completed"                # default status recorded on the ToolCall row
    result: str | None = None
    error_message: str | None = None
    mock: bool = False
    mock_result: str | None = None
    outcome: dict | None = None              # for mocked execute_coding_task
    approval: ChainStepApproval | None = None
    assert_: ChainStepAssert | None = None   # alias="assert"; object, not a list
    planned_prompt: str | None = None        # set on the first step of an agent run
```

### `PendingAgent` (schema.py:173)
```python
class PendingAgent(BaseModel):
    id: str                                  # agent_id
    planned_prompt: str | None = None
```

### `ToolTestDefinition` (schema.py:179)
```python
class ToolTestDefinition(BaseModel):
    name: str
    description: str = ""
    tags: list[str] = []
    setup: list[str] = []                    # list of session IDs to seed
    extends: str | None = None               # another tool-test name to chain first
    chain: list[ChainStep] = []
    session_status: str | None = None        # override final session status
    pending_agents: list[PendingAgent] = []  # objects, not strings
    assert_: list[CheckRef] | None = None    # alias="assert"; list of CheckRef, not CheckAssertion
    verify: list[VerifyCheck] | None = None
    judge: JudgeDefinition | list[str] | None = None
```

### `ToolTestFile`
Wrapper keyed `tool-test:` (with the dash).

## Agent-test schema

### `TestInput` (schema.py:220)
```python
class TestInput(BaseModel):
    name: str
    label: str = ""
    type: str = "text"
    required: bool = True
    default: str | None = None
    options: list[str] | None = None
```

### `AgentTestDefinition` (schema.py:232)
`AgentTestDefinition` is NOT a subclass of `ToolTestDefinition`; it is its own model.
```python
class AgentTestDefinition(BaseModel):
    name: str
    description: str = ""
    tags: list[str] = []
    inputs: list[TestInput] = []             # for parameterised manual tests
    setup: list[str] = []                    # tool-test names to run first
    continue_session: bool = False           # reuse last setup session
    extends: str | None = None
    message: str = ""
    agents: list[str] = []                   # BoundedOrchestrator halt condition
    hitl: str | list[str] | HITLProfile | None = None
    judge_profile: str | None = None
    assert_: list[CheckRef] = []             # alias="assert"
    verify: list[VerifyCheck] | None = None
    judge: JudgeDefinition | list[str] | None = None
```

`agents` is the "halt-after" list consumed by `BoundedOrchestrator`. `hitl: None` → the runner falls back to the profile named `"default"`.

### `AgentTestFile`
Wrapper keyed `agent-test:` (with the dash).

## Result types

Result shapes live alongside the runners (`druppie/testing/judge_runner.py`, `druppie/testing/runner.py`) rather than in `schema.py`. The field set evolves quickly, so treat this section as indicative — consult the runner source for the authoritative layout.

### `JudgeCheckResult` (judge_runner.py)
Fields include `check`, `passed`, `reasoning`, `source` (string: `"check"` or `"inline"`), plus raw judge input/output for debugging.

### Test-run result (runner.py)
`TestRunner` assembles a result dict with overall status, duration, session_id, assertion/verify/judge sub-results, and any error. Refer to `runner.py` for the exact field names currently persisted to `test_runs` + `test_assertion_results`.

## Fixture schemas (`seed_schema.py`)

For seeding sessions from YAML before a test runs:

- `SessionFixture` — Session row
- `AgentRunFixture` — AgentRun rows
- `ToolCallFixture` — ToolCall rows with args + result
- `MessageFixture` — Message rows

Used by "setup" tool tests that build up state without exercising real agents. Note that `ToolTestDefinition.setup` holds a `list[str]` of session IDs (not `list[SessionFixture]` directly); the runner resolves IDs to fixtures elsewhere.

## `fixture_uuid(name)` (`seed_ids.py`)

Deterministic UUIDv5 generator. `fixture_uuid("todo-app-project")` always returns the same UUID. Lets fixtures reference each other stably across runs.
