# System Prompts

`druppie/agents/definitions/system_prompts/*.yaml` — four prompt snippets that most agents compose via their `system_prompts:` list.

## The four snippets

### `tool_only_communication.yaml`

- Agents communicate ONLY via tool calls.
- Never output plain text to the user.
- Use `hitl_ask_question` / `hitl_ask_multiple_choice_question` for user interaction.
- Do NOT include "Other" / "Anders" options in multiple choice — system auto-adds.
- Always call `done()` to complete.

Effect on behaviour: prevents agents from emitting free-form "Sure, I'll do that..." text before doing work. Combined with the loop's termination condition (`done` or max iterations), this enforces structured outputs.

### `summary_relay.yaml`

- Reads "PREVIOUS AGENT SUMMARY:" from the prompt (auto-prepended by the runtime).
- Accumulates all agent outputs across the session.
- Your summary line must be EXACTLY: `Agent <role>: <concrete details>`.
- Include actionable details: branch names, file paths, container names, URLs, port mappings, PR numbers.
- NEVER write vague summaries. "Task completed" breaks the pipeline — the next agent can't act on it.

Effect: makes the single-line `done(summary=…)` output the only inter-agent communication channel. Explicitness about format yields reliably parseable context.

### `done_tool_format.yaml`

- `done()` signals completion.
- `summary` argument is the ONLY inter-agent communication mechanism.
- Optional `next_agent` parameter for deterministic routing (bypasses Planner).
- Previous agent summaries are auto-prepended by the runtime — do not repeat them.

Effect: reminds agents about the structure of `done` and when to use `next_agent`. Planner-bypass routing (e.g. architect → build_classifier) is explicit via this.

### `workspace_state.yaml`

- The workspace is shared across all agents in the session.
- If a previous agent created a feature branch, you're already on it.
- Read "PREVIOUS AGENT SUMMARY" for the current branch name.
- Do NOT create a branch unless the task explicitly says so.

Effect: avoids double-branching. Many agents would otherwise "just to be safe" run `git checkout -b feature/xxx` at the start — this snippet prevents that.

## Composition

The agent YAML lists snippet names under `system_prompts:`:

```yaml
id: business_analyst
system_prompts:
  - tool_only_communication
  - summary_relay
  - done_tool_format
  - workspace_state
system_prompt: |
  You are a Business Analyst...
  (the agent-specific body follows)
```

At prompt-build time, snippets are concatenated (in declared order) and then the agent's own `system_prompt` body is appended. The composed string becomes the `role=system` message for every LLM call in this agent's run.

## Why YAML snippets

- Editable without code changes.
- Shared across agents — change one rule and every agent that includes the snippet gets it.
- Version-controlled — every historical change visible via git blame.

## Adding a new snippet

1. Create `druppie/agents/definitions/system_prompts/<name>.yaml`:
   ```yaml
   content: |
     The rules or preamble to inject.
   ```
2. Add `<name>` to the `system_prompts:` list of agents that should receive it.
3. Restart the backend — snippets are loaded once at startup (via `definition_loader.py`).

## Out-of-scope

There is no templating in snippets today. If an agent needs dynamic data in its system prompt, it goes in the `system_prompt` body (which is treated as a plain string) or in the `planned_prompt` that the planner writes per run.
