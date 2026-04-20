# Test Schemas

Pydantic models from `druppie/testing/schema.py` (330 lines). They validate YAML structure and provide typed access throughout the framework.

## Key models

### `ToolTestDefinition` (line 179)
```python
class ToolTestDefinition(BaseModel):
    name: str
    description: str | None
    tags: list[str] = []
    setup: list[SessionFixture] = []
    extends: str | None                    # merge chain from another test
    chain: list[ChainStep]
    session_status: str | None             # expected after chain
    pending_agents: list[str] | None
    assert_: list[CheckAssertion] = Field(alias="assert", default=[])
    verify: list[VerifyCheck] = []
    judge: JudgeConfig | None
```

### `AgentTestDefinition` (line 232)
```python
class AgentTestDefinition(ToolTestDefinition):
    message: str                           # user message
    agents: list[str]                      # BoundedOrchestrator halt condition
    hitl: str | list[str] | HITLProfile    # profile name / list / inline
    judge_profile: str = "default"
    inputs: list[InputDefinition] = []     # for manual parameterized tests
```

### `ChainStep` (line 154)
```python
class ChainStep(BaseModel):
    agent: str
    tool: str                              # e.g. coding:make_design, or builtin:done
    arguments: dict[str, Any] = {}
    mock: bool = False
    mock_result: dict | None
    outcome: dict | None                   # side effects when mocked
    execute: bool = True
    approval: Literal["approve", "reject"] | None
    assert_: list[CheckAssertion] = Field(alias="assert", default=[])
    planned_prompt: str | None
```

### `CheckAssertion` (line 18)
```python
class CheckAssertion(BaseModel):
    name: str | None
    ref: str | None                        # reference to testing/checks/*.yaml
    agent: str | None
    completed: bool | None
    tool: str | None                       # e.g. coding:make_design or *
    status: str | None
    error_contains: str | None
    error_matches: str | None              # regex
```

### `HITLProfile` (line 78)
```python
class HITLProfile(BaseModel):
    model: str
    provider: str
    prompt: str
    temperature: float = 0.2
```

### `JudgeProfile` (line 87)
```python
class JudgeProfile(BaseModel):
    model: str
    provider: str
    temperature: float = 0.0
```

### `JudgeConfig`
```python
class JudgeConfig(BaseModel):
    profile: str = "default"
    context: list[ContextSource] = []
    checks: list[JudgeCheck] = []
```

### `JudgeCheck`
```python
class JudgeCheck(BaseModel):
    name: str
    check: str                             # natural-language criterion
    context: list[ContextSource] = []      # per-check override
    expected: bool | None                  # for Judge Eval mode
```

### `VerifyCheck`
```python
class VerifyCheck(BaseModel):
    type: Literal["file_exists", "file_not_empty", "file_contains",
                  "file_matches", "mermaid_valid", "git_branch_exists",
                  "gitea_repo_exists"]
    path: str | None
    pattern: str | None
    regex: str | None
    branch: str | None
    repo: str | None
```

## Result types

### `AssertionResult`
```python
class AssertionResult(BaseModel):
    name: str
    passed: bool
    message: str | None
```

### `JudgeCheckResult`
```python
class JudgeCheckResult(BaseModel):
    check: str
    passed: bool
    reasoning: str
    source: Literal["check", "judge_eval"]
    raw_input: str
    raw_output: str
```

### `VerifyResult`
```python
class VerifyResult(BaseModel):
    type: str
    target: str
    passed: bool
    message: str | None
```

### `TestRunResult`
```python
class TestRunResult(BaseModel):
    status: Literal["passed", "failed", "error"]
    duration_ms: int
    session_id: UUID | None
    assertions_total: int
    assertions_passed: int
    judge_checks_total: int
    judge_checks_passed: int
    assertion_results: list[AssertionResult]
    verify_results: list[VerifyResult]
    judge_results: list[JudgeCheckResult]
    error: str | None
```

## Fixture schemas (`seed_schema.py`)

For seeding sessions from YAML before a test runs:

- `SessionFixture` — Session row
- `AgentRunFixture` — AgentRun rows
- `ToolCallFixture` — ToolCall rows with args + result
- `MessageFixture` — Message rows

Used by "setup" tool tests that build up state without exercising real agents.

## `fixture_uuid(name)` (`seed_ids.py`)

Deterministic UUIDv5 generator. `fixture_uuid("todo-app-project")` always returns the same UUID. Lets fixtures reference each other stably across runs.
