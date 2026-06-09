---
name: prd-writer
description: >
  Guides creation of Product Requirements Documents before any feature
  work begins. Covers the lightweight template, problem-goal-journey flow,
  and linking to ADRs and BDD scenarios.
allowed-tools:
  coding:
    - read_file
    - write_file
    - list_dir
---

# PRD Writer

Product Requirements Documents define *what* needs to be built and *why*,
before any architectural decisions or implementation. They are the starting
point of the spec-driven pipeline: PRD → Research → ADR → BDD → Code.

## When to Write a PRD

Write a PRD **before any feature work begins**. This includes:

- New user-facing features.
- Significant changes to existing features.
- Infrastructure or platform changes that affect multiple components.
- Integrations with external systems.

Do **not** write a PRD for:

- Bug fixes (use the `bug-fix` skill).
- Pure refactoring (use the `refactor` skill).
- Minor config changes or typo fixes.

## PRD Template

Create the file as `docs/prds/PRD-NNNN-short-kebab-title.md`:

```markdown
# PRD-NNNN: Short Kebab Title

**Author**: Agent / role
**Date**: YYYY-MM-DD
**Status**: draft | approved

## Problem

What is the problem we're solving? Describe the current pain point or
opportunity in 2-3 sentences. Focus on the user or system impact, not
the solution.

## Goal

What does success look like? One or two measurable outcomes.

- Goal 1: [measurable outcome]
- Goal 2: [measurable outcome]

## User Journey

Describe the primary user journey as a sequence of steps:

1. User does X
2. System responds with Y
3. User does Z
4. ...

Keep it to the happy path. Edge cases go in BDD scenarios.

## Requirements

### Must have
- Requirement 1
- Requirement 2

### Should have
- Requirement 3

### Nice to have
- Requirement 4

## Constraints

What are the hard boundaries for this feature?

- **Technical**: e.g., "Must work with Postgres 15", "No new dependencies"
- **Performance**: e.g., "p95 latency < 200ms", "Handle 100 concurrent users"
- **Security**: e.g., "Role-based access control", "Audit logging required"
- **Compatibility**: e.g., "Backward-compatible with v1 API"
- **Regulatory**: e.g., "Data retention per policy X"

## Out of Scope

Explicitly list what this PRD does NOT cover:

- Thing A (may be covered in a future PRD)
- Thing B (outside current sprint)

## Open Questions

- Question 1
- Question 2

## Related

- ADRs: `docs/adrs/ADR-XXX.md` (if any exist or are planned)
- Research: `docs/research/YYYY-MM-DD-topic.md` (if any)
- BDD: `tests/features/XXX.feature` (created during implementation)
```

## Problem → Goal → User Journey Flow

This is the core narrative of the PRD. It must flow logically:

1. **Problem** — The world as it is today. What's broken, missing, or
   suboptimal? Who is affected?
2. **Goal** — The world as it should be after this feature. What measurable
   change do we expect?
3. **User Journey** — How a user moves through the feature from start to
   finish. Concrete steps, not abstract descriptions.

If any of these three are unclear, the PRD is not ready for approval.

## Keep It Lightweight

A PRD is a direction-setting document, not a detailed spec:

- **2-3 pages max.** If it's longer, the scope is too broad — split into
  multiple PRDs.
- **No implementation details.** The "how" belongs in ADRs and code.
- **No technical jargon** in Problem and Goal. Those sections must be
  understandable by non-technical stakeholders.
- **Requirements are testable.** Each "must have" should map to at least
  one BDD scenario.

## Constraints Section Is Critical

The constraints section is often the most important part of the PRD because
it defines the boundaries within which architects and developers must work.
A PRD without constraints will lead to over-engineering or under-engineering.

For each constraint:
- State it precisely (with numbers where possible).
- Explain *why* it exists (business reason, not technical preference).
- Note if it's a hard constraint (cannot be changed) or a soft constraint
  (negotiable with justification).

## Linking to ADRs and BDD Scenarios

The PRD is the root of the documentation tree. From it, branches grow:

- **PRD → Research** — If the PRD raises questions that need investigation,
  create a research doc and link it.
- **PRD → ADR** — If the PRD requires architectural decisions, create ADRs
  and link them back to the PRD.
- **PRD → BDD** — During implementation, BDD scenarios are tagged with
  `@prd:PRD-NNNN` to trace back to the PRD.

Keep the Related section updated as these documents are created.
