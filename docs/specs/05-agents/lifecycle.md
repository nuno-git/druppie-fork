# Agent Lifecycle

From user message to final summary. All durations are approximate and depend on the LLM provider.

## 1. Create session

`POST /api/chat` with `{message, session_id?}`. If no session_id, a new `Session` is created with:
- `user_id` from Keycloak.
- `project_id` from the request body (or None → `general_chat` path).
- `title` = first ~80 chars of the message.
- `status = ACTIVE`.

The user message is persisted as a `Message(role=user)`.

## 2. Seed router + planner

Two `PENDING` agent runs are inserted:
1. `router` — will classify intent.
2. `planner` — will build the real execution plan after the router.

## 3. Background task starts

`orchestrator.process_message()` is queued via `add_task`. It runs in a fresh DB session and operates the following loop:

```
while session.status == ACTIVE and has_pending_runs(session_id):
    run = next_pending_run(session_id)
    run.status = RUNNING
    agent_loop(run)          # runs the LLM + tool loop
    # loop.py marks run.status COMPLETED or PAUSED_* or FAILED
```

## 4. Agent loop (per agent)

`druppie/agents/loop.py:run()`:

1. Build messages from:
   - Agent's system prompt (from YAML + composed system_prompt snippets).
   - Summary Relay — prior agent's `done()` summary prepended.
   - Recent conversation history (user messages + tool results).
   - The agent's `planned_prompt`.
2. Resolve LLM from profile (`llm_profiles.yaml`) + env-configured API keys.
3. Get tool schemas from `ToolRegistry.get_tools_for_agent(agent.mcps, agent.builtin_tools)`.
4. Iterate up to `max_iterations`:
   - Call LLM with messages + tools.
   - Persist `LlmCall` row (request_messages, response_content, response_tool_calls, tokens).
   - For each tool call in the response → `ToolExecutor.execute(tool_call_id)`.
   - If a tool call returned `status=WAITING_APPROVAL` or `WAITING_ANSWER` or `WAITING_SANDBOX` → pause the run, break the loop.
   - If `done()` was called → mark run COMPLETED, break.
5. On max iterations without `done()` → mark run FAILED.

## 5. Planner re-evaluation

After each non-planner agent completes, the orchestrator adds a new PENDING `planner` run (unless the previous agent used `next_agent=` for deterministic routing). The planner re-reads the summary relay and makes the next plan — or calls `done()` indicating the pipeline is finished.

## 6. Terminal states

- **COMPLETED** — the planner issues `done()` without calling `make_plan` again, meaning there's nothing left.
- **FAILED** — any agent exceeds `max_iterations` without `done()`, or crashes.
- **PAUSED_APPROVAL / PAUSED_HITL / PAUSED_SANDBOX** — waiting for external input.
- **PAUSED_CRASHED** — set by startup recovery when a RUNNING run has no live task.

## 7. Resumption

On approval / HITL answer / sandbox webhook:
1. The external event updates its entity (approval → APPROVED, question → ANSWERED, sandbox_session → completed with events).
2. A background task resumes the orchestrator for that session.
3. The paused agent run's loop continues from where it left off:
   - For approvals: the approved tool is executed; result fed back to the agent.
   - For HITL: the answer becomes the tool result; agent continues.
   - For sandbox: the extracted result text becomes the tool result; agent continues.
4. The agent may make more LLM calls, then `done()`, or pause again.

## 8. Summarizer

The planner's final act in a successful pipeline is to schedule the `summarizer` agent. Summarizer:
- Reads the summary relay (all prior agents' `done()` outputs).
- Calls `create_message(content=…)` — this inserts a user-facing `Message(role=assistant, agent_id=summarizer)` into the timeline.
- Calls `done()`.

After the summarizer completes, the planner has no more plan → session is `COMPLETED`.

## 9. Retry and revert

`POST /api/sessions/{id}/retry-from/{agent_run_id}`:
1. `WorkflowService.revert_session_to_run()` — deletes agent runs, LLM calls, tool calls, messages with `sequence_number > target`.
2. `RevertService` — calls `_internal_revert_to_commit` on the workspace to get git back to the pre-target state.
3. New PENDING run inserted for the target agent with an optional override `planned_prompt`.
4. Background task resumes the orchestrator — effectively runs the agent again with a (possibly) different prompt.

## 10. Cancel

`POST /api/chat/{session_id}/cancel` sets `session.status = PAUSED`. The running background task checks this at each iteration and exits cleanly. Tool calls mid-flight may still complete (docker containers, LLM requests, file writes), but no new ones are issued.

## 11. Crash recovery

Covered in `02-backend/startup.md`. Briefly: zombie `ACTIVE` sessions → `PAUSED_CRASHED`, zombie `running` batches → `failed`. User can Resume a paused-crashed session to retry.
