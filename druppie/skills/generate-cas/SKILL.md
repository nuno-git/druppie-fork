---
name: generate-cas
description: >
  Generates the Current Architecture Specification (CAS.md) from accepted
  ADRs and architecture principles. CAS is the agent's primary reference
  for the current architecture state.
allowed-tools:
  coding:
    - read_file
    - write_file
    - list_dir
    - run_git
---

# Generate CAS (Current Architecture Specification)

The Current Architecture Specification (CAS) is an auto-generated document
that consolidates all accepted ADRs and architecture principles into a
single reference. It is the **primary document agents load** to understand
the current state of the architecture.

## What CAS Is

- **A consolidated snapshot** of all accepted architectural decisions.
- **The agent's first stop** — agents load CAS.md before diving into
  individual ADRs.
- **Auto-generated** — never edit CAS.md manually. Always regenerate.
- **Living documentation** — changes whenever an ADR is accepted or
  superseded.

## What CAS Is Not

- Not a replacement for ADRs — ADRs contain the full rationale and
  trade-off analysis. CAS is a summary.
- Not a design document — it describes what *is*, not what *will be*.
- Not manually editable — any manual changes will be overwritten on the
  next regeneration.

## When to Regenerate

Regenerate CAS.md after any of these events:

1. **ADR accepted** — A new ADR reaches `accepted` status.
2. **ADR superseded** — An existing ADR is superseded by a new one.
3. **ADR deprecated** — An existing ADR is marked `deprecated`.
4. **Architecture principles updated** — The `architecture-principles`
   skill content changes.

Do NOT regenerate for:

- ADRs that are still `proposed` — they are not yet architecture.
- Minor documentation fixes that don't affect the architecture.

## How to Regenerate

Run the generation script:

```bash
python scripts/generate_cas.py
```

The script:

1. Reads all ADRs from `docs/adrs/`.
2. Filters to `accepted` and `deprecated` status (skips `proposed`).
3. Reads architecture principles from the `architecture-principles` skill.
4. Consolidates into `docs/CAS.md` with:
   - Active decisions (accepted, not superseded).
   - Deprecated/superseded decisions (for historical reference).
   - Module boundaries and import rules.
   - Technology stack summary.
   - Cross-references to individual ADRs.

## CAS Structure

The generated `docs/CAS.md` follows this structure:

```markdown
# Current Architecture Specification

**Generated**: YYYY-MM-DD HH:MM
**Source**: scripts/generate_cas.py
**Do not edit manually** — regenerate after ADR changes.

## Active Architectural Decisions

### [ADR-001] Title
**Status**: accepted | **Since**: YYYY-MM-DD
**Summary**: One-paragraph summary of the decision.
**Key rules**: Bullet list of enforceable rules from this ADR.
**Enforcement**: How this is enforced (lint, CI, review).

(Repeated for each active ADR)

## Module Boundaries

| Module | Responsibilities | May import from |
|--------|-----------------|-----------------|
| api/ | HTTP routes | services/, domain/ |
| services/ | Business logic | repositories/, domain/ |
| ... | ... | ... |

## Technology Stack

| Component | Technology | ADR |
|-----------|-----------|-----|
| ... | ... | ADR-XXX |

## Deprecated Decisions

(List of superseded/deprecated ADRs for historical context)

## Unresolved

(List of `proposed` ADRs — not active, but visible for awareness)
```

## How Agents Use CAS

Agents in the Druppie pipeline use CAS as follows:

1. **Load CAS first** — Before any task, read `docs/CAS.md`.
2. **Dive into individual ADRs only when needed** — If CAS references
   an ADR that is directly relevant to the current task, read the full
   ADR for rationale and details.
3. **Follow active decisions** — All `accepted` decisions in CAS are
   mandatory. `proposed` decisions are informational only.
4. **Report violations** — If the codebase violates an active CAS
   decision, flag it as a finding.

## Never Edit CAS.md Manually

If CAS.md contains an error or is out of date:

1. Fix the source — update the ADR or architecture principles.
2. Regenerate: `python scripts/generate_cas.py`.
3. Commit the regenerated file.

Direct edits to CAS.md will be silently overwritten on the next
regeneration and will cause confusion.
