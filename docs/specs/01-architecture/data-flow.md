# Data Flow

Five canonical request lifecycles. Each lists the HTTP entry, the background work it spawns, the persistence side-effects, and how the UI reflects the result.

## 1. User message → agent pipeline

```
Frontend                 Backend                     Agent runtime                MCP servers
────────                 ───────                     ─────────────                ────────────
POST /api/chat
  {message, session_id?}
                   ►  chat.py:send_chat
                      ├ create/fetch Session
                      ├ save user Message
                      ├ create router + planner PENDING runs
                      ├ spawn background task
                      ◄ 202 {session_id, status: active}
◄── poll GET /api/sessions/{id}
                        orchestrator.process_message
                          loop over PENDING runs
                           ├ build prompt (history + summary relay)
                           ├ LLM call ────────────────────────────────►
                           │                                            (zai/deepinfra/…)
                           ◄── response (tool calls)
                           │ for each tool call:
                           │   tool_executor.execute(tc_id)
                           │   ├ approval check → create Approval, PAUSE
                           │   ├ HITL tool   → create Question, PAUSE
                           │   └ MCP call ───────────────────────────►
                           │                                            (module-coding:9001 etc.)
                           │                                          ◄──
                           │ if done() called → agent completes
                           │ planner re-evaluates → may create more PENDING runs
                          end loop → Session.status = COMPLETED | PAUSED_* | FAILED
◄── session detail, timeline, approvals, questions
```

Key persistence writes per agent iteration:
- one `LlmCall` row with full `request_messages`, `response_tool_calls`, tokens, duration.
- N `ToolCall` rows (one per tool call in the response) linked to the LlmCall.
- possibly: `Approval`, `Question`, `Message` rows.

When all PENDING runs finish (planner makes no new plan), the session transitions to `COMPLETED` and the user sees the `summarizer`'s `create_message` output in the timeline.

## 2. Approval resolution

```
POST /api/approvals/{id}/approve         (role check: user has required_role or is session_owner)
  ► ApprovalService.approve
    ├ SELECT … FOR UPDATE on Approval
    ├ UPDATE status = APPROVED, resolved_by, resolved_at
    ├ commit
    ◄ 200 {approval, message}
  ► background task: _resume_workflow_after_approval
    ├ orchestrator.resume_after_approval(tool_call_id)
    │   ├ execute the approved MCP tool
    │   ├ write tool result to ToolCall.result
    │   └ resume the agent (call done loop again)
    └ session transitions back to ACTIVE, then to its next paused state
```

Key detail: the **fast phase** (HTTP response) only writes to the approvals table. The **slow phase** (background) executes the tool. If the backend crashes between these two, the session is left in `PAUSED_APPROVAL` with an approved approval — the watchdog does not currently auto-resume this case; the user must click Resume.

## 3. HITL answer

Same two-phase pattern as approvals, differing only in what resumes:

```
POST /api/questions/{id}/answer {answer, selected_choices?}
  ► QuestionService.answer (session owner check)
    ├ UPDATE answer, answered_at, status = ANSWERED
    ◄ 200
  ► background task: orchestrator.resume_after_answer
    ├ the HITL tool call result is the user's answer (text or display string)
    ├ agent continues its loop with the answer in its LLM context
```

Choices are stored as `choices: JSON` (array of `{text}`) and `selected_indices: JSON` (array of integers). The agent sees the rendered answer, not the raw indices.

## 4. Sandbox webhook

Sandboxes are spawned by the builtin `execute_coding_task` tool, which internally calls the sandbox control plane over HTTP. The agent's tool call is parked in `WAITING_SANDBOX` status. When the sandbox finishes, the control plane calls Druppie:

```
sandbox control plane                Druppie backend
──────────────────────                ──────────────
POST /api/sandbox-sessions/{sid}/complete
  X-Druppie-Signature: hmac256(body, webhook_secret)
  body: {sandbox_session_id, completed_at, reason, artifacts…}
                               ►  sandbox.py:sandbox_complete_webhook
                                  ├ verify HMAC (constant-time)
                                  ├ lock tool_call FOR UPDATE (idempotency)
                                  ├ fetch events from control plane /sessions/{sid}/events
                                  ├ extract:
                                  │   _extract_changed_files()
                                  │   _extract_git_operations()
                                  │   _extract_agent_output()   (strip <think> tags)
                                  │   _extract_tool_results_summary()
                                  ├ build agent_result_text (human-readable)
                                  ├ UPDATE tool_call.status = COMPLETED, .result
                                  ├ UPDATE sandbox_session.events_snapshot, completed_at
                                  ├ insert ProjectDependency rows
                                  ├ spawn resume task if agent_run.status = PAUSED_SANDBOX
                                  ◄ 200
```

Watchdog (`sandbox_watchdog_loop`, every 5 min): any tool call in `WAITING_SANDBOX` older than `SANDBOX_TIMEOUT_MINUTES` (default 30) is marked `FAILED`. The parent agent run and session transition to `FAILED`. The user can retry from that run via `POST /api/sessions/{id}/retry-from/{run_id}`.

## 5. Evaluation run

```
POST /api/evaluations/run-tests
  body: {test_names?: [], tag?: "", run_all?: false, execute?: true, judge?: true, input_values?: {}}
  ► evaluations_tests.py
    ├ create TestBatchRun (status = running)
    ├ enqueue test on a ThreadPoolExecutor
    ◄ 202 {batch_id}
◄── poll GET /api/evaluations/run-status/{batch_id}
      returns {status, current_test, completed, total}

              per-test thread:
              ─────────────────
              TestRunner.run_test
                ├ create BenchmarkRun
                ├ create test user in Keycloak + Gitea
                ├ _run_tool_test OR _run_agent_test
                │   ├ setup: run fixture tool tests in same session
                │   ├ replay: for each ChainStep → real MCP call OR mock
                │   ├ assertions: result_validators, completed/tool/status checks
                │   ├ verify: Gitea side-effect checks (file_exists, etc.)
                │   └ judge: LLM judge checks on agent trace
                ├ write TestRun + N TestAssertionResult rows
                └ update TestBatchRun progress
```

Analytics views (`Analytics.jsx`, `/api/evaluations/analytics/*`) aggregate `TestAssertionResult` rows by agent, tool, eval name, test, and filter by batch. See `07-testing/` for the full data model.

## Transaction boundaries

| Action | Transaction shape |
|--------|-------------------|
| HTTP request to service method | one transaction, commit at method end |
| `lock_for_retry` / `lock_for_resume` | SELECT FOR UPDATE → UPDATE → commit in a single txn |
| Background task | opens its own session in `run_session_task`, commits after each agent iteration |
| Sandbox webhook | SELECT FOR UPDATE on tool_call → update → commit — only then spawn resume task |
| Approval resolution | phase 1 commits before phase 2 starts; phase 2 has its own txn |

Guarantees the system leans on:
- PostgreSQL row locks for concurrent writers.
- SQLAlchemy's default isolation (READ COMMITTED).
- Idempotent webhooks via "already completed → noop" check under the row lock.

Guarantees the system does NOT provide:
- Distributed transactions across MCP calls. If `docker compose_up` partially succeeds (containers started, DB row not written), the containers are orphaned and a manual `docker compose_down` is required. The `druppie.*` labels on containers enable later cleanup via the `/api/deployments` list endpoint.
