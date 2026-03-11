---
name: standards-validation
description: >
  Validation checklist for reviewing generated code against Druppie project
  coding standards and architecture patterns. Used by the Reviewer agent to
  ensure compliance.
allowed-tools:
  coding:
    - read_file
    - list_dir
---

# Standards Validation Checklist

Use this checklist to validate generated code against Druppie's project
coding standards and architecture patterns. Check each item and report
findings in the structured output format below.

**IMPORTANT: Druppie vs. User Projects**

This checklist applies to **Druppie's own codebase** (Python/FastAPI backend,
React frontend, MCP servers). When reviewing code for **user projects**
(projects built by agents for end users), apply only the general code quality
and security checks (sections 2.Code Style and 3.Critical Violations where
universally applicable). Do NOT enforce Druppie-specific patterns
(Summary/Detail, BaseRepository, deps.py wiring, etc.) on user projects —
instead validate against the technology stack and conventions defined in that
project's own specification or builder_plan.md.

---

## 1. Architecture Compliance

### Layer Separation

- [ ] **Routes are thin** — no business logic in route handlers, only:
  parse request → call service → return response
- [ ] **Business logic in services** — authorization checks, validation,
  orchestration all happen in the service layer
- [ ] **Database access in repositories only** — no `self.db.query()` in
  services or routes
- [ ] **No circular dependencies** — Route → Service → Repository (never
  reverse)

### Domain Model Pattern

- [ ] **Summary/Detail pattern used** — every entity has `<Entity>Summary`
  (lightweight, for lists) and `<Entity>Detail` (inherits Summary, for
  single-item views)
- [ ] **Detail inherits from Summary** — `class <Entity>Detail(<Entity>Summary)`
- [ ] **All domain models exported** through `druppie/domain/__init__.py`
- [ ] **Pydantic BaseModel** — all domain models inherit from `BaseModel`

### Repository Pattern

- [ ] **Extends BaseRepository** — `class XxxRepository(BaseRepository)`
- [ ] **Returns domain models** — public query methods (list, get_detail)
  return Pydantic domain models, not ORM models
- [ ] **Has `_to_summary` / `_to_detail` helpers** — private methods that
  convert ORM model → domain model
- [ ] **Raw ORM access** — `get_by_id` returns ORM model (for internal use
  by other repository methods and services)

### Dependency Injection

- [ ] **Wired through deps.py** — `get_<entity>_repository()` and
  `get_<entity>_service()` functions exist in `druppie/api/deps.py`
- [ ] **Uses `Depends()`** — routes inject services via
  `service: XxxService = Depends(get_xxx_service)`
- [ ] **Constructor injection** — services receive repositories via
  constructor, not via global imports

### Frontend Architecture

- [ ] **Page in `src/pages/`** — page components in the correct directory
- [ ] **Components in `src/components/`** — reusable components properly
  organized
- [ ] **API calls via `src/services/api.js`** — not inline fetch calls
- [ ] **React Query for server state** — uses `useQuery` / `useMutation`
  from `@tanstack/react-query`

---

## 2. Code Style Compliance

### Python

- [ ] **Black-compatible formatting** — 100 character line length
- [ ] **Type hints on all public functions** — parameters and return types
- [ ] **Google-style docstrings** — on all public classes and functions
- [ ] **structlog logging** — `logger = structlog.get_logger()` at module
  level, structured key-value logging (exception: MCP servers use
  `logging.getLogger()` since they run as standalone containers)
- [ ] **No bare `except:`** — always specify exception type
- [ ] **Correct import order** — stdlib → third-party → local (Ruff I rule)
- [ ] **Ruff linting clean** — rules E, F, W, I selected; `ruff check .`
  with zero errors
- [ ] **`X | None` preferred** — new code uses union syntax and lowercase
  generics (`list[X]`, `dict[K, V]`)
- [ ] **Async conventions** — route handlers use `async def`; repositories
  use `def`; services use `def` unless calling async externals
- [ ] **Error handling** — uses project errors from `druppie/api/errors.py`
  (`NotFoundError`, `AuthorizationError`); lets framework errors propagate

### Frontend

- [ ] **Functional components only** — no class components
- [ ] **Tailwind CSS** — styling via utility classes, not CSS modules
- [ ] **ESLint clean** — no warnings (enforced with `--max-warnings 0`)
- [ ] **React Query for server state** — `useQuery` / `useMutation` from
  `@tanstack/react-query`; Zustand for client-only state
