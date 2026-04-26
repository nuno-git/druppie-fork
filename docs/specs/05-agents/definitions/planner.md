# planner

File: `druppie/agents/definitions/planner.yaml` (390 lines — largest system agent).

## Role

Execution orchestrator AND re-evaluator. The planner runs twice per session-iteration:
- **MODE 1 — INITIAL PLANNING.** After the router sets intent, the first planner run builds the initial agent plan.
- **MODE 2 — RE-EVALUATION.** After every non-planner agent completes, a new planner run re-reads the summary relay and decides what to run next.

## Config

| Field | Value |
|-------|-------|
| category | system |
| llm_profile | cheap |
| temperature | 0.1 |
| max_tokens | 16384 |
| max_iterations | 15 |
| builtin tools | `make_plan`, `done` |
| MCPs | none |
| system prompts | tool_only_communication, summary_relay, done_tool_format, workspace_state |

The planner has no MCPs — it reads intent + summary relay and decides. If it needs fresh info it routes the next agent to retrieve it.

## Mandatory agent sequences

### CREATE_PROJECT (STANDALONE)
```
business_analyst → architect → builder_planner → test_builder → builder → test_executor → deployer → summarizer
```
Between each, another planner run re-evaluates (except where the completing agent used `next_agent=`).

### UPDATE_PROJECT
```
developer (create feature branch)
  → business_analyst (assess if functional change or NO_FD_CHANGE)
  → architect (review existing vs new)
  → builder_planner
  → test_builder
  → builder
  → test_executor
  → deployer (preview: compose_project_name = "<project>-preview")
  → developer (create + merge PR)
  → deployer (final: stop preview, deploy to "<project>")
  → summarizer
```

### CORE_UPDATE
```
... → architect (DESIGN_APPROVED) → build_classifier → update_core_builder → architect (run 2 for module docs) → normal flow
```

## Re-evaluation logic

On each MODE 2 run:
- Read "PREVIOUS AGENT SUMMARY".
- Count recent TDD retries. If `test_executor` failed ≥ 3 times in a row → escalate via business_analyst with HITL.
- If architect emitted `DESIGN_FEEDBACK` (not `DESIGN_APPROVED`) → route back to business_analyst for revision.
- If `test_executor` reported PASS → proceed to deployer.
- If deployer asked HITL and got "changes needed" → route to developer for improvements, then loop.

## TDD retry ladder

When `test_executor` reports FAIL:
- Retry 1 — builder with specific feedback (what tests failed, suggested fixes).
- Retry 2 — builder with "rethink and rewrite" strategy.
- Retry 3 — builder with "simplify" strategy.
- Retry 4+ — business_analyst HITL escalation: "We couldn't get tests passing. Here's what we tried. How should we proceed?"

## Output format

Each run either:
- `make_plan(steps=[{agent_id, prompt}, ...])` — schedules the next N agents.
- `make_plan(steps=[])` + `done()` — when the pipeline is truly complete and summarizer has run. This makes the session COMPLETED.

A typical single re-evaluation step: plan the next agent + plan ANOTHER planner run after it. The pattern `[next_agent, planner]` is how the loop sustains itself.

## Deterministic bypass

The planner is bypassed entirely when:
- `architect` calls `done(next_agent="build_classifier")`.
- `build_classifier` calls `done(next_agent="builder_planner")` or `done(next_agent="update_core_builder")`.

These cases route directly, avoiding an unnecessary planner round-trip for deterministic decisions.
