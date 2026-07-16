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
| **Research** | *All* options considered + their trade-offs / weighing | Only when the choice isn't obvious | `docs/research/TEMPLATE.md` |
| **ADR** | *Only* the decision that was made + its consequences, kept concise (Context / Decision / Consequences) — **no** weighing of alternatives | When you make a decision worth remembering | `docs/adrs/TEMPLATE.md` |
| **Spec** | Executable acceptance criteria (Gherkin) | Before implementing, to pin behaviour | `testing/specs/features/TEMPLATE.feature` |

> **ADR vs Research.** Keep them apart: the **comparison of alternatives and their trade-offs lives in the Research doc**, not in the ADR. The **ADR states only the decision that was taken and what follows from it** (Context / Decision / Consequences), briefly. If you catch yourself weighing options inside an ADR, that weighing belongs in a Research doc — link the ADR to it via `linked_research`.

## Orientation artefacts (no template, optional)

Next to the four *templated* types above (PRD / Research / ADR / Spec) there are two lightweight, **optional** "orientation" categories. They have **no template and no schema**, and they are **not checked by the validator (Check B)**:

| Type | What it captures | Location |
|------|------------------|----------|
| **Guide** | How-to / explanation / conventions / runbooks — *"how do I do X"* | `docs/guides/` |
| **Reference** | Naslag / subsystem- & architecture docs — *"what exists / how does it hang together"* | `docs/reference/` |

- They carry **no mandatory frontmatter/template** and are **not schema-validated**, but they **do count as valid documentation for the mandatory-docs gate (Check A)**.
- **Back-links:** a guide/reference **SHOULD** link back to the ADR/PRD/Spec that owns the underlying decision/requirement/behaviour. This is a recommendation, not a hard-enforced rule.

### Decompose first: pick As-1 or As-2

Before writing, decide which axis a doc sits on:

- **As-1 — templated (ADR / PRD / Spec):** if the doc records a **decision, a requirement, or testable behaviour**, use a templated type. This holds **even when you are describing how something already works today** — current behaviour does **not** disqualify an ADR or Spec. Lens ≠ time: an **ADR** is about an *already-taken decision*, and a **Spec** describes exactly *current/required behaviour*.
- **As-2 — orientation (guide / reference):** if the doc is **pure orientation or naslag**, use a guide or reference, **with a back-link** to the owning ADR/PRD/Spec.

Reference is **not an escape hatch** to avoid writing ADRs or Specs: a decision or a testable behaviour still needs its templated home.

## The flow

```
PRD  →  Research?  →  ADR?  →  Spec  →  build
```

- **PRD first** — know what you're building and why.
- **Research is optional** — skip it if the choice is obvious or an ADR already covers it.
- **ADR is conditional** — only for a *new* decision; skip if an existing ADR applies.
- **Specs** pin the acceptance criteria and link back to their PRD/ADR via `@prd` / `@adr` tags.

Not every change needs docs: a bugfix or chore usually needs none.

## Conventions

- **Format:** Markdown + YAML frontmatter.
- **Ids:** 3-digit zero-padded **string** (`"001"`); filenames `NNN-kebab-title.md`.
- **Status** differs per type (see each template).
- **Links:** use the `linked_*` frontmatter fields to connect documents.
- **DevOps link (PRD):** a PRD's frontmatter carries a `linked_workitem` field — a URL to the Azure DevOps user story / work item that motivates the PRD. It may be `null` when there is no work item.
- **Language:** English is the source of truth; ids, status and frontmatter are never translated.
- **Schemas:** `docs/{adrs,prds,research}/*.schema.json` define the required frontmatter fields.
- **Outdated docs:** mark them `deprecated` / `superseded` — don't delete (the *why* must survive).

## Not done yet (later stories)

- **Enforcement** — pre-commit + CI that validate docs against the schemas → **PBI 9744**.
- **Migrating existing docs** to this standard → **PBI 9743**.
- **In-core documentation portal**, **decision-aware agents**, and **agent writer-skills** →
  later epics (relevant once we build Druppie via Druppie itself).

> This guide is written in the standard it describes, so it can later be converted into a
> writer-skill with minimal effort.

## Enforcement (checks)

Docs in `docs/{adrs,prds,research}` and `testing/specs/features` are checked automatically (PBI 9744):

- **Locally (optional):** `docker compose --profile docs-validator run --rm docs-validator` — or install [lefthook](https://github.com/evilmartians/lefthook) (`lefthook install`) to run it before each commit.
- **CI (binding):** `.github/workflows/docs.yml` runs on every PR, with two checks:
  - **Validity** — docs that exist must have the required frontmatter/fields, a matching `id`, resolvable `linked_*` / `@prd` / `@adr`, and a fresh `CAS.md`.
  - **Mandatory-docs** — a PR that changes feature code must include documentation, unless it is marked `docs-exempt`.
- **Exempt** a change that genuinely needs no docs via the **`docs-exempt` label** or a **checked `docs-exempt` box** / a **`docs-exempt: <reason>` line** in the PR description.

> These checks currently run in **warn-mode** (they report but do not block) while existing docs are migrated. They become blocking once the baseline is clean and the team agrees.
