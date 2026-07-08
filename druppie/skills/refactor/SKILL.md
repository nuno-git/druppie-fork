---
name: refactor
description: >
  Guides structural refactoring that preserves behavior. Enforces import
  rules, module boundaries, and architecture lint compliance throughout.
  Used by developer agents.
allowed-tools:
  coding:
    - read_file
    - write_file
    - list_dir
    - run_git
---

# Refactoring Workflow

Structural code changes that improve organization without altering behavior.
Refactoring is *only* about structure — if behavior changes, that's a feature
or a bug fix, not a refactor.

## Pre-conditions

1. **Load ADRs** — Read all ADRs that define module boundaries and import
   rules from `docs/adrs/`. These are the contract you must respect.
2. **Load CAS.md** — Read the Current Architecture Specification at
   `docs/adrs/CAS.md` for the
   current state of the architecture.
3. **Identify scope** — Clearly state what is being refactored and why
   (e.g., "Extract session logic from monolithic service into dedicated
   module per ADR-0012").

## Rules

### Behavior preservation

- **No behavior changes.** The refactored code must produce the same outputs
  for the same inputs. If you find yourself fixing a bug during a refactor,
  stop — fix the bug separately, then resume the refactor.
- **No new features.** If you spot an opportunity for improvement that goes
  beyond structure, note it as a TODO but do not implement it.

### Import rules are sacred

The layered architecture import rules are non-negotiable:

| Layer | May import from | Must NOT import from |
|-------|----------------|---------------------|
| `api/` | `services/`, `domain/` | `repositories/`, `db/models/` |
| `services/` | `repositories/`, `domain/` | `api/`, `db/models/` |
| `repositories/` | `db/models/`, `domain/` | `api/`, `services/` |
| `domain/` | Nothing (pure Pydantic) | Any other layer |
| `db/models/` | SQLAlchemy only | Any application layer |

If the refactored code violates any of these rules, the refactor is wrong.

### Spec suite must stay green

- Run the full spec suite before starting. All must pass.
- After each structural change, re-run affected tests.
- At the end of the refactor, the full suite must still pass — zero
  new failures.

## Process

### Step 1: Baseline

1. Run architecture lint: record current violations (if any).
2. Run full test suite: confirm all pass.
3. Note the commit hash for rollback if needed.

### Step 2: Refactor in small steps

Make one structural change at a time:

1. **Move** a function/class to its correct layer.
2. **Run tests** — if they fail, the move broke something. Fix the move,
   don't change the test.
3. **Check import rules** — verify no new layer violations.
4. **Commit** with message: `refactor(scope): what moved where`

Repeat until the structural goal is achieved.

### Step 3: Verify

1. Run full test suite — all must pass.
2. Run architecture lint — violations must be ≤ baseline (ideally fewer).
3. Run `ruff check .` and `black --check .` — clean.

### Step 4: Document

In the final commit message, document:

- What changed and why (reference the motivating ADR).
- Before/after structure if non-trivial.
- Any remaining violations with a justification.

Example:
```
refactor(sessions): extract approval logic to dedicated service [ADR-0012]

Moved approval workflow logic from SessionService to ApprovalService
to align with module boundaries defined in ADR-0012. Spec suite green.
Architecture lint: 3 violations → 1 violation (pre-existing, tracked in
BACKLOG-0045).
```
