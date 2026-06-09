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

## ADR Template

Create the file as `docs/adrs/NNN-short-kebab-title.md`:

```markdown
# NNN. Short Kebab Title

## Status

proposed | accepted | deprecated | superseded by [ADR-XXX]

## Context

What is the issue that we're seeing that is motivating this decision or change?

## Decision

What is the change that we're proposing and/or doing?

## Consequences

What becomes easier or more difficult to do because of this change?

### Positive

- Benefit 1
- Benefit 2

### Negative

- Trade-off 1
- Trade-off 2

### Risks

- Risk 1 and mitigation

## Related

- PRD: `docs/prds/PRD-XXXX.md` (if applicable)
- Research: `docs/research/YYYY-MM-DD-topic.md` (if applicable)
- Supersedes: ADR-XXX (if applicable)
- Superseded by: ADR-XXX (if applicable)
```

## Naming

- **Sequential numbering**: Find the highest existing ADR number, add 1.
  Example: if `ADR-007` exists, the next is `ADR-008`.
- **Short kebab title**: 3-5 words describing the decision.
  Example: `008-module-boundary-enforcement.md`
- **No dates in the filename** — the sequential number is the identifier.

## Status Rules

| Transition | Who | When |
|-----------|-----|------|
| → `proposed` | Any agent | ADR is written, awaiting review |
| → `accepted` | Architect agent | ADR is reviewed and approved |
| → `deprecated` | Architect agent | Decision is no longer recommended |
| → `superseded by ADR-XXX` | Architect agent | A new ADR replaces this one |

- **Never delete an ADR.** Even deprecated ADRs remain for historical context.
- **Status changes require a commit** that updates only the status field and
  the `superseded by` link if applicable.

## Superseding an Old ADR

When a new ADR replaces an old one:

1. Create the new ADR with status `proposed`.
2. In the new ADR, add `Supersedes: ADR-XXX` in the Related section.
3. After the new ADR is accepted, update the old ADR:
   - Change status to `superseded by [ADR-YYY]`.
   - Do NOT modify the old ADR's content — only the status line.
4. Trigger CAS regeneration (see `generate-cas` skill).

## Linking to Enforcement

ADRs that define enforceable rules (import boundaries, naming conventions,
technology choices) should be linked to their enforcement mechanism:

- **Architecture lint** — If the ADR defines import rules, note which lint
  rule enforces it.
- **CI check** — If the ADR mandates a specific check, reference the CI
  configuration.
- **Code review checklist** — If the ADR defines conventions, note that
  code reviews must verify them.

Add a section in the ADR:

```markdown
## Enforcement

- Architecture lint rule: `layer-import-boundaries`
- CI check: `scripts/check_imports.py`
```

## After Acceptance: Trigger CAS Regeneration

Once an ADR is accepted (or superseded), the Current Architecture
Specification must be updated to reflect the new state:

1. Run `scripts/generate_cas.py` to regenerate `docs/CAS.md`.
2. Verify the CAS reflects the new or superseded ADR.
3. See the `generate-cas` skill for details.
