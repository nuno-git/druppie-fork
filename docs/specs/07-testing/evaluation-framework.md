# Evaluation Framework

Modules under `druppie/testing/`. The framework owns test execution, orchestration bounding, replay, HITL simulation, judge running, and result persistence.

## Modules

| File | Role |
|------|------|
| `runner.py` (773 lines) | TestRunner — executes tool and agent tests |
| `bounded_orchestrator.py` (231 lines) | Halts orchestrator after specified agents complete |
| `hitl_simulator.py` (281 lines) | LLM persona answers HITL questions & approvals |
| `session_transcript.py` (133 lines) | Builds transcript from DB for simulator context |
| `replay_executor.py` (400+ lines) | Executes tool call chains through real MCP |
| `schema.py` (330 lines) | Pydantic schemas for test definitions |
| `assertions.py` (250+ lines) | Matches assertions against agent runs |
| `result_validators.py` | Inline validators for tool call results |
| `verifiers.py` (300+ lines) | Gitea side-effect checks |
| `judge_runner.py` (175 lines) | LLM judge execution |
| `eval_judge.py` (150+ lines) | v1 evaluation engine |
| `eval_context.py` (209 lines) | Extract context for judge/eval |
| `loaders.py` (142 lines) | YAML loaders (profiles, checks, tests) |
| `eval_schema.py` | v1 evaluation schema |
| `seed_schema.py` | DB seeding fixtures |
| `seed_ids.py` | Deterministic UUID generation |
| `eval_config.py` | evaluation_config.yaml loader |
| `eval_live.py` | Live evaluation mode |
| `utils.py` | Git info, judge call helpers, JSON parsers |

## `TestRunner.run_test(test_def, options)`

Entry point for a single test. Returns `TestRunResult` with status, duration, assertion counts.

### Tool test flow
1. Create `BenchmarkRun` row.
2. Create test user in Keycloak + Gitea (per-user isolation).
3. Merge extended setup chain with the test's own chain.
4. Run chain via `replay_executor._execute_real(tool_call)` for real steps, mocks for marked ones.
5. Run inline assertions per step (result validators, completed check).
6. Run top-level assertions (tool call matching, status checks).
7. Run verify checks (Gitea file_exists, file_contains, etc.).
8. Run judge checks (LLM evaluation on agent trace).
9. Write `TestRun` + N `TestAssertionResult` rows.
10. Return result.

### Agent test flow
1. Create `BenchmarkRun` row.
2. Create test user.
3. Run setup tool chain (same as tool test setup).
4. Call `_execute_agents(message, real_agents, hitl_profile, ...)`:
   - Wraps real Orchestrator in `BoundedOrchestrator`.
   - Registers HITL callback → `HITLSimulator.answer(transcript)`.
   - Runs orchestrator; halts when all `real_agents` are COMPLETED.
5. Run assertions + judge.
6. Write result rows.

## `BoundedOrchestrator`

Halts execution after a configured set of agents completes. Lets agent tests exercise only the relevant pipeline segment (e.g. `[router, planner, business_analyst]`) without running deployer / summarizer.

Flow:
```python
while True:
  await orchestrator._execute_one_iteration()
  if all_real_agents_done(real_agents):
    cancel_remaining_pending_runs()
    break
  if wall_clock > 10min:
    raise TimeoutError
```

## `HITLSimulator`

Instantiated with a `HITLProfile` (model, provider, temperature, prompt). Each time an agent pauses on HITL or approval:

1. `session_transcript.build_transcript(session_id, exclude_current_pending=True)` — builds a text history.
2. Simulator calls its LLM with:
   - System prompt = profile's persona ("You are a non-technical product manager…").
   - User message = transcript + the current question.
3. LLM returns an answer (text for free-form, choice index for MCQ, approve/reject for approval).
4. Simulator updates the DB (answer row or approval decision) and resumes the orchestrator.

`MAX_HITL_INTERACTIONS = 100` — safety cap.

## `ReplayExecutor`

For tool tests. Each `ChainStep` is either:
- **Real** (`execute: true`) — calls the actual MCP tool through `ToolExecutor`.
- **Mocked** (`execute: false` or `mock: true`) — returns `mock_result` from the YAML.

Uses a thread lock `_gitea_singleton_lock` when resetting the Gitea client for isolation.

## Judge runner

`JudgeRunner.run_checks(checks, session_id, agent_context_filter)`:
1. `_extract_agent_trace(session_id, agent_filter)` — get tool calls, messages, LLM calls for the filtered agents.
2. For each check: call the judge LLM with check text + extracted context.
3. Parse verdict (PASS/FAIL + reasoning).
4. Return `JudgeCheckResult` with raw input/output for debugging.

Two modes:
- **LLM Judge** — check has natural-language criterion; judge's verdict is the result.
- **Judge Eval** — check has an `expected: bool`; this tests whether the judge itself is reliable by comparing its verdict to expected. Used to validate the judge setup.

## Context extraction

`eval_context.extract_context(context_sources, session_id, agent_run_id?)`:

Extractors registered in `_EXTRACTORS`:
- `all_tool_calls` — every tool call in session (or limited by agent).
- `session_messages` — message history.
- `agent_definition` — fields from agent YAML (`system_prompt`, `mcps`, etc.).
- `tool_call_result` / `tool_call_arguments` — specific tool call data.

Each judge check declares which sources it needs, keeping the context window focused.

## Storage

All results write to:
- `benchmark_runs` — one per test batch.
- `test_runs` — one per test.
- `test_assertion_results` — one per assertion / verify / judge check.
- `test_batch_runs` — batch-level status for UI polling.
- `test_run_tags` — tags for filtering.

Analytics layer queries these tables for the Analytics page.
