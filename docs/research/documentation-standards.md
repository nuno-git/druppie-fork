---
id: research-documentation-standards
title: "Documentation Standards, Format & Flow — Research"
type: research
status: complete
author: Druppie team
date: 2026-06-25
tags: [documentation, adr, ai-agents, tooling]
---

# Documentation Standards, Format & Flow — Research

## TL;DR

This is the Definition-of-Done deliverable for the developer spike **"Vast documentatieformat & flow"** (fixed documentation format & flow). Our recommendations, in one breath:

- **Format**: Markdown + YAML frontmatter, in **MADR style** (Markdown Any Decision Records) for decisions. Validate the frontmatter with **JSON Schema**. Reserve XML-style semantic tags for the moment documents are assembled **into a Claude prompt/context** — not as the on-disk format.
- **Publishing**: extend Druppie's existing in-core Documentation Portal (`/documentation`) as the primary docs page — it live-fetches from the repo so it auto-updates on push with no build step; an external MkDocs/GitHub Pages site is an optional public variant.
- **Process**: a **"consult-decisions-before-coding"** workflow, fed to Druppie agents the same lazy, tool-mediated way they already read files (via MCP read tools), eventually rolled up into a generated **"current decisions"** index loaded first.
- **Directory layout**: `/docs/decisions` (ADRs), `/docs/process`, `/docs/guides`, with spike templates in `/docs/research/templates`.
- **Continuous docs**: auto-publish on every push to `colab-dev`, and a layered, escape-hatchable PR gate (template → Danger warn → required `paths-filter` check → CODEOWNERS) so code never merges without documentation. See Part F.

We did not only reason about formats — we **ran a controlled AI-readability experiment** (Part A). Headline result: all four candidate formats are highly AI-readable; the only divergence across 4 formats × 3 tasks × 2 models was the `id` of a classic ADR that encodes its id only in a heading. Explicit named fields (frontmatter/XML/JSON) give deterministic, model-independent extraction of machine keys.

We also assessed the existing draft **PR #277** (spec-driven documentation framework) independently: it already converges on our frontmatter ADR recommendation; we list concrete gaps to fix before merge (Part E).

---

## 1. Context

### 1.1 How Druppie agents consume documentation today

Any documentation standard for this platform has to fit how our agents actually read. The ground truth in our core:

- Agents are defined in `druppie/agents/definitions/*.yaml` (id, system_prompt, mcps tool allow-list, skills, llm_profile). Prompt assembly happens in `druppie/agents/prompt_builder.py`.
- **CRITICAL: no repo files or docs are injected into prompts automatically.** An agent only gets a document into context when it actively **CALLS a read tool** (`coding:read_project_file` / `filesearch:read_file`). Context between agents is relayed only as short *"previous agent summary"* strings. Agents act exclusively through MCP tools — **tool-only communication**.
- **Skills are loaded lazily** via an `invoke_skill` tool (instructions fetched on demand), confirming a lazy, tool-mediated context model.
- **RAG today is distributed**: each generated app has its own pgvector store; there is **no central documentation-ingestion pipeline yet** (a `module-rag` orchestrator is spec-only/future). The platform's chunking defaults (`docs/RAG/rag-patterns.md`): recursive ~512-token chunks, 10–20% overlap, hybrid BM25 + dense retrieval, content-hash chunk IDs + section metadata for citations. **The format that fits this best is clean Markdown with a stable heading hierarchy and numbered sections.**
- Existing "agent reads docs" mechanisms: the **documenter** agent reads `docs/documentation.md` via `coding:read_project_file`; the **architect** writes `docs/technical-design.md`, reviewed at the `make_design` human gate.

**Architecture constraints (from `CLAUDE.md`) relevant to doc tooling:**

| Constraint | Implication for documentation tooling |
|---|---|
| Tool-only agents | Any doc generation/ingestion must be an **MCP tool**, not direct file output |
| Config in YAML, not DB | Doc/agent config stays in YAML files |
| No JSON/JSONB columns, no migrations | RAG metadata must be **relational or app-local pgvector** |
| Every new tool needs an MCP permission entry | A "read decisions" capability must be registered as a permissioned tool |
| No legacy/fallback code | Pick one format; no parallel parsers/shapes |

**Takeaway**: the recommended on-disk format must be (a) **directly readable by a tool-calling agent one file at a time**, and (b) **good input for the future recursive-512 chunking pipeline**. Clean Markdown with explicit frontmatter fields and stable headings satisfies both.

### 1.2 Existing `/docs` state — gap analysis

- **37 docs across 7 folders**, almost all plain Markdown. **No file uses real YAML/JSON frontmatter**; metadata is ad-hoc prose or tables (e.g. `Status: draft`, `Author: nuno` inline).
- ADR-like docs exist but are **inconsistent**: `docs/ADR-KUBERNETES.md` (decision matrix + mermaid), `docs/specs/*` (status headers), `docs/modules-research-and-decisions.md`, `docs/research-agent-runtime.md` (D2–D46 decision log). **No shared template, no machine-readable metadata, no cross-reference index**, Dutch/English mixed, most docs have no status field.

