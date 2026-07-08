---
name: feature-dev
description: >
  Guides end-to-end feature development: PRD → Research → ADR → Acceptance Specs → Implementation → Test.
  Loads relevant ADRs, platform standards, and architecture principles.
  Used by developer and builder_planner agents.
allowed-tools:
  coding:
    - read_file
    - write_file
    - list_dir
    - run_git
---

# Feature Development Workflow

End-to-end guide for building features following the spec-driven documentation
pipeline: PRD → Research → ADR → Acceptance Specs → Implementation → Verification.

## Pre-conditions

Before writing any code:

1. **Load CAS.md** — Read the Current Architecture Specification at
   `docs/adrs/CAS.md`. This is
   the agent's primary reference for the current state of the architecture.
2. **Read the linked PRD** — The feature request references a PRD in
   `docs/prds/`. Read it fully to understand problem, goals, user journey,
   and constraints.
3. **Load architecture-principles skill** — Invoke the `architecture-principles`
   skill to ground decisions in established principles.
4. **Check for existing ADRs** — Scan `docs/adrs/` for any ADRs related to
   the feature's domain. Load and follow accepted ADRs.

## Phase 1: Research

If the feature covers novel ground — new technology, unfamiliar patterns, or
a domain not covered by existing ADRs — create a research document:

1. Create `docs/research/NNN-short-kebab-title.md` following the research
   template (`docs/research/TEMPLATE.md`).
2. Use the `research-writer` skill for guidance.
3. Include a trade-off table (Option | Pros | Cons | Risk | Effort).
4. Cite sources and provide a clear recommendation.
5. Link the research doc from the PRD.

Skip this phase if the feature is straightforward and existing ADRs already
cover the architectural choices.

## Phase 2: ADR

If the feature requires an architectural decision that is not already covered
by an accepted ADR:

1. Create `docs/adrs/NNN-short-kebab-title.md` using the ADR template.
2. Use the `adr-writer` skill for format and status rules.
3. Status starts as `proposed`. Only the architect agent promotes to `accepted`.
4. The ADR must link back to the PRD and forward to any research doc.
5. After acceptance, trigger CAS regeneration (see `generate-cas` skill).

Skip this phase if no new architectural decision is needed.

## Phase 3: Acceptance Specs

Write acceptance scenarios *before* implementation:

1. Create a `.feature` file in the appropriate test directory.
2. Tag the feature with `@prd:<prd-id>` to link it back to the PRD.
3. Write scenarios covering:
   - Happy path (the user journey from the PRD)
   - Edge cases (boundary conditions, empty states)
   - Error handling (validation failures, permission denials)
4. Each scenario should be concrete and testable — no vague language.

Example:
```gherkin
@prd:PRD-0042
Feature: Session approval workflow
  Scenario: Admin approves a pending session
    Given a session with status "pending_approval"
    And the current user has role "admin"
    When the user approves the session
    Then the session status becomes "approved"
    And an audit log entry is created
```

## Phase 4: Implementation

Follow the layered architecture strictly. The data flow is:
**Repository → Domain Model → Service → API Route**

### Layer rules

| Layer | May import from | Must NOT import from |
|-------|----------------|---------------------|
| `api/` | `services/`, `domain/` | `repositories/`, `db/models/` |
| `services/` | `repositories/`, `domain/` | `api/`, `db/models/` |
| `repositories/` | `db/models/`, `domain/` | `api/`, `services/` |
| `domain/` | Nothing (pure Pydantic) | Any other layer |
| `db/models/` | SQLAlchemy only | Any application layer |

### Implementation order

1. **Domain models** — Define Summary and Detail models in `domain/`.
   Follow the naming convention: `EntitySummary` for lists, `EntityDetail`
   for single items. Export through `domain/__init__.py`.
2. **Database models** — Add SQLAlchemy models in `db/models/`. No JSON/JSONB
   columns — normalize into proper relational tables.
3. **Repository** — Data access layer in `repositories/`. Returns domain models,
   never ORM objects. Uses SQLAlchemy sessions.
4. **Service** — Business logic in `services/`. Orchestrates repositories.
   Validates input, enforces business rules.
5. **API route** — Thin layer in `api/`. Delegates to services. Handles HTTP
   concerns (status codes, request/response models).

### Additional rules

- **No database migrations** — Update SQLAlchemy models directly, reset DB
  with `docker compose --profile reset-db run --rm reset-db`.
- **Config in YAML** — Agent definitions in `agents/definitions/*.yaml`, not
  in the database.
- **No legacy/fallback code** — Clean architecture only.

## Phase 5: Verification

Before considering the feature complete:

1. **Run acceptance specs** — Execute the `.feature` file written in Phase 3.
   All scenarios must pass.
2. **Run existing tests** — `cd druppie && pytest`. No regressions.
3. **Check architecture lint** — Verify import rules are respected. No layer
   violations.
4. **Lint check** — `cd druppie && ruff check .` must be clean.
5. **Format check** — `cd druppie && black --check .` must be clean.

## Commit rules

Every commit for this feature must:

1. Reference the PRD: `feat(scope): description [PRD-XXXX]`
2. Reference the ADR if one was created: `[ADR-NNN]`
3. Use conventional commit format (feat, fix, docs, refactor, test, chore).

Example:
```
feat(sessions): add approval workflow endpoint [PRD-0042] [ADR-0015]
```
