---
id: "010"
title: "Approval Workflow System"
status: approved
author: nuno
date: 2026-07-16
supersedes: null
superseded_by: null
linked_adrs: ["docs/adrs/010-layered-approval-model.md"]
linked_research: []
linked_specs: []
---

# PRD: Approval Workflow System

> **Where this fits:** This PRD describes the **product** experience of the
> human-in-the-loop approval system — what users can do with it and what "good"
> looks like. The architectural decision (two-layer model, global defaults +
> per-agent overrides, role-based authorization) lives in ADR 010. This document
> does not duplicate that architecture; it states the problem and the goals from
> the user's perspective.

## Problem

Druppie agents act exclusively through MCP tools, and those tools carry wildly
different risk profiles. A `read_file` or `list_dir` is safe to run on its own;
a `build`, `run`, `merge_pull_request`, or `remove` is destructive and can alter
files, infrastructure, or source control in ways that are hard to undo. Today
the pain points for users are:

- **No predictable control point.** Without a defined approval layer, users
  cannot tell which agent actions will execute autonomously and which will wait
  for them. Destructive operations can fire without a human ever seeing them,
  eroding trust in letting agents run unattended.
- **No way to map authority to the team.** "Someone needs to approve this" is
  not enough — different actions legitimately belong to different roles. An
  architect should sign off on design-affecting changes; a developer should
  gate PR merges. Today there is no product concept of "needs approval by a
  specific role."
- **No single queue.** When an agent needs authorization, the user has to be
  watching the right session at the right moment. There is no consolidated view
  of "everything waiting on me," so approvals are missed or acted on late.
- **No flexibility per agent.** The same tool can need different scrutiny
  depending on which agent calls it — a trusted agent may write files freely
  while a sensitive one must get sign-off first. A single rigid rule per tool
  cannot express that, so teams either over-approve (everything blocks, killing
  autonomy) or under-approve (nothing blocks, killing safety).

What breaks without this feature: users cannot safely let agents run
autonomously, the approval burden falls unevenly on whoever happens to be
watching, and there is no auditable, role-aligned gate between an agent and a
destructive action.

## Goal

A risk-tiered, role-based approval system that lets agents run autonomously on
safe actions while guaranteeing a human authorizes destructive ones. Concretely,
done means:

1. **Tiered by risk.** Tools are split into "runs autonomously" vs "needs
   approval." Low-risk tools (reads, listing) never block; high-risk tools
   (build, run, merge, remove) always pause until authorized.
2. **Role-based authorization.** Every approval-requiring tool names a
   `required_role`. Only users holding that role (or an admin) can approve or
   reject it — approval authority maps to real team roles (admin, architect,
   developer, business analyst, user).
3. **Predictable per-agent behavior.** The platform ships sensible global
   defaults, and each agent can tighten or loosen the rule for a given tool
   without code changes — so a sensitive agent can demand sign-off where a
   trusted one does not.
4. **One queue, two views.** A dedicated **Tasks page** (`/tasks`) acts as the
   centralized, role-filtered approval queue across all sessions, and approval
   cards also appear inline in the chat timeline of the session that triggered
   them — so users can act from either context.
5. **Visible pending state.** While an approval is outstanding the session
   shows a clear "waiting for approval" status and the requesting agent run is
   visibly paused; resuming is automatic once the user acts.
6. **Actionable rejections.** A rejection carries a reason that flows back to
   the agent, so the agent can adapt rather than silently stall.

**Definition of done:** an authorized user can see every approval they are
allowed to act on (and no others) on the Tasks page, approve or reject each one
(with a reason on reject) inline or from the queue, and the session correctly
resumes execution after the decision — while a user lacking the required role
cannot act at all. The queue updates within ~1 second of a new approval being
created.

## User Journey

1. An agent in a session calls a high-risk tool (e.g. `merge_pull_request`).
2. The system recognizes the tool requires approval by a specific role, creates
   an approval request, and **pauses** the requesting agent run. The session
   moves to a "waiting for approval" status.
3. The approval appears in **two places at once**: as a card inline in the
   session's chat timeline (with full context of what triggered it), and in the
   **Tasks page** queue.
4. On the Tasks page, the user sees only approvals their roles authorize them
   to act on. Each card shows the tool name, MCP server, the requesting agent,
   the full arguments (with expandable file-content previews for write
   operations), and a link to the parent session.
5. The user reviews the request and either:
   - **Approves** — the paused tool executes, the agent run resumes, and the
     session continues automatically; or
   - **Rejects** (with a required reason) — the rejection reason is passed back
     to the agent, which adapts and continues.
6. The approval card is removed from the queue and the timeline updates to show
   the decision. The Tasks page polls every ~1 second, so new approvals surface
   promptly.
7. A user whose role does not match the tool's `required_role` (and who is not
   an admin) never sees the card and cannot act on it.

## Constraints

- **Role-bound.** Approval authority is tied to Keycloak roles. Only the
  `required_role` holder (or an admin, who can act on any approval) may approve
  or reject. This is a hard security constraint, not a preference.
- **Config in YAML, not the database.** Global approval defaults live in
  `mcp_config.yaml` and per-agent overrides live in agent YAML files. Rules are
  version-controlled and reviewable; they are not runtime-mutable from the UI.
- **Always resumable.** Pausing for approval never discards work. The agent
  run suspends cleanly and resumes from exactly where it stopped once decided
  (the durability model is owned by the Session Lifecycle PRD / ADR 013).
- **Two surfaces must stay consistent.** The Tasks page and the inline chat
  card reflect the same approval; acting on either resolves it in both.
- **Rejections must carry a reason.** The agent depends on the reason to adapt,
  so a reject without a reason is not a valid action.
- **Admin overrides role.** An admin can approve or reject any item regardless
  of `required_role`.

## Out of Scope

- **Delegation / reassignment** of an approval to another user or role.
- **Bulk approval** of multiple items at once.
- **Notification preferences** (email, Slack, push) for approval events.
- **Time-out / auto-reject** of stale approvals after a deadline.
- **A UI to edit approval rules.** Rules live in YAML and are changed by
  editing config, not from the product UI.
- **The mechanics of how a pause resumes** — that is the Session Lifecycle
  subsystem (PRD 011 / ADR 013). This PRD covers the approval *experience*; it
  depends on that subsystem to actually resume execution.

## Open Questions

- **Q1: Should approvals support delegation when the required role is absent?**
  - Option A: No delegation — if no one with the role is online, the approval
    waits. Simpler and ships now.
  - Option B: Delegate to another role (e.g. admin-only fallback) so work is
    never blocked. More flexible, adds UI and policy complexity.
  - Owner: architect, deadline: 2026-08-15
- **Q2: How do users discover *why* a tool did (or did not) require approval?**
  - Option A: Show the effective rule (global default vs. agent override) on the
    approval card for transparency.
  - Option B: Keep the card minimal and expose rule provenance only in an
    admin/debug view.
  - Owner: architect, deadline: 2026-08-15

## Linked Documents

- **ADRs:** `docs/adrs/010-layered-approval-model.md` (the two-layer approval
  model: global defaults + per-agent overrides, resolved by the ToolExecutor,
  role-based authorization).
- **Research:** _(none)_
- **Specs / Feature files:** _(none yet)_
- **Related PRDs:** PRD 004 (Native Agent Runtime) — the agent runtime is what
  pauses and resumes around an approval; this PRD defines the approval
  experience layered on top of it.
- **Source references:** `docs/TECHNICAL.md` §6.11 (Layered Approval System);
  `docs/FEATURES.md` "Approval Workflow" section.
