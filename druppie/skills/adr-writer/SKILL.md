---
name: adr-writer
description: >
  Guides creation and management of Architecture Decision Records.
  Covers when to write an ADR, the template format, status rules,
  supersession, and linking to enforcement mechanisms.
allowed-tools:
  coding:
    - read_file
    - write_file
    - list_dir
---

# ADR Writer

Architecture Decision Records (ADRs) document the "why" behind architectural
choices. They are the primary mechanism for architectural governance in this
project.

## Where ADR Fits in the Flow

ADRs come AFTER research (if needed) and AFTER the PRD. The flow is:

**PRD** (we want something) → **Research** (what are the options?) → **ADR** (we decided X)

An ADR is a COMMITTED decision — it records what was chosen and why. Research documents
are the investigation that happens BEFORE the ADR. Not every ADR needs a research document
(skip research when the choice is obvious).

## When to Write an ADR

Write an ADR for any **non-trivial architectural choice**, including but not
limited to:

- Choosing a technology, framework, or library for a key component.
- Defining module boundaries or import rules.
- Selecting a data storage strategy (SQL vs NoSQL, caching strategy).
- Deciding on an integration pattern (sync vs async, REST vs gRPC).
- Establishing a new convention that affects multiple developers or agents.
- Changing an existing architectural decision.

Do **not** write an ADR for:

- Trivial implementation details (variable names, code formatting).
- Decisions fully covered by an existing accepted ADR.
- Temporary workarounds with a clear expiration.

## ADR Template — YAML Frontmatter Format (MANDATORY)

The canonical format is defined by `docs/adrs/TEMPLATE.md`. Every ADR is a
Markdown file with **YAML frontmatter between `---` delimiters**, followed by a
fixed set of body sections. The frontmatter is what
`scripts/validate_adr_status.py` parses — a plain-Markdown ADR (no frontmatter)
will be rejected.

Create the file as `docs/adrs/NNN-short-kebab-title.md`:

```markdown
---
id: "NNN"                           # 3-digit zero-padded number, QUOTED to avoid YAML int coercion. Must match filename prefix.
title: Short imperative title       # Imperative mood, e.g. "Use layered architecture"
status: proposed                    # proposed | accepted | deprecated | superseded
date: YYYY-MM-DD                    # Date the decision was made
deciders:                           # Roles/people who made the decision
  - role_or_name

superseded_by: null                 # ADR id string (e.g. "005") or null

enforcement:
  lint_rules: []                    # Linter rule IDs guarding this decision (e.g. ["TYP001"])
  ci_checks: []                     # CI job names or script paths that verify compliance

linked_prd: null                    # Path to a PRD (e.g. "docs/prds/001-approvals.md") or null
linked_research: null               # Path to a research doc (e.g. "docs/research/001-state-mgmt.md") or null
---

## Context

What is the issue motivating this decision or change? Describe the forces at
play — technical, social, and project constraints. State assumptions about the
current system.

## Decision

What was decided? State it clearly and unambiguously, in imperative mood.
Explain *what* was decided, not *why* (the why lives in Context and Consequences).

## Consequences

What becomes easier or harder because of this change? Cover positive effects,
negative trade-offs, and risks with their mitigations.

## Compliance

How do we verify the system still adheres to this decision? Reference the
specific lint rules, CI jobs, or code-review criteria. If a decision cannot be
automatically enforced, say so and describe the manual review process.

## Enforcement

Concrete steps taken when a violation is detected. What happens in CI? At
runtime? What is the remediation path for a developer who accidentally violates
this rule?
```

### Required frontmatter fields

These fields are checked by `scripts/validate_adr_status.py` — omitting any of
them fails validation:

