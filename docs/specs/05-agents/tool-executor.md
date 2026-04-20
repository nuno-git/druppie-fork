# Tool Executor

`druppie/execution/tool_executor.py` — responsible for every tool call an agent makes. Handles classification (builtin vs MCP), approval gating, HITL creation, argument injection/validation, dispatch, and result persistence.

## Entry point

```python
async def execute(self, tool_call_id: UUID) -> ToolCallStatus:
    tool_call = self.repo.get_by_id(tool_call_id)
    ...
```

Returns the final status: `COMPLETED`, `FAILED`, `WAITING_APPROVAL`, `WAITING_ANSWER`, `WAITING_SANDBOX`.

## Sets of tools

```python
BUILTIN_TOOLS = {
    "done", "make_plan", "set_intent",
    "hitl_ask_question", "hitl_ask_multiple_choice_question",
    "create_message", "invoke_skill",
    "execute_coding_task", "test_report",
}

HITL_TOOLS = {"hitl_ask_question", "hitl_ask_multiple_choice_question"}

LONG_RUNNING_TOOLS = {
    ("coding", "run_tests"): 1200,
    ("coding", "install_test_dependencies"): 1200,
    ("docker", "compose_up"): 1200,
}
```

Default timeout for everything else: 60 s.

## Execution sequence

```
1. Fetch ToolCall row (status must be PENDING).
2. If tool is a HITL tool:
     create Question record
     tool_call.status = WAITING_ANSWER
     return WAITING_ANSWER
3. If tool requires approval (per MCPConfig + agent overrides):
     create Approval record
     tool_call.status = WAITING_APPROVAL
     return WAITING_APPROVAL
4. If tool is "execute_coding_task":
     invoke sandbox flow → tool_call.status = WAITING_SANDBOX
     return WAITING_SANDBOX
5. If tool is another builtin:
     execute in-process
     store result
     tool_call.status = COMPLETED
6. Else (MCP tool):
     inject standard args (session_id, project_id, …)
     validate args (with normalization fallback)
     HTTP POST to <server>/v1/mcp with the tool call
     parse response
     store result
     tool_call.status = COMPLETED or FAILED
```

## Argument injection

Implemented by `MCPConfig.apply_injections(tool_name, arguments, context)`:

```python
for rule in self.injection_rules.get(mcp_id, []):
    if not rule.applies_to_tool(tool_name):
        continue
    value = navigate(context, rule.from_path)      # e.g. context.session.id
    if value is None:
        continue
    arguments[rule.param] = value
```

Context object is built fresh for each call:
```python
context = Context(
    session=session_domain_model,
    project=project_domain_model_or_None,
    user=user_domain_model,
)
```

Hidden params are dropped from the schema sent to the LLM earlier (in `ToolRegistry.to_openai_format`). Injection happens after the LLM has decided to call — i.e. the LLM never sees nor supplies them.

## Argument validation

`ToolDefinition.validate_arguments(args)` returns `(is_valid, error, validated_args, normalized_args)`:

1. Try JSON schema validation on args as given.
2. If valid → return validated args.
3. If invalid, normalize:
   - `"null"` → None
   - `"none"` → None
   - `"undefined"` → None
   - `"{}"` → `{}`
   - `"[]"` → `[]`
   - `"true"` / `"false"` → booleans
   - Remove keys not in schema.
4. Try validation again with normalized args.
5. If still invalid → fail the tool call with the validation error.
6. Persist any normalization to `tool_call_normalizations` for debugging.

## Builtin tool handlers

Each has a dedicated handler in `tool_executor.py` (or the orchestrator for ones with side effects on the session):

- `done(summary, next_agent?)` — mark the agent run COMPLETED, append summary for the relay. If `next_agent` given, enqueue that agent directly (bypassing planner).
- `make_plan(steps)` — insert new PENDING agent runs for each `{agent_id, prompt}` in `steps`.
- `set_intent(intent, project_id?, project_name?)` — update session intent; if create_project + project_name, create Project + Gitea repo; update planner's planned_prompt.
- `hitl_ask_question(question, context?)` — create Question with type=text.
- `hitl_ask_multiple_choice_question(question, choices, context?)` — create Question with type=single_choice or multiple_choice. Note: system auto-appends "Other" choice unless already present.
- `create_message(content)` — insert Message(role=assistant, agent_id=summarizer, content).
- `invoke_skill(skill_name)` — read `druppie/skills/{skill_name}/SKILL.md`, return its body. Agent then has the instructions in its context.
- `execute_coding_task(task, agent?, repo_target?)` — kick off a sandbox. Tool call stays WAITING_SANDBOX until the webhook fires.
- `test_report(iteration, tests_passed, summary, …)` — structured report, used by test_executor to standardise PASS/FAIL reporting.

## HTTP client

`druppie/execution/mcp_http.py:MCPHttp` — simple wrapper around `httpx.AsyncClient`. Each call:
- POST to `<server_url>/v1/mcp`.
- Body: JSON-RPC 2.0 envelope with `method=tools/call, params={name, arguments}`.
- Headers: `Content-Type: application/json`.
- Timeout from `LONG_RUNNING_TOOLS` map or default.

Errors:
- HTTP non-2xx → tool_call.status = FAILED, error_message = body.
- Timeout → FAILED with timeout message.
- JSON parse failure → FAILED.

## Sandbox path

When `execute_coding_task` is called:
1. Register ownership with `POST /api/sandbox-sessions/internal/register` (on Druppie itself) to create a `SandboxSession` row with a fresh webhook_secret.
2. Call the sandbox control plane to create the sandbox, passing the webhook URL + secret.
3. Return from the tool handler with `status = WAITING_SANDBOX`.
4. When the webhook arrives later, the orchestrator resumes the agent run.

Ownership tracking is essential — the webhook URL is public by necessity (HTTPS endpoint on Druppie), so the HMAC secret + session scoping protect against forged completions.
