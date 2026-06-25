---
id: implementation-plan-documentation-standards
title: "Implementation Plan — Documentation Standards, Format & Flow"
type: plan
status: proposed
author: Druppie team
date: 2026-06-25
linked_research: documentation-standards.md
tags: [documentation, implementation, roadmap]
---

# Implementation Plan — Documentation Standards, Format & Flow

## 1. Purpose & how to read

This plan operationalises [`docs/research/documentation-standards.md`](./documentation-standards.md). It turns the research report into an actionable, phased roadmap.

- The work is sequenced into **phases 0–7**.
- Each phase is described with the same fields: **Goal / Steps / Proposals / Acceptance criteria / Effort (S/M/L) / Depends on**.
- "Proposals" are open choices the team still has to make — this document is a **proposal**, not a finished decision. The team reviews and adjusts before executing.
- No code is written here. References stay at the proposal level and are coupled back to the research report's parts (A format eval, B in-core portal, C workflow + scenarios, E PR #277, F enforcement).

> **Effort legend:** S = <1 day, M = 1–3 days, L = ~1 week.

## 2. Guiding principles (from the research)

- **Single source of truth = Markdown in the repo.** Decisions and product docs live next to the code, version-controlled, reviewable in PRs.
- **Explicit machine-keyed YAML frontmatter** is the metadata format — it proved the most reliably extractable option in **Part A**'s empirical format test.
- **The in-core Documentation Portal is the primary presentation layer** (**Part B**) — humans browse decisions inside Druppie itself, not on a separate site.
- **Enforce documentation proportional to change impact** (**Part F**) — big/architectural changes need an ADR; chores do not.
- **Converge with Nuno's PR #277 rather than restart** (**Part E**) — keep its working spine, fix its gaps, layer the portal and enforcement on top.

## 3. Open proposals to decide first (Phase 0 inputs)

