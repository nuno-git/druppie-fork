---
id: "007"
title: Enforce strict layered architecture in the backend
status: accepted
date: 2026-07-16
deciders:
  - nuno
supersedes: null
superseded_by: null
linked_prd: null
linked_research: null
---

# ADR 007: Enforce strict layered architecture in the backend

## Context

The backend (Python / FastAPI) is the integration point for the API, business
rules, agent runtime, and persistence. Without a forced structure, logic tends to
creep across boundaries: API routes start querying the database directly, services
grow HTTP-aware code, and ORM models leak into API responses. That coupling makes
the code hard to test (you cannot mock at a layer boundary), hard to reason about
(unclear ownership of a rule), and inconsistent in the contract it exposes to the
frontend.

The forces at play:

- Multiple route modules (`chat`, `sessions`, `approvals`, `questions`, `projects`,
  `deployments`, `workspace`, `agents`, `mcps`, `mcp_bridge`) that must stay thin.
- Business rules (workflow orchestration, approval/question handling, revert logic)
  that must be reusable and testable independently of HTTP.
- A PostgreSQL schema accessed through SQLAlchemy ORM models whose shape must not
  leak into API responses.
- A need for one stable API contract (Pydantic domain models) shared between
  backend and frontend.

## Decision

Enforce a strict, unidirectional layered architecture with a single responsibility
per layer:

```
Repository  -->  Domain Model  -->  Service  -->  API Route
(DB access)      (Pydantic)        (logic)       (HTTP)
```

- **API Routes** (`druppie/api/routes/`): thin HTTP layer. They receive requests,
  perform request validation and auth, delegate to services, and return domain
  models. They contain no business logic and no database access.
- **Services** (`druppie/services/`): business logic. They orchestrate repository
  calls, enforce rules, and never touch the database directly or know about HTTP.
- **Repositories** (`druppie/repositories/`): data access. They query SQLAlchemy
  models and return domain models. They are the only layer that talks to the ORM.
- **Domain Models** (`druppie/domain/`): Pydantic models that define the API
  contract. All exports go through the central `druppie/domain/__init__.py`, using
  the Summary/Detail naming convention (e.g. `SessionSummary` for lists,
  `SessionDetail` for single items).

Dependency flow is unidirectional: a route may call a service; a service may call
repositories; a repository may not call a service or a route. No layer may skip
over another (routes must not call repositories directly).

## Consequences

Positive:

- Each layer is independently testable by mocking the layer below it.
- Clear ownership: every rule lives in exactly one layer, making onboarding and
  code review faster.
- A single, stable API contract (domain models) decouples the frontend from the
  database schema.
- Repositories can be swapped or refactored without touching routes or services.

Negative:

- More files and indirection for simple operations (a trivial read still flows
  route -> service -> repository).
- Ongoing discipline is required to prevent drift; nothing today hard-blocks a
  route from importing a repository, so it must be enforced in review.

## Alternatives Considered

- **Fat routes (business logic inside API handlers).** Rejected: logic gets
  duplicated across routes, becomes impossible to unit test without an HTTP
  client, and couples rules to request/response objects.
- **Active Record (ORM models carry persistence and behavior).** Rejected: it
  couples the domain shape to the database, makes the API contract drift with the
  schema, and prevents a clean domain-model layer.
- **Service-less two-layer (route -> repository).** Rejected: business rules end
  up either in routes or in repositories, recreating the coupling this decision
  exists to prevent.
