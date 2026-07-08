---
name: prd-writer
description: >
  Guides creation of Product Requirements Documents before any feature
  work begins. Covers the lightweight template, problem-goal-journey flow,
  and linking to ADRs and acceptance specs.
allowed-tools:
  coding:
    - read_file
    - write_file
    - list_dir
---

# PRD Writer

Product Requirements Documents define *what* needs to be built and *why*,
before any architectural decisions or implementation. They are the starting
point of the spec-driven pipeline: PRD → Research → ADR → Acceptance Specs → Code.

## Where the PRD Fits in the Flow

The PRD is the START of the spec-driven pipeline. Everything flows from here:

1. **PRD** — We want something. Why? What's the user journey?
2. **Research** (optional) — How should we build it? What are the options?
3. **ADR** — We decided X. Here's why. Here's how it's enforced.
4. **Acceptance Specs** — The system must do Y. Here's the executable proof.
5. **Implementation** — Build it following the ADRs.

The PRD is the user-facing story. It does NOT contain technical decisions (that's ADRs)
or executable tests (that's Acceptance Specs). It describes the PROBLEM and the GOAL.

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

## PRD Template — YAML Frontmatter Format (MANDATORY)

The canonical format is defined by `docs/prds/TEMPLATE.md`. Every PRD is a
Markdown file with **YAML frontmatter between `---` delimiters**, followed by a
fixed set of body sections.

Create the file as `docs/prds/NNN-short-kebab-title.md` (3-digit id matching the
frontmatter `id`):

```markdown
---
id: 000                              # Sequential PRD number (e.g. 001, 002)
title: Feature name                  # Short, descriptive name
status: proposed                     # proposed | accepted | deprecated | superseded
superseded_by: null                  # ID of replacement PRD when status is superseded
author: role name                    # Who authored this PRD (e.g. "architect")
date: 2026-06-09                     # Date of initial draft (YYYY-MM-DD)
linked_adrs: []                      # ADR file paths, e.g. ["docs/adrs/001-layered-architecture.md"]
linked_research: []                  # Research doc paths, e.g. ["docs/research/001-state-mgmt.md"]
linked_specs: []                     # .feature file paths, e.g. ["tests/features/approval-workflow.feature"]
---

# PRD: {title}

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

Keep it to the happy path. Edge cases go in acceptance specs.

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

## Linked Documents

<!-- Auto-populated from YAML frontmatter. Do not edit manually. -->

### ADRs
### Research
### Acceptance Specs / Feature Files
```

### Required frontmatter fields

| Field | Type | Notes |
|-------|------|-------|
| `id` | integer | Sequential PRD number (e.g. `001`). |
| `title` | string | Short, descriptive name. |
| `status` | string | One of `proposed`, `accepted`, `deprecated`, `superseded`. |
| `superseded_by` | integer \| null | ID of the PRD that replaces this one. Set only when `status` is `superseded`; `null` otherwise. |
| `author` | string | Role or name of the author. |
| `date` | string | `YYYY-MM-DD`. |
| `linked_adrs` | list | ADR file paths, e.g. `["docs/adrs/001-layered-architecture.md"]`. |
| `linked_research` | list | Research doc paths. |
| `linked_specs` | list | `.feature` file paths. |

### Body sections (fixed order)

**Problem**, **Goal**, **User Journey**, **Constraints**, **Out of Scope**,
**Open Questions**, **Linked Documents** — matching `docs/prds/TEMPLATE.md`.
There is no separate "Requirements" section; testable requirements belong in the
**Goal** (as measurable outcomes) and in linked acceptance specs. There is no prose
"Related" header — all cross-links live in the frontmatter and are rendered into
the **Linked Documents** section.

### PRD Governance Status Model

PRD status tracks **governance truth**, not build progress. It mirrors the ADR
status model exactly. The lifecycle is:

```
proposed → accepted → (deprecated | superseded)
```

- **`proposed`** — A new PRD has been written and is seeking acceptance. This is
  the initial status of every PRD you create.
- **`accepted`** — The PRD is agreed as the current truth. The team has committed
  to the problem, goal, and journey. This is the steady state of an active PRD.
- **`deprecated`** — The PRD is no longer relevant and has not been replaced by a
  specific successor. Set `superseded_by: null`.
- **`superseded`** — The PRD has been replaced by a newer one. The `superseded_by`
  field MUST point to the replacing PRD's `id`.

There is no `review` status (acceptance is the gate, not a separate review phase)
and no `implemented` status (PRD governance does not track implementation — that
is the job of the acceptance specs and code).

#### How to supersede a PRD

To replace an existing accepted PRD with a new one:

1. Create the new PRD with `status: proposed` (then move to `accepted` once agreed).
2. Update the old PRD: set `status: superseded` and `superseded_by: <new PRD id>`.
3. Do not delete the old PRD — its history and links must remain intact.

## Problem → Goal → User Journey Flow

This is the core narrative of the PRD. It must flow logically:

1. **Problem** — The world as it is today. What's broken, missing, or
   suboptimal? Who is affected?
2. **Goal** — The world as it should be after this feature. What measurable
   change do we expect?
3. **User Journey** — How a user moves through the feature from start to
   finish. Concrete steps, not abstract descriptions.

If any of these three are unclear, the PRD is not ready to be accepted.

## Keep It Lightweight

A PRD is a direction-setting document, not a detailed spec:

- **2-3 pages max.** If it's longer, the scope is too broad — split into
  multiple PRDs.
- **No implementation details.** The "how" belongs in ADRs and code.
- **No technical jargon** in Problem and Goal. Those sections must be
  understandable by non-technical stakeholders.
- **Requirements are testable.** Each "must have" should map to at least
  one acceptance spec.

## Constraints Section Is Critical

The constraints section is often the most important part of the PRD because
it defines the boundaries within which architects and developers must work.
A PRD without constraints will lead to over-engineering or under-engineering.

For each constraint:
- State it precisely (with numbers where possible).
- Explain *why* it exists (business reason, not technical preference).
- Note if it's a hard constraint (cannot be changed) or a soft constraint
  (negotiable with justification).

## Linking to ADRs and Acceptance Specs

The PRD is the root of the documentation tree. From it, branches grow. All
cross-links live in the **frontmatter** (not in a prose "Related" section) so
they stay machine-readable:

- **PRD → Research** — If the PRD raises questions that need investigation,
  create a research doc and add its path to `linked_research`.
- **PRD → ADR** — If the PRD requires architectural decisions, create ADRs and
  add their paths to `linked_adrs` (e.g. `"docs/adrs/001-layered-architecture.md"`).
- **PRD → Acceptance Specs** — During implementation, acceptance specs are tagged with
  `@prd:NNN` to trace back to the PRD, and the `.feature` paths are added to
  `linked_specs`.

Keep the frontmatter link fields updated as these documents are created. The
**Linked Documents** body section renders from these fields — never edit it by
hand.