| Decision | Options | Recommended |
|---|---|---|
| **ADR template** | One YAML-frontmatter MADR-style ADR template vs. multiple (resolves PR #277's template-vs-skill drift) | **Adopt ONE** YAML-frontmatter MADR-style ADR template |
| **File numbering** | `NNN-kebab-title.md` zero-padded vs. date-prefixed (log4brains style) | **`NNN-kebab-title.md`** |
| **Status workflow** | Free-form vs. fixed lifecycle | `proposed -> accepted` (**only an architect promotes**) `-> deprecated / superseded` |
| **Language** | EN everywhere vs. mixed | **English for decision docs** (consistent with code docs); NL allowed where the audience needs it |
| **When is an ADR required?** | Always vs. impact-based | **Significant / architectural / new-dependency / public-API** changes — NOT bugfix / refactor / chore |
| **Directory layout** | Flat vs. categorised | `/docs/decisions`, `/docs/process`, `/docs/guides` |
| **Docs ownership** | Ad hoc vs. owned | Define a **`docs-maintainers`** group for CODEOWNERS review |

## 4. The step-by-step plan

### Phase 0 — Align & decide (S)

- **Goal:** Team agreement on Section 3 and convergence with PR #277.
- **Steps:** Review the research report and this plan; pick the single ADR template; agree directory layout, numbering, status workflow, language, and the "ADR-required" policy; assign `docs-maintainers`. Record the outcome **as the first ADR** — "ADR-001: documentation standard".
- **Proposals:** Use the recommendations in Section 3 as the default ballot.
- **Acceptance:** Decisions captured in **ADR-001**.
- **Effort:** S.
- **Depends on:** none.

### Phase 1 — Adopt the format & structure (M)

- **Goal:** The standard physically exists in the repo.
- **Steps:**
  - Create `/docs/decisions`, `/docs/process`, `/docs/guides`.
  - Promote the ADR + PRD templates from `docs/research/templates/` into place.
  - Write **ADR-001** (the standard itself).
  - Migrate **2–3 existing decision docs** into frontmatter ADRs — e.g. `docs/ADR-KUBERNETES.md`, key decisions from `docs/modules-research-and-decisions.md` and `docs/research-agent-runtime.md`.
  - Add a `/docs/decisions/README` describing the flow.
- **Proposals:** Pick which legacy docs to migrate first (highest-traffic / most-referenced).
- **Acceptance:** **≥3 real ADRs** with valid frontmatter + templates in place.
- **Effort:** M.
- **Depends on:** Phase 0.

### Phase 2 — Validation (M)

- **Goal:** Malformed docs are caught automatically.
- **Steps:**
  - Define a **JSON Schema** for ADR/PRD frontmatter.
  - Adopt and **repair** PR #277's `validate_adr_status.py` + `validate_doc_links.py`:
    - **Fix:** consolidate to a single YAML parser.
    - **Fix:** replace filesystem-mtime "freshness" with a **git/content-hash** check.
  - Run them locally (**lefthook**) **and** in a **CI workflow** (fills #277's missing-CI gap).
- **Proposals:** Choose the canonical YAML parser and where the schema lives.
- **Acceptance:** A PR with a broken ADR **fails CI**.
- **Effort:** M.
- **Depends on:** Phase 1.

### Phase 3 — In-core Documentation Portal (primary) (L)

- **Goal:** Humans browse decisions inside Druppie; auto-updates on push.
- **Steps (proposal-level):**
  - Surface `docs/decisions/*` in the existing `/documentation` portal as a new section.
  - Render an **ADR overview with status badges**.
  - Add a **search / filter box**.
  - Add a **per-feature progress log** and links to user stories / PRs.
  - Note: the portal **live-fetches from the repo with a short cache**, so no build/deploy is needed — changes appear within **~a minute** of a push.
- **Proposals:** Decide placement within `/documentation` and the cache TTL.
- **Acceptance:** `/documentation` shows all ADRs with status, is searchable, and reflects a push within **~a minute**.
- **Effort:** L.
- **Depends on:** Phase 1.

### Phase 4 — Overview/index generation (S–M)

- **Goal:** A generated decisions index + feature progress log that stays current.
- **Steps:** A small script scans `docs/decisions` frontmatter and emits an **index** (status table + supersession chain); run it in CI and/or compute it in the portal.
- **Proposals:** Generate at CI time (committed artifact) vs. compute live in the portal.
- **Acceptance:** The index **always reflects current ADRs** and is **never hand-edited**.
- **Effort:** S–M.
- **Depends on:** Phase 1.

### Phase 5 — Make agents decision-aware (M–L)

- **Goal:** AI agents consult decisions before generating code (**Part C scenario 2**).
- **Steps:**
  - Expose a **"list/read decisions" capability as an MCP tool** (tool-only architecture).
  - Have relevant agent definitions / skills consult it first.
  - Longer term: feed the generated decisions index as **initial context**.
- **Proposals:** Which agents are decision-aware first (architect, developer).
- **Acceptance:** An agent run **references a relevant accepted ADR**.
- **Effort:** M–L.
- **Depends on:** Phase 1, Phase 4.

### Phase 6 — Enforcement: mandatory docs in PRs (M)

- **Goal:** Code cannot merge without documentation (**Part F**).
- **Steps:**
  - Add the **PR template**.
  - Add the **Danger warn**.
  - Add the **docs-required CI gate** (paths-filter + ADR/PRD reference + `docs-exempt` label; **always-run** so the required check can't hang).
  - Make it a **required status check** via branch protection.
  - Add **CODEOWNERS** on `/docs`.
  - Roll out as **warn first, then promote to required**.
- **Proposals:** Define the exact paths-filter and the exempt-label policy.
- **Acceptance:** A code-only PR with no docs/ADR reference is **blocked**, and the **escape hatch works**.
- **Effort:** M.
- **Depends on:** Phase 2.

### Phase 7 (optional) — External public site (M)

- **Goal:** A public, strongly-searchable site + `llms.txt` for external agents.
- **Steps:** **MkDocs + Material**; `deploy-docs.yml` to **GitHub Pages**; **mkdocs-llmstxt**. Same source markdown (**single source of truth**).
- **Proposals:** Decide whether this is in scope at all, and what is published vs. internal-only.
- **Acceptance:** The public site **builds and publishes on push**.
- **Effort:** M.
- **Depends on:** Phase 1.

## 5. Convergence with PR #277 (Nuno)

| Keep | Fix | Add |
|---|---|---|
| PRD ↔ ADR ↔ BDD ↔ CAS traceability | Template-vs-skill drift → **pick one template** | **CI workflow** for the validators |
| Lefthook enforcement | mtime-based CAS freshness → use **git/hash** | The **in-core portal** surface (Phase 3) |
| Import-linter contracts | Three divergent YAML parsers → **consolidate** | The **mandatory-docs PR gate** (Phase 6) |
| The frontmatter ADR template | Unimplemented Memory pillar → **mark aspirational / out of MVP** | Optional **public site** (Phase 7) |

**Sequencing:** Adopt #277's spine in **Phases 1–2**, fix its gaps, and layer **portal + enforcement** on top.

## 6. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Checkbox-docs gaming | Tiered enforcement + CODEOWNERS review |
| Recurring template drift | Single template + schema validation |
| Portal DB change needs a reset (no migrations) | Schedule a reset window |
| Over-scoping #277's Memory pillar | Keep aspirational, out of MVP |
| Adoption friction | Start enforcement as **warn**, ramp to **required** |

## 7. Suggested epics & tickets (proposal backlog)

- **Epic 0 — Align & decide**
  - Run the standards decision meeting; fill the Section 3 ballot.
  - Author ADR-001 capturing the chosen standard.
  - Assign and document the `docs-maintainers` group.

- **Epic 1 — Adopt format & structure**
  - Create `/docs/{decisions,process,guides}` and place templates.
  - Migrate `docs/ADR-KUBERNETES.md` to a frontmatter ADR.
  - Migrate 1–2 decisions from `modules-research-and-decisions.md` / `research-agent-runtime.md`.
  - Write `/docs/decisions/README`.

- **Epic 2 — Validation**
  - Define the ADR/PRD frontmatter JSON Schema.
  - Repair + adopt `validate_adr_status.py` and `validate_doc_links.py`.
  - Wire validators into lefthook and a CI workflow.

- **Epic 3 — In-core portal**
  - Add a decisions section to `/documentation` with status badges.
  - Add search/filter.
  - Add per-feature progress log + PR/user-story links.

- **Epic 4 — Index generation**
  - Build the frontmatter-scan index script (status table + supersession chain).
  - Run it in CI and/or compute it in the portal.

- **Epic 5 — Decision-aware agents**
  - Add a "list/read decisions" MCP tool.
  - Update architect/developer agent definitions to consult it.
  - Feed the decisions index as initial context.

- **Epic 6 — Mandatory-docs enforcement**
  - Add the PR template and Danger warn.
  - Add the docs-required CI gate (paths-filter + label escape hatch).
  - Add CODEOWNERS; promote the check from warn to required.

- **Epic 7 — Public site (optional)**
  - Stand up MkDocs + Material.
  - Add `deploy-docs.yml` to GitHub Pages.
  - Add `mkdocs-llmstxt`.

## 8. Definition of Done (for the rollout, not the spike)

- Standard captured in **ADR-001**.
- **≥3 ADRs** migrated with valid frontmatter.
- **Validation runs in CI**.
- The **in-core portal** shows decisions and is searchable.
- The **mandatory-docs PR gate** is active (at least as a warn).
- **PR #277 converged** (merged or superseded by this work).
