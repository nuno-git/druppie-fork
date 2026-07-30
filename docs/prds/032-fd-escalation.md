---
id: "032"
title: FD Escalation
status: implemented
author: architect
date: 2026-07-29
supersedes: null
superseded_by: null
linked_adrs:
  - docs/adrs/038-fd-escalation-via-expert-hitl.md
linked_research: []
linked_specs:
  - docs/specs/030-fd-escalation.feature
linked_workitem: null
---

# PRD: FD Escalation

## Problem

When the architect agent repeatedly rejects a functional design (FD) with DESIGN_FEEDBACK, the BA and architect agents enter an infinite revision loop. There is no mechanism to break the deadlock — the agents will keep cycling without human intervention, wasting compute and blocking the project.

## Goal

After a configurable number of consecutive architect DESIGN_FEEDBACK rejections (default: 3), the system escalates to a human expert for a decision. The expert chooses one of four options: iterate (send feedback for another BA revision), ready (override and proceed to architecture), escalate (ask the architect human), or terminate (end the session). The escalation uses the existing `ask_expert_multiple_choice_question` HITL infrastructure, keeping the implementation minimal.

## User Journey

1. BA creates or revises a functional design.
2. Architect reviews and returns DESIGN_FEEDBACK.
3. Steps 1-2 repeat until the configurable threshold (default 3) is reached.
4. On the next BA completion, the planner agent calls `ask_expert_multiple_choice_question` with `expert_role="business_analyst"`.
5. A user with the `business_analyst` Keycloak role sees an escalation card in the session UI with four choices and an optional comment field.
6. The expert selects a single choice and optionally adds a comment.
7. The system routes accordingly: iterate sends to BA with expert's comment as primary directive, ready sends to architect with override, escalate asks the architect human, terminate ends the session.

## Constraints

- Must reuse existing `ask_expert_multiple_choice_question` infrastructure — no new endpoints, services, or database tables beyond what's strictly needed.
- Expert comment must be passed through to the receiving agent in all routing paths.
- Once escalation is triggered, all subsequent DESIGN_FEEDBACK cycles must go through expert escalation (sticky behavior).
- The `terminate_session` builtin tool must set session status to TERMINATED and cancel all pending runs.

## Out of Scope

- Notifications for escalation events (separate feature).
- Configurable escalation choices per agent definition.
- Audit trail beyond the existing question/answer records.

## Open Questions

None — all resolved during implementation.

## Linked Documents

- **ADRs:** [038 — FD escalation via expert HITL](../adrs/038-fd-escalation-via-expert-hitl.md)
- **Research:** none
- **Specs / Feature files:** [030 — FD escalation](../specs/030-fd-escalation.feature)
