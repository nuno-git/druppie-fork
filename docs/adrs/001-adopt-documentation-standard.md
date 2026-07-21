---
id: "001"
title: Adopt a spec-driven documentation standard
status: proposed
date: 2026-07-14
deciders:
  - team
supersedes: null
superseded_by: null
linked_prd: null
linked_research: null
---

> **Where this fits:** This ADR is the first application of the standard it defines
> (dogfooding). It records *that* we adopt a documentation standard and *what* that standard is.
> The empirical rationale lives in the linked research (PR #283).

## Context

Architectural decisions and their rationale get lost over time — humans forget, and LLM agents
lose context on compaction. Two parallel efforts tried to fix this: PR #277 (a spec-driven
framework with templates) and the spike in PR #283 (an empirical evaluation of documentation
formats). We need one agreed standard so the team and Claude Code produce documentation with a
consistent structure, and so it is always clear which decisions apply.

## Decision

We adopt a spec-driven documentation standard:

- **Format:** Markdown with YAML frontmatter. Frontmatter carries the machine-readable fields
  (id, status, links); the body is free-form Markdown for human reasoning.
- **Document types (4):** PRD (feature), ADR (decision), Research (investigation),
  and Spec (executable `.feature` acceptance criteria).
- **Flow:** `PRD → Research? → ADR? → Spec → build` (Research and ADR are conditional).
- **Status per type** (not one shared enum): ADR `proposed | accepted | deprecated | superseded`;
  PRD `draft | review | approved | implemented | deprecated | superseded`; Research `draft | complete`.
- **Deprecation:** outdated documents are marked, never deleted — set `status: deprecated` or `superseded` (with `superseded_by`) so the rationale stays discoverable. Research docs remain a historical record.
- **Identifiers:** 3-digit zero-padded **string** ids (`"001"`); filenames `NNN-kebab-title.md`.
- **Traceability:** documents link via `linked_prd`, `linked_adrs`, `linked_research`,
  `linked_specs`, and `supersedes`/`superseded_by`; specs link back via `@prd`/`@adr` tags.
- **Validation contract:** one JSON Schema per frontmatter type
  (`docs/{adrs,prds,research}/*.schema.json`) defines the required fields.
- **Language:** English is the source of truth; frontmatter, ids and status are never translated.
- **Templates** live at fixed locations: `docs/adrs/TEMPLATE.md`, `docs/prds/TEMPLATE.md`,
  `docs/research/TEMPLATE.md`, `docs/specs/TEMPLATE.feature`.

## Consequences

- (+) One consistent structure; decisions and their rationale are captured and discoverable.
- (+) Explicit named frontmatter fields extract deterministically (empirically verified in the
  linked research — the classic id-in-heading style did not).
- (+) The standard is dogfooded: this ADR, the templates, and the guide all use it.
- (-) Authors must follow the templates; there is a small learning curve.
- (-) Until enforcement exists, compliance is manual and can drift.

Enforcement of this standard (pre-commit + CI validation using the schemas) is deliberately
**out of scope here** and handled in a later story (PBI 9744), so the team can first agree the best
enforcement mechanism. Migrating existing docs to the standard is likewise a separate story (PBI 9743).
This ADR stays `proposed` until the team signs off, then flips to `accepted`.
