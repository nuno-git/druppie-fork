---
name: bug-fix
description: >
  Guides bug fixing with minimal, targeted changes. Reproduce with acceptance specs,
  trace through layers, fix minimally, and guard against regressions.
  Used by developer agents.
allowed-tools:
  coding:
    - read_file
    - write_file
    - list_dir
    - run_git
---

# Bug Fix Workflow

Targeted bug fixes that address the root cause without introducing
collateral changes. The goal is the smallest possible change that fixes
the bug.

## Step 1: Reproduce the Bug

Before touching any code, reproduce the failure:

1. **Find the failing acceptance spec.** If one already exists, run it and
   confirm it fails.
2. **Write a new acceptance spec if none exists.** This is mandatory — a bug
   without a failing test is a bug that will come back.
3. Tag the scenario: `@bug:<short-description>` and `@prd:<prd-id>` if
   applicable.

Example:
```gherkin
@bug:session-status-race
Scenario: Concurrent approval and rejection of same session
  Given a session with status "pending_approval"
  When admin approves and developer rejects simultaneously
  Then the session reaches a consistent state
  And no duplicate audit entries exist
```

## Step 2: Root Cause Analysis

Trace the failure through the layers to find the root cause:

1. **API layer** — Is the route receiving the correct input? Check request
   parsing, validation, and error responses.
2. **Service layer** — Is the business logic correct? Check state
   transitions, error handling, and concurrent access patterns.
3. **Repository layer** — Is the data access correct? Check query logic,
   filtering, and transaction boundaries.
4. **Database layer** — Is the data model correct? Check constraints,
   indexes, and relationship definitions.

Ask: *Where does the actual behavior diverge from the expected behavior?*
That's the root cause layer. The fix should be in that layer.

## Step 3: Fix Minimally

- **Fix only the root cause.** Do not refactor surrounding code, improve
  naming, or "clean up while you're here." Those are separate commits.
- **Fix at the correct layer.** If the bug is in the service, fix the
  service — don't work around it in the API or repository.
- **One fix, one commit.** If multiple related bugs are found, fix them
  in separate commits.

### Common anti-patterns to avoid

- Wrapping a bug in a try/catch instead of fixing the root cause.
- Adding a special-case `if` in a higher layer to hide a lower-layer bug.
- Refactoring the code "because it was hard to understand" while fixing.
- Changing the test to make it pass instead of fixing the code.

## Step 4: Verify the Fix

1. **Run the failing acceptance spec** — Must now pass.
2. **Run related tests** — Run tests for the affected module/service.
3. **Run full test suite** — `cd druppie && pytest`. Zero new failures.
4. **Lint check** — `cd druppie && ruff check .` clean.

## Step 5: Regression Guard

Ensure the fix doesn't break other scenarios:

1. Scan the acceptance specs for any that cover the same component or
   workflow. Run them all.
2. If the fix changes shared behavior (e.g., a domain model or base
   service), run the *full* test suite.
3. Check that the fix doesn't introduce a performance regression
   (e.g., adding N+1 queries).

## Commit

```
fix(scope): description of the bug and fix [BUG-XXXX]

The <component> was <what went wrong> because <root cause>.
Fixed by <what changed>.

Specs: @bug:<short-description> now passes.
```

Example:
```
fix(sessions): prevent race condition on concurrent status changes

SessionService.transition_status() did not acquire a row lock before
checking current status, allowing two concurrent transitions to both
succeed. Fixed by adding SELECT FOR UPDATE in the repository query.

Specs: @bug:session-status-race now passes.
```