| Gap | Consequence today |
|---|---|
| No consistent metadata schema | Agents burn context parsing each doc individually |
| No doc-type classification | Reference and narrative blur together; worse retrieval chunks |
| No machine-readable decision links | Cross-document reasoning is unreliable |
| No lifecycle/status tracking | Superseded decisions get re-litigated |

---

## 2. Part A — Format evaluation

### 2.1 Candidate formats & AI-friendliness criteria

The user story asks us to evaluate formats by whether **an AI agent** can use them. Criteria per format:

1. **(a) Extract named fields** reliably
2. **(b) Infer cross-document links**
3. **(c) Summarize / detect changes**
4. **(d) Machine-validatable**
5. **(e) Human authoring cost**

Candidates: (1) Markdown + YAML/JSON frontmatter; (2) Markdown + XML-style semantic tags; (3) JSON Schema + Markdown explanation; (4) ADR with fixed fields (Nygard / MADR); (5) `llms.txt`; (6) Diátaxis (a framework, not a format).

### 2.2 The meta-finding that shapes everything

**The format best for an LLM to READ is not the best for an LLM to WRITE.** A peer-reviewed EMNLP-2024 study, *"Let Me Speak Freely?"*, found that forcing models to emit strict structured formats (e.g. JSON mode) **measurably degrades reasoning** — and the degradation is the *constraint itself*, not parse errors [16][17]. Anthropic likewise recommends **free-form reasoning first, then structured formatting** [1].

So a format can be excellent as **input context** yet a poor **target to generate**. **Conclusion: give agents richly structured input, but let them reason in free text and only emit into strict structure at the end.** This single insight justifies our split recommendation: structured Markdown on disk (great input), free-text reasoning, then a final write into validated frontmatter.

### 2.3 Qualitative comparison (cited)

1. **Markdown + YAML/JSON frontmatter** — the de-facto metadata convention for static site generators (Hugo, Jekyll, MkDocs) and GitHub Docs [2][4]. Not schema-checked by default but validatable via JSON Schema tooling (vscode-yaml [6], mkdocs-required-frontmatter-plugin [7], Material schema validation [8]); JS parser gray-matter [2]. *AI-friendliness*: extraction **strong** (`---...---` + `key: value` maps onto YAML training data), cross-doc links **moderate** (by tag/convention), summarize/change **strong** for metadata, validatable **moderate–strong** with tooling, authoring cost **low**.

2. **Markdown + XML-style semantic tags** — Anthropic explicitly recommends XML tags to structure prompts; they "help Claude parse complex prompts unambiguously," with benefits of clarity/accuracy/flexibility/parseability, no reserved tag names, nestable for hierarchy [1][10]. Primarily an **input/prompt** technique. *AI-friendliness*: extraction **strong** for role-bounded content but tags carry semantics not typed values, cross-doc links **moderate**, summarize/change **strong**, validatable **weak** (not real XML/XSD), authoring cost **moderate** (verbose).

3. **JSON Schema + Markdown explanation** — declarative validation plus "human-readable and machine-readable documentation" [11][12]; mature validators including machine-readable output formats [13]. *AI-friendliness*: extraction **strongest** (typed named fields), cross-doc links **strongest** (first-class resolvable `$ref`/`$id`), summarize/change **strong and deterministic** (schema diff is mechanical), validatable **strongest**, authoring cost **high** (verbose; prose must stay in sync; flat extracts better than deeply nested [14]). *Caveat*: use as a **target/validator**, not the reasoning medium [16][17].

4. **ADR with fixed fields** — Nygard original (Title/Status/Context/Decision/Consequences), immutable, status lifecycle `proposed → accepted → deprecated → superseded` [15][18]. **MADR** (Markdown Any Decision Records, adr.github.io, v4.0.0 released 17 Sep 2024) adds Jekyll-compatible YAML frontmatter (status, date, decision-makers, consulted, informed) — effectively format #1 + fixed ADR fields; files numbered `nnnn-title.md` in `docs/decisions` [19][20]. Tooling: adr-tools CLI (supersede, link, Graphviz of the decision graph) [21], log4brains (renders MADR to a static site) [15]. *AI-friendliness*: extraction **strong**, cross-doc links **strongest among prose formats** (explicit supersedes/superseded-by/link), summarize/change **strong** (immutable + numbered + status transitions = clean history), validatable **moderate**, authoring cost **low–moderate**. **ADR/MADR is the best-balanced format for the user story.**

