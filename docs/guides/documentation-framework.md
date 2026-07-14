---
title: Documentation framework — how it works
status: draft
---

# Documentation framework — how it works

This is the practical guide to how we document decisions and specs in this repo. For the decision and rationale see [ADR 001](../adrs/001-adopt-documentation-standard.md).

## The four document types

| Type | What it captures | When you write it | Template |
|------|------------------|-------------------|----------|
| **PRD** | The feature: the problem and goal from the user's side | Start of a non-trivial feature | `docs/prds/TEMPLATE.md` |
| **Research** | An options / trade-off investigation | Only when the choice isn't obvious | `docs/research/TEMPLATE.md` |
| **ADR** | A committed technical/architecture decision + why | When you make a decision worth remembering | `docs/adrs/TEMPLATE.md` |
| **BDD** | Executable acceptance criteria (Gherkin) | Before implementing, to pin behaviour | `testing/bdd/features/TEMPLATE.feature` |

## The flow

```
PRD  →  Research?  →  ADR?  →  BDD  →  build
```

- **PRD first** — know what you're building and why.
- **Research is optional** — skip it if the choice is obvious or an ADR already covers it.
- **ADR is conditional** — only for a *new* decision; skip if an existing ADR applies.
- **BDD** pins the acceptance criteria and links back to its PRD/ADR via `@prd` / `@adr` tags.

Not every change needs docs: a bugfix or chore usually needs none.

## Conventions

- **Format:** Markdown + YAML frontmatter.
- **Ids:** 3-digit zero-padded **string** (`"001"`); filenames `NNN-kebab-title.md`.
- **Status** differs per type (see each template).
- **Links:** use the `linked_*` frontmatter fields to connect documents.
- **Language:** English is the source of truth; ids, status and frontmatter are never translated.
- **Schemas:** `docs/{adrs,prds,research}/*.schema.json` define the required frontmatter fields.

## Not done yet (later stories)

- **Enforcement** — pre-commit + CI that validate docs against the schemas → **PBI 9744**.
- **Migrating existing docs** to this standard → **PBI 9743**.
- **In-core documentation portal**, **decision-aware agents**, and **agent writer-skills** →
  later epics (relevant once we build Druppie via Druppie itself).

> This guide is written in the standard it describes, so it can later be converted into a
> writer-skill with minimal effort.
