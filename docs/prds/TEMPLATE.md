---
id: 000                              # Sequential PRD number (e.g. 001, 002)
title: Feature name                   # Short, descriptive name
status: proposed                      # proposed | accepted | deprecated | superseded
author: role name                     # Who authored this PRD (e.g. "architect", "developer")
date: 2026-06-09                      # Date of initial draft (YYYY-MM-DD)

# Supersession tracking — only relevant when status is "superseded"
superseded_by: null                   # PRD id (e.g. 003) — only when status is "superseded"

linked_adrs: []                       # List of ADR file paths, e.g. ["docs/adrs/001-choice-of-state-management.md"]
linked_research: []                   # List of research doc paths, e.g. ["docs/research/001-auth-providers.md"]
linked_specs: []                      # List of .feature file paths, e.g. ["tests/features/approval-workflow.feature"]
---

# PRD: {title}

> **Where this fits:** The PRD is the START of the spec-driven pipeline. Everything flows
> from here: PRD → Research (optional, only when unclear) → ADR (decision) → Acceptance Specs (verification)
> → Implementation. The PRD describes the PROBLEM and the GOAL from the user's perspective.
> It does NOT contain technical decisions (that's ADRs) or executable tests (that's Acceptance Specs).

## Problem

<!-- What problem does this solve? Why now?
     - Describe the user pain point or business need.
     - Explain what breaks or degrades without this feature.
     - Reference specific user feedback, metrics, or incidents if available.
     Example: "Users cannot approve agent actions from mobile devices, forcing them to switch to desktop for every approval." -->

_Graph of the current state and why it is insufficient._

## Goal

<!-- What does success look like? Measurable outcomes.
     - Define clear, testable acceptance criteria.
     - Include quantitative targets where possible (latency, throughput, error rate).
     - State what "done" means unambiguously.
     Example: "Users can approve or reject any pending task within 3 seconds on mobile, reducing desktop-only approval rate to <5%." -->

_Definition of done with measurable criteria._

## User Journey

<!-- Step-by-step interaction flow.
     - Number each step.
     - Write from the user's perspective ("User clicks...", "System responds...").
     - Cover the happy path. Edge cases go in Constraints or Open Questions.
     Example:
     1. User opens the Approvals page on mobile.
     2. System displays pending approval cards with file preview.
     3. User taps "Approve" on a task.
     4. System confirms approval and removes the card.
-->

1. _Step one: user does X._
2. _Step two: system responds with Y._
3. ...

## Constraints

<!-- Technical, regulatory, or design constraints.
     - List hard limits that cannot be negotiated (API contracts, security requirements, browser support).
     - Include performance budgets (e.g. "Page load <2s on 3G").
     - Reference regulatory requirements if applicable (GDPR, SOC2).
     Example: "Must work without JavaScript (SSR fallback). Approval actions require role-based access control." -->

- _Constraint 1._
- _Constraint 2._

## Out of Scope

<!-- Explicitly what this feature does NOT cover.
     - Prevent scope creep by listing related but excluded work.
     - Items here may become separate PRDs.
     Example: "Bulk approval of multiple tasks at once. Notification preferences for approval events." -->

- _Excluded item 1._
- _Excluded item 2._

## Open Questions

<!-- Unresolved decisions with options.
     - Each question should have at least two options with trade-offs.
     - Assign an owner and deadline for each question.
     Example:
     - **Q1: Should approvals support delegation?**
       - Option A: No delegation — simpler, ships faster.
       - Option B: Delegate to another role — more flexible, adds UI complexity.
       - Owner: architect, deadline: 2026-06-15_
-->

- **Q1: _Question text?_**
  - Option A: _Description._
  - Option B: _Description._
  - Owner: _role_, deadline: _date_

## Linked Documents

<!-- Auto-populated from YAML frontmatter. Do not edit this section manually.
     The links below are rendered from the frontmatter fields above. -->

### ADRs
<!-- Rendered from `linked_adrs` frontmatter -->
<!-- {% for adr in linked_adrs %}- [{{ adr }}](/{{ adr }}){% endfor %} -->

### Research
<!-- Rendered from `linked_research` frontmatter -->
<!-- {% for doc in linked_research %}- [{{ doc }}](/{{ doc }}){% endfor %} -->

### Acceptance Specs / Feature Files
<!-- Rendered from `linked_specs` frontmatter -->
<!-- {% for spec in linked_specs %}- [{{ spec }}](/{{ spec }}){% endfor %} -->