5. **`llms.txt` (emerging)** — Jeremy Howard's proposal (3 Sep 2024): a `/llms.txt` Markdown index of a site with a required H1, a blockquote summary, and H2 link sections; serve clean `.md` at `url + .md` [22][28]. Adopted by Anthropic, Stripe, Zapier, Cloudflare [23] **but** Google declined to support it (Illyes/Mueller compared it to the ignored keywords meta tag), and a 300k-domain study found no link to citation frequency [24][25]. Treat as a **cheap, unproven navigation index**. extraction **weak**, cross-doc links **strong** by design, validatable **weak**, authoring cost **low**.

6. **Diátaxis (framework, not a format)** — Daniele Procida's four doc types: Tutorials / How-to / Reference / Explanation [26][27]. Improves AI consumption *indirectly* by separating facts (reference) from narrative (explanation) → cleaner retrieval chunks. Pairs naturally with **Docs-as-Code** (docs in git, reviewed via PR, built in CI).

### 2.4 Comparison summary table

Ratings: ●●● strong / ●● moderate / ● weak.

| Format | Extract fields | Cross-doc links | Summarize/change | Validatable | Low authoring cost | Best role |
|---|:---:|:---:|:---:|:---:|:---:|---|
| Markdown + YAML frontmatter | ●●● | ●● | ●●● | ●● | ●●● | **On-disk format** |
| Markdown + XML tags | ●●● | ●● | ●●● | ● | ●● | Prompt-assembly only |
| JSON Schema + Markdown | ●●● | ●●● | ●●● | ●●● | ● | Validator / target |
| ADR / MADR (fixed fields) | ●●● | ●●● | ●●● | ●● | ●●● | **Decisions (recommended)** |
| `llms.txt` | ● | ●●● | ●● | ● | ●●● | Nav index for AI |
| Diátaxis (framework) | — | — | — | — | — | Doc-type taxonomy |

### 2.5 Empirical AI test (centrepiece)

We did not just reason about the formats — we **ran a controlled experiment**, exactly as the user story asks ("per format I tested whether an AI agent can extract fields / link documents / detect changes").

**Method.** One decision — **ADR-007 "Rolling deployment strategy for generated sandbox apps"** — was rendered in **4 formats**: (i) YAML frontmatter, (ii) XML tags, (iii) JSON + schema, (iv) classic ADR with **no `id` field**. For each format, a **fresh agent that saw ONLY the given document(s)** ran **3 tasks**:

- **(a) Extraction** — extract **9 named fields** (`id`, `title`, `status`, `date`, `deciders`, `supersedes`, `num_consequences`, `num_positive`, `num_negative`) and return JSON.
- **(b) Cross-doc linking** — given ADR-007 + a linked **PRD-014**, answer "which decision constrains a new config-reload feature and what does it require?"
- **(c) Change detection** — detect what changed between **V1** and **V2** of the ADR.

Extraction was run with **both a strong (Opus-class) and a weak (Haiku) model**. Answers were graded against a fixed ground truth. The fixtures and full results are stored in `docs/research/format-evaluation/`.

**Results.**

| Format | Extraction (strong model) | Extraction (weak / Haiku) | Cross-doc linking | Change detection |
|---|---|---|---|---|
| Markdown + YAML frontmatter | 9/9 exact | 9/9 exact (id `007`) | Correct & complete | 3/3 changes |
| Markdown + XML tags | 9/9 exact | 9/9 exact (id `007`) | Correct & complete | 3/3 changes |
| JSON + schema | 9/9 exact | 9/9 exact (id `007`) | Correct & complete | 3/3 changes |
| Classic ADR (no `id` field) | 8/9 — id read as `ADR-007` | 8/9 — id read as `7` | Correct & complete | 3/3 changes |

**Findings.**

1. **All four formats are highly AI-readable.** Cross-doc linking and change detection were **100% correct** across every format and model — modern agents handle clean structured Markdown well.
2. The **only divergence** across 4 formats × 3 tasks × 2 models was the **`id` of the classic ADR**, which encodes its id only in the heading `# 7.` with no dedicated field: inferred as `ADR-007` (strong model) and `7` (weak model), **neither matching the canonical `007`**.
3. **Implication**: an explicit named field (frontmatter / XML / JSON) yields **deterministic, model-independent extraction** of machine keys. Any generator or index that keys on an exact `id` **must not depend on values encoded only in prose/headings**.
4. **Caveat / honesty**: the documents were small and clean. With larger, noisier real docs and weaker models, the gap between explicit-field and prose-encoded formats will **widen** — so this is a **lower bound** on the advantage of explicit fields, not the full picture.

### 2.6 Part A conclusion

Recommend **Markdown + YAML frontmatter in MADR style** as the on-disk format. It gives:

- **Explicit machine-keyed fields** → deterministic extraction (proven above),
- the **strongest cross-document linking among prose formats** (`supersedes` / `superseded_by` / `linked_*`),
- **append-only, diffable history**,
- **low human authoring cost**, and
- exactly the **clean-Markdown-with-stable-headings** shape our future RAG chunking wants.

Use **JSON Schema to validate the frontmatter** (machine-checkable), and **reserve XML-style tags for the moment docs are assembled into a Claude prompt**.

