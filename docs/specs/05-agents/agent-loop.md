# Agent Loop

`druppie/agents/loop.py` — the LLM+tool loop for a single agent run. Invoked by the orchestrator once per PENDING agent run.

## Responsibilities

1. Build the prompt (system prompt + summary relay + history + planned_prompt).
2. Resolve the LLM from the agent's profile.
3. Build the tools schema from ToolRegistry.
4. Iterate (up to `max_iterations`):
   - Call LLM.
   - Persist LlmCall row.
   - For each tool call → ToolExecutor.execute.
   - If any tool pauses the agent (approval, HITL, sandbox) → exit loop, agent run pauses.
   - If `done()` called → exit loop, agent run COMPLETED.
5. On max iterations without done → FAILED.

## Prompt construction

Order of concatenation:

```
1. <system_prompts composed>           ← see system-prompts.md
2. <agent.system_prompt body>           ← from agent YAML
3. PREVIOUS AGENT SUMMARY:
     Agent router: … (from done())
     Agent planner: …
     Agent business_analyst: …
4. Recent conversation (limited window)
     user: <original user message>
     tool results / hitl answers interleaved
5. planned_prompt                       ← from current run
```

The "Summary Relay" (step 3) is accumulated across all completed agent runs for the session and pre-pended to every subsequent agent's prompt. This is how agents coordinate without a shared memory — each writes exactly one line per `done()`, and future agents read them all.

## LLM resolution

`druppie/llm/resolver.py:resolve_llm(profile_name)`:

1. Load `llm_profiles.yaml`.
2. For each provider in the profile's ordered chain:
   - Check if the env vars for that provider are set.
   - If yes, construct the primary LLM client.
   - Break.
3. If another provider later in the chain also has keys, construct it as a `FallbackLLM` — if primary fails, fallback is invoked.
4. Return the wrapped client.

## LLM call

`druppie/llm/service.py:call_llm(messages, tools, model_config)`:

- Via LiteLLM to unify providers under one API.
- Max 3 retries with exponential backoff (0.5s, 1s, 2s) on transient errors.
- Each retry persisted to `llm_retries` table.
- Final outcome → one `llm_calls` row (with `retries` eager-loadable).

Token counting: LiteLLM returns `prompt_tokens`, `completion_tokens`; stored directly.

## Tool call parsing

LLMs return tool calls in a provider-specific shape that LiteLLM normalises to OpenAI's:
```json
[{
  "id": "call_xxx",
  "type": "function",
  "function": {"name": "coding_write_file", "arguments": "{\"path\": \"…\", \"content\": \"…\"}"}
}]
```

For each:
1. Parse arguments JSON.
2. Map `name` → `(server, tool)` — the convention is `<server>_<tool>` for MCP (e.g. `coding_write_file`) and bare name for builtins.
3. Create a `ToolCall` row linked to the `LlmCall`.
4. Invoke `ToolExecutor.execute(tool_call_id)`.
5. If the tool completed, append a `Message(role=tool, content=<result>, tool_call_id=<id>)` — this is what the LLM sees on its next iteration.

## Iteration termination

- `done()` called → loop exits, agent run COMPLETED.
- Any tool returns a paused status (`WAITING_APPROVAL`, `WAITING_ANSWER`, `WAITING_SANDBOX`) → loop exits, agent run status mirrors the tool.
- `iteration_count >= agent.max_iterations` → loop exits, agent run FAILED with "Max iterations reached" in `error_message`.
- Unhandled exception → agent run FAILED, exception logged.

## Max iterations per agent

From YAML defaults:
- router, planner, build_classifier, summarizer: 5–15
- business_analyst, architect: 50 (long deliberations)
- builder_planner, test_builder, test_executor: 25–30
- builder, developer, deployer, update_core_builder: 100 (TDD retry loops)
- reviewer: 50

A generous `max_iterations` is not a performance problem because each iteration requires a tool call + response cycle. Agents that want to do nothing call `done()` almost immediately.

## Context window management

`druppie/agents/message_history.py` truncates conversation history when approaching context limits. Strategy:
- Always keep system prompt + summary relay + planned_prompt.
- Drop oldest tool_call results first.
- Never drop the user's original message.

This is coarse — no embedding-based retrieval — but works because agents are narrow and their prompts are designed not to require long-term memory of tool results.
