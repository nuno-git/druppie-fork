---
id: "001"
title: Enforce strict layered architecture
status: accepted
date: 2026-06-09
deciders:
  - architect
  - developer
superseded_by: null
enforcement:
  lint_rules:
    - import-linter
  ci_checks:
    - import-linter-contracts
linked_prd: null
linked_research: null
---

## Context

The Druppie backend is a FastAPI application with multiple concerns: HTTP routing, business logic, data persistence, and domain contracts. Without strict layer boundaries, code tends to leak responsibilities — API routes directly query the database, services import HTTP-specific types, or repositories return raw ORM objects to callers. This coupling makes the system harder to test, harder to evolve, and harder to reason about.

Early in the project we experienced these exact problems: route handlers contained business logic, database queries were scattered across modules, and there was no consistent data contract between layers. Refactoring became risky because changes in one area had unpredictable ripple effects.

## Decision

We enforce a strict unidirectional layered architecture with four layers:

```
API Route  -->  Service  -->  Repository  -->  Domain Model
(HTTP)         (logic)       (DB access)      (Pydantic)
```

**Layer responsibilities:**

- **API Routes** (`druppie/api/routes/`): Thin HTTP layer. Receives requests, validates parameters via FastAPI dependencies, delegates to a single service method, and returns domain models. No business logic, no direct database access.
- **Services** (`druppie/services/`): Business logic. Orchestrates one or more repository calls, enforces business rules, manages transactions. Services never import FastAPI HTTP types (`Request`, `Response`, etc.).
- **Repositories** (`druppie/repositories/`): Data access. Queries SQLAlchemy ORM models and returns Pydantic domain models. Repositories never accept or return HTTP types.
- **Domain Models** (`druppie/domain/`): Pydantic models defining the API contract. All domain model exports go through `druppie/domain/__init__.py`.

**Additional rules:**

- Domain models use a **Summary/Detail naming pattern**: `SessionSummary` for lists, `SessionDetail` for single items.
- Dependency flow is unidirectional: outer layers depend on inner layers, never the reverse.
- Dependencies between layers are wired via FastAPI's dependency injection in `druppie/api/deps.py`.

## Consequences

**Positive:**

- Each layer can be tested independently with mocked dependencies.
- Business logic is isolated in services, making it easy to find and modify.
- Domain models provide a stable contract that shields the API from database schema changes.
- New developers can understand the codebase structure by following the layer convention.

**Negative:**

- Adding a simple feature requires touching four files (route, service, repository, domain model).
- The strict separation can feel verbose for trivial CRUD operations.
- Requires discipline and CI enforcement to prevent layer violations.

## Compliance

Compliance is verified through:

1. **import-linter**: Configured with contracts that forbid cross-layer imports (e.g., routes must not import from `druppie/db/`, services must not import from `druppie/api/`).
2. **Code review**: Reviewers check that route handlers remain thin and delegate to services.
3. **Domain model exports**: All Pydantic models used in API responses must be exported from `druppie/domain/__init__.py`.

## Enforcement

When a layer violation is detected:

1. **CI failure**: The `import-linter-contracts` CI job fails, blocking the PR.
2. **Remediation**: The developer must move the misplaced logic to the correct layer.
3. **Exception process**: If a legitimate cross-layer need arises, it must be discussed with the architect and documented as an exception in the ADR system.