---

## 3. Part B — Documentation page (presentation layer)

**Requirements**: searchable, git-versioned, auto-built on push, AI-readable.

### 3.1 Primary proposal — extend Druppie's in-core Documentation Portal

**Druppie ALREADY HAS an in-core documentation page**, so this proposal **EXTENDS** it rather than building a new presentation layer from scratch. The existing pieces:

- **Frontend**: `frontend/src/pages/Documentation.jsx` — a React "Documentation Portal" page using `react-markdown` + `remark-gfm`, with a `CodeBlock` component (syntax highlighting) and a `MermaidBlock` component (diagram rendering), laid out as collapsible cards grouped by category (currently Agents, Modules, Applications, MCPs, Tools). Routed at `/documentation` in `App.jsx` and surfaced in the NavRail as "Documentation Portal".
- **Backend**: `druppie/api/routes/documentation.py` exposes `GET /api/documentation` (auth-gated), delegating to `DocumentationService`.
- **Service**: `druppie/services/documentation_service.py` scans projects in the DB, fetches `docs/documentation.md` from each repo's `main` branch via Gitea, and caches results in a relational `DocumentationCache` table with a ~60-second TTL. Known source types: gitea, core_file, agent_def, module, mcp, tool.

**Why in-core is the right primary choice:**

- **(a) It already exists and is behind auth.** Decisions/ADRs and internal process docs are governance content; the portal already sits behind Keycloak auth, which fits internal content far better than a public website.
- **(b) It matches how Druppie agents actually consume docs.** Agents read documentation via the `coding` MCP tools `read_file` / `search_files` / `grep` — not via a rendered website. The platform is **tool-only**; there is no FastAPI StaticFiles serving. A docs *page* for humans and the *files* agents read are then one and the same source.
- **(c) The user story explicitly allowed "via Druppie zelf"** — surfacing the documentation inside Druppie itself is in scope.

**KEY ADVANTAGE on the "auto-update on push" requirement.** Because `DocumentationService` fetches **live** from the repo's `main` branch and caches only **~60 seconds**, documentation changes appear in the portal **automatically within about a minute of a push** — there is **NO separate static-site build/deploy step**. This satisfies the DoD requirement "automatically updated on push" **natively**, with no CI pipeline to maintain.

**How the hard requirements are met in-core:**

| Requirement | How it is met in the in-core portal |
|---|---|
| **Searchable** | The portal renders all entries client-side; add a **filter/search box** over titles + frontmatter (id/status/tags) — a small frontend change in `Documentation.jsx`. |
| **Version-controlled** | **Git is the single source of truth** — the markdown files live in the repo; nothing is authored in the DB. |
| **Auto-update on push** | The **live-fetch + ~60s cache** above: changes appear within ~a minute, no build. |
| **AI-readable** | Agents read the same `docs/decisions/*` markdown directly via the `coding` MCP tools. |

**Concrete extension steps (small):**

1. **Add a new `source_type`** (e.g. `decisions`) to the relational `DocumentationCache` model — **no JSON column** (stays relational), and **reset the DB rather than migrate** (per CLAUDE.md constraints).
2. **Extend `DocumentationService`** to also fetch `docs/decisions/*.md` (parse YAML frontmatter for `id` / `title` / `status` / `date`) plus the generated decisions **index page**.
3. **Add a new `<DocSection>` "Decisions (ADRs)"** in `Documentation.jsx` rendering **status badges**, a **per-feature progress log**, and **links to user stories / PRs**.
4. **Agents keep reading the same `docs/decisions/*` files** via the `coding` MCP tools — the Phase-4 "read decisions" MCP tool is just a **thin convenience wrapper** over the files agents already read.

### 3.2 Optional public variant — external static site (MkDocs)

If the team later wants a **public**, strongly-searchable, versioned site (or an `llms.txt` index for external agents), an external static-site generator is an **optional addition** on top of the same markdown — **not** the primary internal solution. Both the in-core portal and any external site read from the **SAME source markdown in the repo**, so there is a single source of truth.

| SSG | Stack | Search | Versioning | Mermaid | `llms.txt` | Maintenance |
|---|---|---|---|---|---|---|
| **MkDocs + Material** | Python/pip [SSG1] | Offline client-side lunr, no server [SSG12] | via `mike` → gh-pages [SSG2][SSG8] | **Native, no plugin** [SSG11] | mkdocs-llmstxt / mkdocs-llmstxt-md [SSG15][SSG16] | **Low** |
| **Docusaurus** | Node/React/MDX [SSG9][SSG10] | Algolia DocSearch free [SSG14] or local plugin | First-class [SSG3] | via theme [SSG5] | docusaurus-plugin-llms [SSG17] | Heavier |
| **mdBook** | Rust [SSG6] | Built-in [SSG7] | **None native [SSG4]** (disqualifying) | via preprocessor | — | Low |
| **Hand-maintained `docs/index.md`** | None | grep only | git | GitHub renders natively | raw `.md` already reachable | Zero build, doesn't scale |

