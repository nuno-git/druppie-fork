---
id: "038"
title: Use existing expert HITL tools for FD escalation
status: accepted
date: 2026-07-29
deciders:
  - architect
  - product_owner
supersedes: null
superseded_by: null
linked_prd: docs/prds/032-fd-escalation.md
linked_research: null
---

## Context

When the architect agent repeatedly rejects a functional design with DESIGN_FEEDBACK, the BA and architect agents enter an infinite revision loop. A prior implementation (PR 302, ~4,500 lines) built parallel infrastructure: new session statuses (`PAUSED_BA_HITL`, `PAUSED_ARCHITECT_HITL`), an `EscalationService` with RBAC, four new API endpoints, an `escalation_events` audit table, and custom UI cards (`BAHitlCard`, `ArchitectHitlCard`). This duplicated existing capabilities already provided by the `ask_expert_multiple_choice_question` builtin tool, which routes structured multiple-choice questions to users by Keycloak role with full authentication and audit.

## Decision

Implement FD escalation using the existing `ask_expert_multiple_choice_question` infrastructure. The planner agent calls `ask_expert_multiple_choice_question` when the `fd_rejection_count` on the session reaches the `escalation_threshold` configured on the architect agent definition. A code-level orchestrator override ensures reliable routing by overwriting the pending planner's `planned_prompt` when the BA completes after threshold. The existing HITL question/answer flow handles authentication, role-based routing, and persistence. A new `terminate_session` builtin tool and `TERMINATED` session status handle the termination path. Total implementation: ~564 lines across 12 files, replacing ~4,500 lines.

## Consequences

**Positive:**
- Minimal code surface: ~564 lines instead of ~4,500, reducing maintenance burden and attack surface.
- Reuses battle-tested HITL infrastructure for authentication, role-based routing, and question persistence.
- Expert comments flow through all routing paths, giving receiving agents actionable context.
- Sticky escalation prevents agents from reverting to the infinite loop.

**Negative:**
- The orchestrator override (`_on_agent_completed`) adds coupling between the orchestrator and the planner's prompt format.
- The planner YAML prompt for escalation handling is complex and relies on the LLM correctly parsing the four choice paths.
- No dedicated audit table — escalation events are tracked via question/answer records, which is adequate but less queryable than a purpose-built table.
