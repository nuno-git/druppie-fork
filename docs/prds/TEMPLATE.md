---
id: "001"                            # Sequential PRD number as STRING (quote it!) — e.g. "001", "002"
title: Feature name                   # Short, descriptive name
status: draft                         # draft | review | approved | implemented | deprecated | superseded
author: role name                     # Who authored this PRD (e.g. "architect", "developer")
date: YYYY-MM-DD                      # Date of initial draft (YYYY-MM-DD)
# Supersession tracking — only relevant when a PRD is replaced
supersedes: null                      # PRD id string this replaces (e.g. "003") or null
superseded_by: null                   # PRD id string that replaces this (e.g. "005") or null
linked_adrs: []                       # List of ADR file paths, e.g. ["docs/adrs/001-choice-of-state-management.md"]
linked_research: []                   # List of research doc paths, e.g. ["docs/research/001-auth-providers.md"]
linked_specs: []                      # List of .feature file paths, e.g. ["docs/specs/010-approval-workflow.feature"]
linked_workitem: null                 # URL to the Azure DevOps user story / work item that motivates this PRD (or null)
---

# PRD: {title}

> **Where this fits:** The PRD is the START of the spec-driven pipeline. Everything flows
> from here: PRD → Research (optional, only when unclear) → ADR (decision) → Spec (verification)
> → Implementation. The PRD describes the PROBLEM and the GOAL from the user's perspective.
> It does NOT contain technical decisions (that's ADRs) or executable tests (that's Specs).

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

<!-- Keep this list in sync with the frontmatter above (manual for now). -->

- **ADRs:** _list the items from `linked_adrs`_
- **Research:** _list the items from `linked_research`_
- **Specs / Feature files:** _list the items from `linked_specs`_
