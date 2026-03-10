---
name: project-coding-standards
description: >
  Druppie project coding standards for Python (FastAPI), React (Vite),
  and MCP servers. Covers code style, naming conventions, import order,
  file naming, and critical project rules.
---

# Project Coding Standards

These are the mandatory coding standards for the Druppie platform codebase.
All generated code MUST comply with these rules.

---

## 1. Python / FastAPI Standards

### Formatting & Linting

| Tool | Setting |
|------|---------|
| **Black** | line-length = 100, target-version = py311 |
| **Ruff** | select = E, F, W, I; line-length = 100; ignore = E501 |

### Naming Conventions

| Element | Convention | Example |
|---------|-----------|---------|
| Functions & methods | `snake_case` | `get_by_id()`, `list_all()` |
| Variables | `snake_case` | `project_id`, `user_roles` |
| Classes | `PascalCase` | `ProjectService`, `SessionRepository` |
| Constants | `UPPER_SNAKE_CASE` | `MAX_RETRIES`, `DEFAULT_LANGUAGE` |
| Modules / files | `snake_case.py` | `project_service.py`, `session_repository.py` |
| Packages / directories | `snake_case` | `db/models/`, `api/routes/` |

### Type Hints

- **Required** on all function signatures (parameters and return types)
- Prefer `X | None` syntax for new code (Python 3.11+); `Optional[X]` is also acceptable
- Use `list[X]` instead of `List[X]` (lowercase generics)
- Use `dict[K, V]` instead of `Dict[K, V]`
- Use `from __future__ import annotations` when forward references are needed

```python
# CORRECT
def get_by_id(self, project_id: UUID) -> Project | None:
    ...

def list_all(self, limit: int = 20, offset: int = 0) -> tuple[list[ProjectSummary], int]:
    ...

# WRONG
def get_by_id(self, project_id):  # Missing type hints
    ...
```

### Docstrings

- **Google-style** docstrings on all public classes and functions
- Keep them concise (1-2 sentences for simple functions)
- Include `Args:` and `Returns:` sections when parameters/return values aren't obvious

```python
# CORRECT
class ProjectRepository(BaseRepository):
    """Database access for projects."""

    def get_by_id(self, project_id: UUID) -> Project | None:
        """Get raw project model."""
        ...

    def list_for_user(
        self,
        user_id: UUID,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[ProjectSummary], int]:
        """List projects for a user.

        Args:
            user_id: Owner's UUID
            limit: Max results per page
            offset: Pagination offset

        Returns:
            Tuple of (project summaries, total count)
        """
        ...
```

### Logging

- Use `structlog.get_logger()` — **never** `logging.getLogger()`
- Logger as module-level constant: `logger = structlog.get_logger()`
- Use structured key-value pairs, not string formatting
- **Exception**: MCP servers (`druppie/mcp-servers/`) run as standalone
  Docker containers without structlog. Use `logging.getLogger()` there.

```python
import structlog

logger = structlog.get_logger()

# CORRECT
logger.info("project_created", project_id=str(project.id), name=project.name)

# WRONG
logger.info(f"Created project {project.id}")  # No structured logging
```

### Error Handling