- [ ] **Lucide React icons** — no other icon libraries
- [ ] **Import order** — React/third-party → components → services → styles

### Naming Conventions

- [ ] **Python functions/variables** — `snake_case`
- [ ] **Python classes** — `PascalCase`
- [ ] **Python files** — `snake_case.py`
- [ ] **React components** — `PascalCase` names, `PascalCase.jsx` files
- [ ] **JavaScript variables/functions** — `camelCase`
- [ ] **API route prefixes** — plural nouns (`/projects`, `/sessions`)
- [ ] **Python constants** — `UPPER_SNAKE_CASE`
- [ ] **Python packages/directories** — `snake_case`
- [ ] **Component files** — `PascalCase.jsx`
- [ ] **Service files** — `camelCase.js`

### File Organization

- [ ] **Domain models** in `druppie/domain/<entity>.py` — exported in `__init__.py`
- [ ] **DB models** in `druppie/db/models/<entity>.py` — exported in `__init__.py`
- [ ] **Repositories** in `druppie/repositories/<entity>_repository.py`
- [ ] **Services** in `druppie/services/<entity>_service.py`
- [ ] **API routes** in `druppie/api/routes/<entities>.py` — plural noun
- [ ] **Frontend pages** in `frontend/src/pages/PascalCase.jsx`
- [ ] **Skills** in `druppie/skills/<skill-name>/SKILL.md` — kebab-case dir

---

## 3. Critical Violations (Must Fail Review)

These issues automatically result in a **FAIL** verdict:

| Violation | Why It Fails |
|-----------|-------------|
| **JSON/JSONB column** for structured domain data (settings, config, relationships) | Normalize into relational tables. Exception: dynamic external data (LLM messages, tool args, agent state) may use JSON |
| **Database migration file** (Alembic, etc.) | Project rule: update models directly, reset DB |
| **Legacy/fallback code** (backwards compat hacks, unused `_vars`) | Project rule: clean architecture only |
| **Business logic in route handlers** (DB queries, complex conditionals) | Architecture: routes must be thin |
| **Direct DB access in services** (`self.db.query(...)` in a service) | Architecture: only repositories touch DB |
| **Missing `__init__.py` exports** for new domain models | Convention: central export required |
| **Class components** in React | Convention: functional components only |

---

## 4. Template Usage Verification

When the Builder created new components, verify the correct templates were
followed:

- [ ] **Domain model** follows Summary/Detail pattern with Pydantic
- [ ] **DB model** extends `Base`, uses `UUID(as_uuid=True)` for primary key,
  has `created_at` / `updated_at` timestamps
- [ ] **Repository** extends `BaseRepository`, has conversion helpers
- [ ] **Service** receives repository via constructor injection
- [ ] **Route** uses `Depends()` for service injection, returns domain models
- [ ] **deps.py** has both repository and service factory functions
- [ ] **Frontend page** uses React Query, Tailwind CSS

---

## 5. Output Format

Structure REVIEW.md as follows:

```markdown
# Code Review: [Component/Feature Name]

## Verdict: PASS / FAIL / NEEDS WORK

## Architecture Compliance: PASS / FAIL

### Findings
- [x] Layer separation: [status]
- [x] Summary/Detail pattern: [status]
- [x] Repository pattern: [status]
- [x] Dependency injection: [status]
- [ ] [Any failing check with details]

## Standards Compliance: PASS / FAIL

### Findings
- [x] Type hints: [status]
- [x] Naming conventions: [status]
- [ ] [Any failing check with details]

## Critical Violations
- [List any critical violations, or "None found"]

## Issues by Severity

### Critical (must fix)
- [Issue description, file, line]

### Major (should fix)
- [Issue description, file, line]

### Minor (suggestion)
- [Issue description, file, line]

## Positive Observations
- [What was done well]

## Recommendations
- [Actionable next steps]
```

---

## Review Process

1. **Invoke skills** — load `fullstack-architecture`,
   `project-coding-standards`, and this `standards-validation` skill
2. **Read the code** — use `coding_read_file` and `coding_list_dir` to
   inspect all generated files
3. **Determine project type** — check if this is Druppie's own codebase
   or a user project (see "Druppie vs. User Projects" note above)
4. **Apply checklists** — go through each section above (skip
   architecture/template sections for user projects)
5. **Check for critical violations** — any violation in section 3 means
   automatic FAIL
6. **Write REVIEW.md** — using the output format above
7. **Commit and push** — save REVIEW.md to git
8. **Call done()** — with summary including verdict and key findings