| Field | Type | Notes |
|-------|------|-------|
| `id` | quoted string | 3-digit zero-padded, e.g. `"001"`. **Quote it** so YAML keeps it a string. Must match the filename prefix. |
| `title` | string | Short, imperative mood. |
| `status` | string | One of `proposed`, `accepted`, `deprecated`, `superseded`. |
| `date` | string | `YYYY-MM-DD`. |
| `deciders` | list | Roles or names of the decision makers. |
| `superseded_by` | string or null | ADR id (e.g. `"005"`) or `null`. |
| `enforcement` | map | Contains `lint_rules: []` and `ci_checks: []`. |

`linked_prd` and `linked_research` are not enforced by the validator but are
required by the template for traceability — always include them (use `null` when
not applicable).

### Body sections (fixed order)

The body must contain, in this order: **Context**, **Decision**, **Consequences**,
**Compliance**, **Enforcement**. Do not add a `## Status` section — status lives
in the frontmatter. Do not add a `## Related` section — links live in the
`linked_prd`, `linked_research`, and `superseded_by` frontmatter fields.

## Naming

- **Sequential numbering**: Find the highest existing ADR number, add 1.
  Example: if `007-*.md` exists, the next is `008-...`.
- **Short kebab title**: 3-5 words describing the decision.
  Example: `008-module-boundary-enforcement.md`
- **The `id` field must match the filename prefix** — `id: "008"` for file
  `008-module-boundary-enforcement.md`. The validator enforces this.
- **No dates in the filename** — the sequential number is the identifier.

## Status Rules

Status is a single frontmatter value — one of exactly four allowed strings.
Do not write prose like `superseded by [ADR-XXX]` in a Status section; that
information goes in the `superseded_by` field.

| Transition | Who | When |
|-----------|-----|------|
| → `proposed` | Any agent | ADR is written, awaiting review |
| → `accepted` | Architect agent | ADR is reviewed and approved |
| → `deprecated` | Architect agent | Decision is no longer recommended |
| → `superseded` | Architect agent | A new ADR replaces this one |

- **Never delete an ADR.** Even deprecated ADRs remain for historical context.
- **Status changes require a commit** that updates only the `status` field and,
  if applicable, the `superseded_by` field. Do not rewrite the body on a status
  change.

## Superseding an Old ADR

Supersession is tracked entirely in frontmatter — there is no prose "Related"
section. When a new ADR replaces an old one:

1. Create the new ADR with `status: proposed`. Leave its `superseded_by: null`.
2. Once the new ADR is `accepted`, update the **old** ADR's frontmatter only:
   - Set `status: superseded`.
   - Set `superseded_by: "NNN"` to the new ADR's id.
3. Do NOT modify the old ADR's body content — only the two frontmatter fields.
4. Trigger CAS regeneration (see `generate-cas` skill).

The validator enforces consistency: a `superseded` ADR must have a non-null
`superseded_by` that references an existing ADR id; an `accepted` ADR must have
`superseded_by: null`.

## Linking to Enforcement

Enforcement is recorded in **two** places that must agree:

1. **Frontmatter `enforcement` block** — machine-readable, consumed by tooling:
   ```yaml
   enforcement:
     lint_rules:
       - import-linter
     ci_checks:
       - import-linter-contracts
   ```
2. **Body `## Compliance` and `## Enforcement` sections** — human-readable
   description of how the rule is verified and what happens on violation.

If the ADR defines import rules, name the lint rule under `lint_rules`. If it
mandates a CI check, name the job or script under `ci_checks`. If a decision
cannot be automatically enforced, leave both lists empty and describe the manual
review process in the `## Compliance` section.

## After Acceptance: Trigger CAS Regeneration

Once an ADR is accepted (or superseded), the Current Architecture Specification
must be updated to reflect the new state:

1. Run `python scripts/generate_cas.py` to regenerate `docs/adrs/CAS.md`.
2. Verify the CAS reflects the new or superseded ADR.
3. See the `generate-cas` skill for details.

Never edit `docs/adrs/CAS.md` by hand — it is auto-generated and manual edits
are silently overwritten.