**If you do build the optional external site, prefer MkDocs + Material.** Stack-fit: the backend is Python/FastAPI; MkDocs lives in the same toolchain, so there is **no second Node runtime just for docs**. It satisfies every hard requirement for a public site out of the box (searchable, git-versioned, CI-built, native Mermaid) and emits **`llms.txt`** for external AI agents.

**Trade-offs / cautions (external variant only):**

- `mike` versioning takes some CI setup [SSG8] — **skip it until multi-version docs are actually needed**.
- `mkdocs-llmstxt` is in maintenance mode [SSG15] — **pin it, or prefer `mkdocs-llmstxt-md`** [SSG16].
- Pick **Docusaurus only** if you want MDX/React components sharing the frontend design system.

### 3.3 Proposed page structure

The structure below maps onto the in-core portal's `<DocSection>`s (and equally onto the optional external site, since both read the same markdown):

```
docs/
├── decisions/              # ADRs (frontmatter), source for the "Decisions (ADRs)" DocSection
│   ├── index.md            # generated overview — all decisions + status + supersession chain
│   └── NNN-kebab-title.md  # individual ADRs
├── process/                # Workflow guides ("consult decisions before coding")
└── guides/                 # How-tos
```

Sections to surface in the portal:

1. **Decisions overview** — all ADRs listed with a **status badge** (proposed / accepted / superseded) and the supersession chain.
2. **Per-feature progress log** — track each feature's state over time.
3. **Links to user stories and code** — each ADR links to its `linked_prd`, user stories, and the PR(s)/issue(s) that implemented it.
4. **Guides / process** — the "consult decisions before coding" workflow and how-tos.

---

## 4. Part C — Process improvement workflow

### 4.1 "Consult decisions before writing code"

For a developer **or** an AI agent, the loop is:

1. **Before new code** → query the **decisions index**: which prior decisions are relevant? what patterns / constraints / trade-offs already exist?
2. **Apply the existing pattern** if one fits.
3. **If the decision is genuinely new** → author a new ADR (`proposed → reviewed → accepted`).

### 4.2 How this maps to Druppie's reality

Agents read docs **lazily via MCP read tools**, so the workflow becomes: **an agent calls a "list/read decisions" step first.** Longer term, a **generated decisions index** (analogous to a "current decisions" rollup) is loaded first, so the agent **starts decision-aware**.

> **Constraint**: this must be delivered as an **MCP tool**, not file injection, per our tool-only architecture. A file/CI-based generator is fine for the *docs site*, but anything the *agent* consults at runtime goes through a permissioned MCP tool.

### 4.3 Concrete scenarios

**Scenario 1 — Developer.** A developer wants to add a new deploy strategy. They first read the existing **ADR-007 (rolling deployment)** and **reuse the `maxSurge=1` / `maxUnavailable=0` + health-check pattern** instead of reinventing it. Result: faster, consistent, no re-litigating a settled decision.

**Scenario 2 — AI agent on a feature branch.** Before generating code, the **Druppie coding agent pulls the decisions index / relevant ADRs as context**, then **generates code that already respects accepted decisions** (e.g. layered architecture, no JSON columns). Result: fewer review cycles, fewer wrong assumptions.

---

## 5. Part D — Recommended tooling & implementation plan

### 5.1 Directory structure

| Path | Purpose |
|---|---|
| `/docs/decisions/` | ADRs, named `NNN-kebab.md` |
| `/docs/process/` | Workflow + process guides |
| `/docs/guides/` | How-tos |
| `/docs/research/templates/` | Templates delivered by this spike |

### 5.2 Templates delivered by this spike

This spike delivers an **ADR template** and a **PRD template**:

- `docs/research/templates/adr-template.md`
- `docs/research/templates/prd-template.md`

**Minimal ADR example (the DoD-required template).** Frontmatter fields + fixed sections:

```markdown
---
id: 007
title: "Rolling deployment strategy for generated sandbox apps"
status: accepted          # proposed | accepted | deprecated | superseded
date: 2026-05-12
deciders: [nuno, kilian]
supersedes: []            # e.g. [005]
superseded_by: null       # e.g. 012
linked_prd: PRD-014
tags: [deployment, kubernetes, sandbox]
---

## Context
Why this decision is needed; forces and constraints at play.

## Decision
The choice made (e.g. rolling update, maxSurge=1 / maxUnavailable=0, health checks).

## Consequences
Positive and negative outcomes; follow-on work.

## Compliance
How adherence is checked (validator, import-linter contract, review gate).
```

Field summary: `id`, `title`, `status`, `date`, `deciders`, `supersedes`, `superseded_by`, `linked_prd`, `tags`; sections **Context / Decision / Consequences / Compliance**.

### 5.3 Overview / index generation

A small script scans `/docs/decisions/*.md`, parses the frontmatter, and emits an **index page** containing a **status table** and the **supersession chain**.

