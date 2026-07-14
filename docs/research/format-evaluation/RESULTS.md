# Empirical AI-extraction test — results

## Ground truth

**Field extraction** (the canonical values, ADR-007):

- id = `007`
- title = `Rolling deployment strategy for generated sandbox apps`
- status = `accepted`
- date = `2026-05-12`
- deciders = `[nuno, kilian]`
- supersedes = `ADR-003`
- consequences = 4 (2 positive, 2 negative)

The extraction task scored each of **9 JSON keys**: `id`, `title`, `status`,
`date`, `deciders`, `supersedes`, `num_consequences` (=4), `num_positive` (=2),
`num_negative` (=2) — so a perfect run is **9/9**.

**Cross-doc linking** (ADR-007 + PRD-014): ADR-007 constrains the work — it
requires a rolling-deployment path **and** passing a health check before the
traffic switch **and** a `/health` endpoint **and** `maxSurge=1`/`maxUnavailable=0`
**and** tolerating transient ~2x memory usage during rollout.

**Change detection** (V1 -> V2):

- status `proposed` -> `accepted`
- `supersedes: ADR-003` added
- consequence "Requires a /health endpoint on every generated app" added

## Results

| Format | Field extraction (strong model) | Field extraction (weak model / Haiku) | Cross-doc linking | Change detection |
|---|---|---|---|---|
| 1. Markdown + YAML frontmatter | 9/9 exact | 9/9 exact (id=`007`) | Correct & complete | 3/3 changes found |
| 2. Markdown + XML tags | 9/9 exact | 9/9 exact (id=`007`) | Correct & complete | 3/3 changes found |
| 3. JSON + schema | 9/9 exact | 9/9 exact (id=`007`) | Correct & complete | 3/3 changes found |
| 4. Classic ADR (no id field) | 8/9 — id read as `ADR-007` (≠ `007`) | 8/9 — id read as `7` (≠ `007`) | Correct & complete | 3/3 changes found |

## Findings

1. **All four formats are highly AI-readable.** Cross-doc linking and
   change-detection were 100% correct across every format and every model.

2. **The only divergence** across 4 formats x 3 tasks x 2 models was the `id`
   field of the classic ADR, which has no dedicated machine field: it was
   inferred as `ADR-007` (strong model) and `7` (weak model), neither matching
   the canonical `007`.

3. **Implication:** formats carrying an explicit, named field (frontmatter, XML,
   JSON) yield deterministic, model-independent extraction of machine keys. A
   generator or index that keys on the exact `id` must not rely on values that
   are encoded only in prose or headings.

4. **Caveat:** these tasks used small, clean documents. With larger/noisier real
   documents and weaker models, the gap between explicit-field and
   prose-encoded formats is expected to widen — so this result is a **lower
   bound** on the advantage of explicit fields.