- No bare `except:` — always specify the exception type
- Use project-specific errors from `druppie/api/errors.py` (e.g., `NotFoundError`, `AuthorizationError`)
- Let framework errors propagate (don't catch and re-raise without adding value)

### Async / Await

- Route handlers: `async def` (FastAPI convention)
- Repository methods: regular `def` (synchronous SQLAlchemy)
- Service methods: regular `def` unless calling async external services

---

## 2. Frontend / React Standards

### Formatting & Linting

| Tool | Setting |
|------|---------|
| **ESLint** | `--max-warnings 0` (zero warnings allowed) |
| **Plugins** | eslint-plugin-react, eslint-plugin-react-hooks |

### Component Style

- **Functional components with hooks only** — no class components
- Export: `export default function ComponentName()` for pages
- Use React Query (`useQuery`, `useMutation`) for all server state
- Use Zustand for client-only state (not Redux, not React Context for global state)
- Use Tailwind CSS for styling — no CSS modules, no styled-components

### Naming Conventions

| Element | Convention | Example |
|---------|-----------|---------|
| Components / Pages | `PascalCase` | `ProjectDetail`, `SessionSidebar` |
| Component files | `PascalCase.jsx` | `ProjectDetail.jsx`, `Toast.jsx` |
| Variables & functions | `camelCase` | `projectId`, `handleSubmit` |
| Service files | `camelCase.js` | `api.js`, `keycloak.js` |
| Directories | `kebab-case` or `camelCase` | `src/components/chat/`, `src/services/` |
| Query keys | `camelCase` arrays | `['projects', projectId]` |

### Import Order

1. React & third-party libraries
2. Components
3. Services / utilities
4. Styles / assets

```jsx
// CORRECT
import React from 'react'
import { useQuery } from '@tanstack/react-query'

import PageHeader from '../components/shared/PageHeader'
import ProjectCard from '../components/ProjectCard'

import { getProjects } from '../services/api'
```

### Icons

- Use **Lucide React** for icons — no other icon libraries

---

## 3. Critical Project Rules

These rules are **absolute** and override any other convention:

1. **NO JSON/JSONB columns** for structured domain data — normalize into proper relational tables with foreign keys. **Exception**: JSON columns are acceptable for dynamic external data with no fixed schema (e.g., LLM message arrays, tool call arguments, agent state snapshots, user-provided choices).
2. **NO database migrations** (no Alembic) — update SQLAlchemy models directly, reset DB with `docker compose --profile reset-db run --rm reset-db`
3. **NO legacy/fallback code** — clean architecture only, no backwards compatibility hacks
4. **Config in YAML files** — agent definitions in `agents/definitions/*.yaml`, not in database
5. **Always commit and push** — keep changes in git

---

## 4. Import Conventions

### Python Backend

```python
# Domain models — ALWAYS import from druppie/domain/__init__.py
from druppie.domain import ProjectSummary, ProjectDetail

# Within a package — use relative imports
from .base import BaseRepository        # In repositories/
from ..domain import SessionSummary     # Up one level
from ..db.models import Project         # Cross-package

# Standard library first, then third-party, then local
import os
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from druppie.api.deps import get_current_user
from druppie.domain import ProjectDetail
```

### Frontend

```javascript
// API client — import from services/api.js
import { getProjects, getProject } from '../services/api'

// Shared components
import PageHeader from '../components/shared/PageHeader'
```

---

## 5. File Organization

### Python Backend File Placement

| Type | Location | Naming |
|------|----------|--------|
| Domain models | `druppie/domain/<entity>.py` | Export in `__init__.py` |
| DB/ORM models | `druppie/db/models/<entity>.py` | Export in `__init__.py` |
| Repositories | `druppie/repositories/<entity>_repository.py` | Export in `__init__.py` |
| Services | `druppie/services/<entity>_service.py` | Export in `__init__.py` |
| API routes | `druppie/api/routes/<entities>.py` | Plural noun |
| Dependencies | `druppie/api/deps.py` | Single file |
| Agent definitions | `druppie/agents/definitions/<agent_id>.yaml` | Agent ID |
| Skills | `druppie/skills/<skill-name>/SKILL.md` | kebab-case directory |

### Frontend File Placement

| Type | Location | Naming |
|------|----------|--------|
| Pages | `frontend/src/pages/` | `PascalCase.jsx` |
| Shared components | `frontend/src/components/shared/` | `PascalCase.jsx` |
| Feature components | `frontend/src/components/<feature>/` | `PascalCase.jsx` |
| API client | `frontend/src/services/api.js` | Single file |
| Auth service | `frontend/src/services/keycloak.js` | Single file |