> **Scope note**: per the spike scope, **we deliver the report + templates**. The **generator script and CI wiring are the recommended NEXT implementation steps**, not built here. Any **in-platform** generation must be exposed as an **MCP tool** (tool-only constraint); a **CI/file-based** generator is fine for the docs site itself.

### 5.4 CI step (GitHub Actions → GitHub Pages)

**For the PRIMARY in-core portal, NO static-site CI/deploy is required** — it reads live from the repo and refreshes within ~a minute of a push. The GitHub Actions workflow below applies **only if the team also wants the optional external public site** (Part B §3.2).

On push, build the MkDocs site, publish to GitHub Pages, and generate `llms.txt`. Sketch:

```yaml
name: docs
on:
  push:
    branches: [main]
permissions:
  contents: read
  pages: write
  id-token: write
jobs:
  build-deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install mkdocs-material mkdocs-llmstxt-md
      - run: mkdocs build              # emits site/ + llms.txt
      - uses: actions/upload-pages-artifact@v3
        with: { path: site }
      - uses: actions/deploy-pages@v4
```

(Equivalent one-liner alternative: `mkdocs gh-deploy`.)

### 5.5 Phased plan

| Phase | Deliverable |
|---|---|
| **Phase 1** | Adopt frontmatter + ADR template + `/docs/decisions` |
| **Phase 2** | Add **JSON-Schema validation AND the docs-required PR gate** (start as a Danger warn, mirror PR #277's validators into CI) on `pull_request`. |
| **Phase 3** | **Extend the in-core Documentation Portal to surface `docs/decisions/*`** (new `source_type` + `<DocSection>` + search box) — the **primary docs page**, auto-updating via live-fetch (no build). Then **promote the docs-required gate to a REQUIRED status check** + add CODEOWNERS on `docs/`. |
| **Phase 4** | Expose a **"read decisions" MCP tool** so Druppie agents become decision-aware |
| **Phase 5 (optional)** | Stand up the **external public site** — MkDocs + GitHub Pages auto-publish with a pre-build index/`llms.txt` generation step — for public, strongly-searchable, versioned docs and external AI agents. |

---

## 6. Part E — Independent comparison with existing draft PR #277

This was assessed **independently** — we did our own research first, then compared. PR #277 ("spec-driven documentation framework") already implements much of a compatible direction. Credit first, then gaps.

### 6.1 What it does well

- **Coherent end-to-end traceability**: PRD ↔ ADR ↔ BDD ↔ CAS.
- **Real enforcement** via lefthook pre-commit/pre-push (ruff, black, import-linter, doc-link & adr-status validators, pytest/behave).
- **Zero-dependency stdlib scripts**.
- **import-linter contracts** matching the layered architecture (api ⊥ db, domain ⊥ everything).
- Its **ADR template already uses YAML frontmatter** (`id`/`title`/`status`/`date`/`deciders`/`superseded_by`/`linked_prd`) — **matching our independent recommendation**, a strong sign of convergence.

### 6.2 Gaps / risks to address before merge

| # | Gap | Fix |
|---|---|---|
| 1 | **Template-vs-skill DRIFT** — skill files describe a different ADR shape (`## Status` body section, no frontmatter) than the actual frontmatter templates; agents will emit inconsistent files and the parser will mishandle skill-style ADRs | Pick **one** format (the frontmatter template) and make skills match |
| 2 | **CAS "freshness" uses filesystem `mtime`**, which resets on git clone/checkout → false stale/fresh in CI | Key off **git or content hashes** instead |
| 3 | **Three separate hand-rolled regex YAML parsers** (`validate_doc_links` uses a weaker one) → inconsistent parsing | Consolidate on **one parser** (ideally PyYAML or a shared util) |
| 4 | **Memory/context-budget pillar documented but unimplemented** | Mark **aspirational** so it isn't mistaken for shipped |
| 5 | **No CI workflow file** in the diff — enforcement depends on locally-installed lefthook/import-linter/behave | Add a **GitHub Actions** job |
| 6 | **`generate_cas` domain inference is heuristic/brittle** | Harden the inference |

### 6.3 Recommendation

**Converge.** Keep PR #277's enforcement + traceability spine, then:

1. Fix the **format drift** to the single frontmatter ADR template validated above.
2. Replace **mtime freshness** with git/hash.
3. Consolidate the **YAML parser**.
4. Add the **CI workflow**.
5. Add the **MkDocs + `llms.txt`** publishing layer this report recommends.

---

## 7. Part F — Continuous documentation & PR enforcement

This section answers two operational requirements: (1) the docs site must AUTO-UPDATE on every change, and (2) when a PR is ready, documentation must be delivered with it — it cannot be silently skipped.

### F.1 Auto-update the docs site on every change

- A GitHub Actions workflow triggers on push to `colab-dev`. Recommended pattern: build job uploads the rendered `site/` as a Pages artifact, a dependent deploy job publishes via `actions/deploy-pages@v4` (no `gh-pages` branch to maintain) [ENF3][ENF4]; the simpler `mkdocs gh-deploy` is the one-liner alternative [ENF1][ENF2].
- KEY: regenerate derived pages BEFORE building, as a pre-build step (e.g. `python scripts/generate_index.py && mkdocs build`), so the auto-generated decisions index and `llms.txt` are always current and never hand-committed [ENF1]. This is what realises the DoD requirement "automatically updated on push": every merge rebuilds and republishes the site, index included.
- A ready-to-adapt sample is delivered at `docs/research/examples/deploy-docs.yml`.

### F.2 Mandatory documentation on every PR — a layered gate

Design as tiers from soft to hard, WITH escape hatches, to avoid the well-documented "checkbox docs" failure mode where contributors satisfy the letter (touch a docs file) without real content [ENF13][ENF14]:

1. PR template (soft) — `.github/pull_request_template.md` with a documentation checklist (which ADR/PRD does this implement? new decision needed? docs updated?) [ENF12].
2. Danger warn (medium) — a Dangerfile that WARNS when `druppie/**` or `frontend/src/**` changed without any `docs/**` change [ENF13][ENF14]. Include this short example:

```javascript
const m = danger.git.modified_files;
const code = m.some(f => f.startsWith("druppie/") || f.startsWith("frontend/src/"));
const docs = m.some(f => f.startsWith("docs/"));
if (code && !docs) warn("Code changed but no docs/ update — intentional? Reference an ADR/PRD or add one.");
```

3. Required CI gate (hard) — a `pull_request` workflow that uses `dorny/paths-filter` to compute code-vs-docs changes and FAILS when code changed AND no docs changed AND the PR references no `ADR-\d+`/`PRD-\d+` AND there is no `docs-exempt` label [ENF6]. Make it a REQUIRED status check via branch protection / a ruleset on `colab-dev` so it actually blocks merge [ENF8][ENF9]. Sample delivered at `docs/research/examples/docs-required.yml`.
4. CODEOWNERS (quality) — map `/docs/ @docs-maintainers` so doc changes get a human review; this shifts enforcement from "a file changed" (gameable) to "a maintainer approved the docs" [ENF17].
5. Mirror PR #277's validators into CI — run `validate_adr_status.py` + `validate_doc_links.py` in the same PR workflow so any included docs are well-formed; this directly fills PR #277's noted gap (its validators run only in local lefthook, not in CI).

> CRITICAL GOTCHA: do NOT put path filters in the workflow's top-level `on:` clause. If a PR matches nothing, the job never runs, and a REQUIRED check then sits "Expected — Waiting for status to be reported" forever, making the PR unmergeable. Always run the gate workflow and put the path logic in steps [ENF10][ENF11].

Escape hatches so trivial PRs aren't punished: a `docs-exempt` label, and conventional `chore:`/`ci:` PR-title prefixes that skip the hard gate [ENF15][ENF16].

### F.3 Tiered policy — which change needs what

| Change type | Requirement |
|---|---|
| New feature / architectural change / new dependency / public API change | MUST add or reference an ADR/PRD (hard gate blocks merge) |
| Bugfix / refactor / chore / docs-only | Danger warn + PR-template checklist; `docs-exempt` allowed |

This mirrors the framework's own rule that an ADR is written only for significant decisions — so the gate enforces documentation proportional to impact.

**Dogfooding note**: Druppie already produces `docs/technical-design.md` at the `make_design` human gate; the same "documentation present" criterion can become part of an agent session's done-condition, and the Phase-4 "read decisions" MCP tool makes agents reference/author decisions as they code — so the platform enforces on its own agents what the CI gate enforces on humans.

---

## 8. Sources

### Formats
1. Anthropic — Use XML tags to structure prompts: https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/use-xml-tags
2. Markdown Frontmatter and YAML: https://openmarkapp.com/blog/markdown-frontmatter-yaml
4. GitHub Docs — Using YAML frontmatter: https://docs.github.com/en/contributing/writing-for-github-docs/using-yaml-frontmatter
6. vscode-yaml front matter validation: https://github.com/redhat-developer/vscode-yaml/issues/207
7. mkdocs-required-frontmatter-plugin: https://github.com/unmc-vcr/mkdocs-required-frontmatter-plugin
8. Material for MkDocs schema/validation: https://squidfunk.github.io/mkdocs-material/plugins/meta/
10. Claude XML tags examples: https://www.aipromptlibrary.app/blog/claude-xml-tags-prompt-engineering
11. JSON Schema (RESTfulAPI): https://restfulapi.net/json-schema/
12. What is JSON Schema (Postman): https://blog.postman.com/what-is-json-schema/
13. networknt/json-schema-validator: https://github.com/networknt/json-schema-validator
14. Beyond JSON — formats for LLM pipelines: https://medium.com/@michael.hannecke/beyond-json-picking-the-right-format-for-llm-pipelines-b65f15f77f7d
15. MADR / log4brains: https://adr.github.io/madr/
16. Let Me Speak Freely? (arXiv): https://arxiv.org/abs/2408.02442
17. Let Me Speak Freely? (ACL): https://aclanthology.org/2024.emnlp-industry.91/
18. Nygard ADR template/lifecycle: https://github.com/joelparkerhenderson/architecture-decision-record
19. adr/madr: https://github.com/adr/madr
20. MADR template fields: https://adr.github.io/madr/
21. npryce/adr-tools: https://github.com/npryce/adr-tools
22. llmstxt.org: https://llmstxt.org/
23. Search Engine Land on llms.txt: https://searchengineland.com/llms-txt-proposed-standard-453676
24. SEJ — Mueller on llms.txt: https://www.searchenginejournal.com/googles-mueller-says-llms-txt-cant-help-llms-differentiate-sites/579304/
25. Search Engine Roundtable — Google does not endorse llms.txt: https://www.seroundtable.com/google-does-not-endorse-llms-txt-40789.html
26. Diátaxis: https://diataxis.fr/
27. Diátaxis start here: https://diataxis.fr/start-here/
28. Answer.AI llms.txt proposal: https://www.answer.ai/posts/2024-09-03-llmstxt.html

### Static-site generators
- SSG1. Material for MkDocs: https://squidfunk.github.io/mkdocs-material/
- SSG2. MkDocs versioning: https://squidfunk.github.io/mkdocs-material/setup/setting-up-versioning/
- SSG3. Docs versioning comparison: https://tw-docs.com/docs/static-site-generators/docs-versioning/
- SSG4. mdBook versioning issue: https://github.com/rust-lang/mdBook/issues/494
- SSG5. Docusaurus Mermaid: https://docusaurus.io/docs/markdown-features/diagrams
- SSG6. mdBook CI: https://rust-lang.github.io/mdBook/continuous-integration.html
- SSG7. mdBook search config: https://rust-lang.github.io/mdBook/format/configuration/general.html
- SSG8. Versioning with Material for MkDocs: https://blog.lx862.com/blog/2025-06-10-versioning-with-material-mkdocs/
- SSG9. Docusaurus deployment: https://docusaurus.io/docs/deployment
- SSG10. Docusaurus review: https://ferndesk.com/blog/docusaurus-review
- SSG11. mkdocs mermaid2 plugin: https://github.com/fralau/mkdocs-mermaid2-plugin
- SSG12. MkDocs site search: https://squidfunk.github.io/mkdocs-material/setup/setting-up-site-search/
- SSG13. Docusaurus search: https://docusaurus.io/docs/search
- SSG14. Algolia DocSearch free: https://www.algolia.com/blog/product/algolia-docsearch-is-now-free-for-all-docs-sites
- SSG15. mkdocs-llmstxt: https://github.com/pawamoy/mkdocs-llmstxt
- SSG16. mkdocs-llmstxt-md: https://github.com/noklam/mkdocs-llmstxt-md
- SSG17. docusaurus-plugin-llms: https://github.com/rachfop/docusaurus-plugin-llms

### Continuous documentation & PR enforcement
- ENF1. Material for MkDocs — Publishing your site: https://squidfunk.github.io/mkdocs-material/publishing-your-site/
- ENF2. MkDocs — Deploying your docs: https://www.mkdocs.org/user-guide/deploying-your-docs/
- ENF3. GitHub Pages — custom workflows: https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages
- ENF4. actions/deploy-pages: https://github.com/actions/deploy-pages
- ENF5. mkdocs-deploy-gh-pages: https://github.com/mhausenblas/mkdocs-deploy-gh-pages
- ENF6. dorny/paths-filter: https://github.com/dorny/paths-filter
- ENF7. tj-actions/changed-files: https://github.com/tj-actions/changed-files
- ENF8. GitHub rulesets — required status checks: https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets
- ENF9. GitHub branch protection — required status checks: https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/managing-a-branch-protection-rule
- ENF10. GitHub community #54877 — paths-ignore pending-forever trap: https://github.com/orgs/community/discussions/54877
- ENF11. GitHub Docs — troubleshooting required status checks: https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/collaborating-on-repositories-with-code-quality-features/troubleshooting-required-status-checks
- ENF12. PR templates with checklists: https://www.bornfight.com/blog/how-to-protect-github-projects-from-non-reviewed-code-and-force-code-review-culture/
- ENF13. Danger JS: https://danger.systems/js/
- ENF14. Danger JS — the Dangerfile: https://danger.systems/js/guides/the_dangerfile
- ENF15. amannn/action-semantic-pull-request: https://github.com/amannn/action-semantic-pull-request
- ENF16. Conventional Commits v1.0.0: https://www.conventionalcommits.org/en/v1.0.0/
- ENF17. GitHub Docs — About code owners: https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners
