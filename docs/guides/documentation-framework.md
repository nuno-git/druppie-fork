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
| **Spec** | Executable acceptance criteria (Gherkin) | Before implementing, to pin behaviour | `testing/specs/features/TEMPLATE.feature` |

## The flow

```
PRD  →  Research?  →  ADR?  →  Spec  →  build
```

- **PRD first** — know what you're building and why.
- **Research is optional** — skip it if the choice is obvious or an ADR already covers it.
- **ADR is conditional** — only for a *new* decision; skip if an existing ADR applies.
- **Specs** pin the acceptance criteria, link back to their PRD/ADR via `@prd` / `@adr` Gherkin tags, and carry lifecycle tags (`# @status`, `# @superseded_by`) just like the other doc types.

Not every change needs docs: a bugfix or chore usually needs none.

## Conventions

- **Format:** Markdown + YAML frontmatter.
- **Ids:** 3-digit zero-padded **string** (`"001"`); filenames `NNN-kebab-title.md`.
- **Status & lifecycle:** every doc carries a `status`, and a `superseded_by` once replaced. For ADR/PRD/Research these live in YAML frontmatter; for Specs they are `# @status` / `# @superseded_by` comment tags at the top of the file. Exact values differ per type — see each template.
- **Links:** use the `linked_*` frontmatter fields (ADR/PRD/Research) or the `@prd` / `@adr` Gherkin tags (Specs) to connect documents.
- **Language:** English is the source of truth; ids, status and frontmatter are never translated.
- **Schemas:** `docs/{adrs,prds,research}/*.schema.json` define the required frontmatter fields; Spec `@prd` / `@adr` / `@status` / `@superseded_by` tags are checked by `scripts/validate_docs.py`.
- **Outdated docs:** never delete — always supersede (see [Migration Workflow](#migration-workflow)). Mark the old doc `superseded` and point `superseded_by` at the replacement so the *why* stays traceable.

## Migration Workflow

Living docs (`docs/TECHNICAL.md`, `docs/FEATURES.md`, ad-hoc behavioural notes) capture
decisions and features informally. As the content stabilises, migrate it into the typed
documents so it gets an id, a status, and cross-links. The golden rule: **never delete —
always supersede**, so the historical *why* stays traceable.

### Lifecycle tags

Every document records where it is in its lifecycle. The mechanism differs by type but the
shape is the same — a `status` plus a `superseded_by`:

| Type | Where the tags live | Example |
|------|---------------------|---------|
| ADR / PRD / Research | YAML frontmatter (`status`, `superseded_by`) | `status: accepted`, `superseded_by: "005-..."` |
| Spec (`.feature`) | comment tags at the top of the file | `# @status active`, `# @superseded_by <file>` |

- **ADR statuses:** `proposed | accepted | deprecated | superseded` (see `docs/adrs/TEMPLATE.md`).
- **Spec statuses:** `draft | active | superseded` (see `testing/specs/features/TEMPLATE.feature`).
- **PRD / Research** use the same frontmatter pattern — see their templates for the exact
  status values.
- `scripts/validate_docs.py` enforces this in CI: a `superseded` doc **must** name its
  replacement, and a `draft` / `active` doc must leave `superseded_by` empty.

### Migrating content

- **Decision buried in `TECHNICAL.md` → ADR.** Copy the decision, its context, and
  consequences into a new `docs/adrs/NNN-title.md`, filling in every required frontmatter
  field. Leave a one-line pointer to the new ADR at the old location, then supersede the
  old prose (below) rather than deleting it.
- **Feature description in a living doc → PRD.** Move the problem, goal, and user journey
  into `docs/prds/NNN-title.md`; connect it to its motivation via `linked_adrs` /
  `linked_research`.
- **Behavioural / acceptance notes → Spec.** Rewrite the behaviour as Gherkin scenarios in
  `testing/specs/features/NNN-name.feature`, starting from `TEMPLATE.feature`. Fill in the
  `# @status` / `# @superseded_by` block and the `@prd` / `@adr` tags so the spec links
  back to its PRD and ADR.

### Superseding a document

When a typed document replaces an older one (or a living-doc section), do **both** steps:

1. **Old doc — mark superseded.** Set `status: superseded` and `superseded_by: <new-doc>`
   (frontmatter), or `# @status superseded` + `# @superseded_by <new-file>` (Specs). For a
   Markdown doc, also add a banner at the very top of the body so a reader lands on it
   immediately:

   ```markdown
   > **Superseded** by [`005-new-title.md`](005-new-title.md).
   > Kept for history — follow the new doc.
   ```

2. **New doc — point back.** Link the replacement to the old one (ADR: `supersedes:
   "<old-id>"`) so the chain is navigable in both directions.

Never delete the old document. The validator guarantees a `superseded` doc always names its
replacement.

## Not done yet (later stories)

- **Enforcement** — pre-commit + CI that validate docs against the schemas → **PBI 9744**.
- **Migrating existing docs** to this standard → **PBI 9743**.
- **In-core documentation portal**, **decision-aware agents**, and **agent writer-skills** →
  later epics (relevant once we build Druppie via Druppie itself).

> This guide is written in the standard it describes, so it can later be converted into a
> writer-skill with minimal effort.
