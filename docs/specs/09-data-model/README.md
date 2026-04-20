# 09 — Data Model

Cross-cutting view of the persisted data: every entity, its relationships, lifecycle state machines. See `02-backend/db-models.md` for per-column schema; this folder focuses on *how entities relate* and *how they move through state*.

## Files

- [entities.md](entities.md) — Entity list with their aggregates
- [relationships.md](relationships.md) — FK diagrams, cardinalities
- [session-lifecycle.md](session-lifecycle.md) — Session status state machine
- [agent-run-lifecycle.md](agent-run-lifecycle.md) — AgentRun state transitions
- [tool-call-lifecycle.md](tool-call-lifecycle.md) — ToolCall status flow
- [approval-question-lifecycle.md](approval-question-lifecycle.md) — Approvals + Questions
- [evaluation-entities.md](evaluation-entities.md) — BenchmarkRun, TestRun, assertion results
