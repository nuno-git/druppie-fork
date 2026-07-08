# Converged Documentation Framework — Implementation Plan

**Status:** Active
**Created:** 2026-07-08
**Supersedes:** PR #277 (Nuno), PR #283 (Merlijn) — converges both into a single shippable framework

## Context

Two PRs addressed the "vast documentatie format & flow" story:

- **PR #277** (Nuno) — *built* a documentation framework: spec, 3 validator scripts, CAS generator, 7 agent skills, 3 real ADRs, templates, lefthook hooks, BDD scaffolding, design-system docs. Ambitious but half-broken.
- **PR #283** (Merlijn) — *researched* what the framework should be: format evaluation, enforcement gate design, in-core portal argument, language policy, and a critique of #277's bugs. Good analysis, no code, oversold experiment.

**Decision:** Converge. Take Nuno's working artifacts as the base, apply Merlijn's fixes and additions, drop the dead weight from both.

## What's Wrong With Each PR

### PR #277 — Verified Bugs
1. **Template/skill drift** — `adr-writer` skill describes plain Markdown ADRs; `TEMPLATE.md` uses YAML frontmatter. Files produced per the skill fail validation.
2. **mtime-based freshness** — `validate_doc_links.py` compares `stat().st_mtime`. Git doesn't preserve mtimes → non-deterministic on clone/CI.
3. **3 divergent YAML parsers** — `generate_cas.py` (nested), `validate_adr_status.py` (flat, collapses nested maps), `validate_doc_links.py` (crudest). All hand-rolled, none use PyYAML.
4. **No CI workflow** — `.github/workflows/` has no docs gate. Only local lefthook hooks.
5. **`.importlinter` doubly broken** — TOML syntax in standalone file (needs INI), and `domain-independent` contract contradicts `layered-flow`.
6. **BDD layer can't run** — features reference non-existent PRDs, steps have no definitions, implementations are tautological.
7. **Memory pillar unimplemented** — pure prose in the spec, no code.
8. **Committed CAS.md** — auto-generated but committed; will silently rot.
9. **`id: 001` parsing bug** — unquoted `001` parses to int `1`, fails `^\d{3}$` regex.

### PR #283 — Verified Gaps
1. **Experiment not reproducible** — PRD-014 fixture and V2 versions don't exist in repo. Two of three tasks reference missing fixtures.
2. **No actual code** — pure documentation. No JSON schema, no generator, no validator, no CI.
3. **Deletes unrelated CI/CD files** — `.gitea/workflows/`, `cicd/act-runner/`, `docs/CI-CD.md` deleted without explanation.

## Implementation Plan

### Phase 0 — Import Nuno's Artifacts (as-is)
Take these files from PR #277 without modification:
- `docs/SPEC-FRAMEWORK.md` — the eight-pillar spec
- `docs/adrs/TEMPLATE.md`, `docs/prds/TEMPLATE.md`, `docs/research/TEMPLATE.md` — templates
- `docs/adrs/001-layered-architecture.md`, `002-no-json-columns.md`, `003-tool-only-communication.md` — real ADRs
- `docs/design-system/README.md`, `docs/design-system/components/button.md` — design system
- `scripts/generate_cas.py` — CAS generator
- `scripts/validate_adr_status.py` — ADR validator (will be fixed in Phase 1)
- `scripts/validate_doc_links.py` — link validator (will be fixed in Phase 1)

### Phase 1 — Fix Nuno's Bugs
1. **Replace 3 YAML parsers with PyYAML** — one dependency, one parser, correct nested-map handling. Delete `_parse_yaml_block`, the flat parser, and the `text.find("---")` hack in all three scripts.
2. **Kill template/skill drift** — rewrite the 7 agent skills to match the YAML frontmatter template. An agent following `adr-writer` must produce files that `validate_adr_status.py` accepts.
3. **Replace mtime with content-hash** — `validate_doc_links.py` should hash ADR contents and compare against a hash stored in CAS.md frontmatter, not `stat().st_mtime`.
4. **Un-commit CAS.md** — add to `.gitignore`, generate via pre-commit or CI.
5. **Fix `id: 001` parsing** — quote in template default, or don't `int()` before string-validating.
6. **Fix `validate_adr_status.py`** — the flat parser collapses the nested `enforcement:` map. PyYAML fix resolves this.

### Phase 2 — Fix Enforcement Layer
7. **Fix `.importlinter`** — convert to INI syntax (standalone file), remove `domain-independent` contract (contradicts `layered-flow`). Keep only `layered-flow`.
8. **Add CI workflow** — `docs-required.yml` using `dorny/paths-filter`, no top-level `paths:` filter (avoids pending-forever trap), with `docs-exempt` label escape hatch.
9. **Delete BDD scaffolding** — features reference non-existent PRDs, steps have no definitions. Dead weight. Defer BDD to a future phase.

### Phase 3 — Add Merlijn's Contributions
10. **Add `adr.schema.json`** — JSON Schema for ADR frontmatter validation. Wire into `validate_adr_status.py`.
11. **Adopt in-core portal as primary docs surface** — extend `DocumentationService` to serve CAS and ADR index. No MkDocs build step.
12. **Adopt language policy** — EN source-of-truth, NL auto-generated via existing `translate_from_english()`.
13. **Add consult-decisions MCP tool** — tool that lets agents query CAS/ADRs before coding.

### Phase 4 — Drop Dead Weight
- Merlijn's format-evaluation experiment (not reproducible, n=1, fixtures missing)
- Merlijn's MkDocs/Docusaurus SSG comparison (irrelevant if using in-core portal)
- Merlijn's deletion of Gitea CI/CD files (unrelated scope creep)
- Nuno's Memory pillar (pure prose, no implementation path)
- Nuno's BDD features and step implementations (broken)

## Acceptance Criteria
- [ ] All 3 validator scripts use PyYAML, no hand-rolled parsers
- [ ] Agent skills produce files that pass validation
- [ ] CAS freshness check is deterministic (content-hash, not mtime)
- [ ] CAS.md is gitignored, not committed
- [ ] `.importlinter` is valid INI, doesn't block commits
- [ ] `docs-required.yml` CI gate works without pending-forever trap
- [ ] `adr.schema.json` validates committed ADR frontmatter
- [ ] No broken BDD scaffolding in repo
- [ ] All committed ADRs pass `validate_adr_status.py`
- [ ] Backend rebuilds and lints clean
