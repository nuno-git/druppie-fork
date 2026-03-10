---
name: fullstack-architecture
description: >
  Druppie fullstack architecture patterns and code templates for Python
  backend (FastAPI clean architecture) and React frontend. Includes
  templates for domain models, repositories, services, API routes,
  dependency injection, DB models, and frontend components.
---

# Fullstack Architecture Patterns & Templates

This skill defines the Druppie project's architecture patterns and provides
code templates for generating new components. **All new components MUST follow
these patterns.**

---

## Architecture Overview

### Data Flow (Unidirectional)

```
Database (PostgreSQL)
    |
DB Model (SQLAlchemy ORM)
    |
Repository (data access, ORM → Domain conversion)
    |
Domain Model (Pydantic — the API contract)
    |
Service (business logic, authorization)
    |
API Route (thin HTTP layer, delegates to service)
    |
Frontend (React, consumes API)
```

### Layer Responsibilities

| Layer | Responsibility | What it does NOT do |
|-------|---------------|---------------------|
| **DB Model** | Define database schema as SQLAlchemy ORM classes | No business logic, no validation |
| **Repository** | Query database, convert ORM models → Domain models | No business rules, no HTTP concerns |
| **Domain Model** | Define the API contract as Pydantic models | No database access, no business logic |
| **Service** | Business logic, authorization, orchestration | No direct DB access, no HTTP concerns |
| **API Route** | HTTP endpoint, parse request, return response | No business logic, no DB access |

### Key Directory Structure

```
druppie/
├── domain/             # Pydantic domain models (Summary/Detail)
│   ├── __init__.py     # Central export point for ALL domain models
│   ├── project.py
│   ├── session.py
│   └── common.py       # Shared types (TokenUsage, enums)
├── db/models/          # SQLAlchemy ORM models
│   ├── __init__.py
│   ├── base.py         # Base class with utcnow helper
│   └── project.py
├── repositories/       # Data access layer
│   ├── __init__.py
│   ├── base.py         # BaseRepository (db session holder)
│   └── project_repository.py
├── services/           # Business logic layer
│   ├── __init__.py
│   └── project_service.py
├── api/
│   ├── deps.py         # Dependency injection wiring
│   └── routes/         # HTTP endpoints
│       └── projects.py
└── mcp-servers/        # MCP microservices
    └── coding/
        ├── server.py   # FastMCP endpoints
        └── module.py   # Business logic
```

---

## Pattern 1: Summary / Detail Domain Models

Every entity uses a two-tier domain model:

- **`<Entity>Summary`** — lightweight, used in lists and embedding
- **`<Entity>Detail`** — inherits from Summary, adds full data

**All domain models MUST be exported through `druppie/domain/__init__.py`.**

### Why This Pattern

- Lists only load what's needed (fast queries, small payloads)
- Detail inherits Summary — no field duplication
- Single import source (`from druppie.domain import ...`)

### Examples in Codebase

| Entity | Summary | Detail |
|--------|---------|--------|
| Project | `ProjectSummary` (id, name, description, repo_url, created_at) | `ProjectDetail` (+owner_id, repo_name, token_usage, sessions) |
| Session | `SessionSummary` (id, title, status, project_id, token_usage, created_at) | `SessionDetail` (+user_id, intent, timeline) |
| AgentRun | `AgentRunSummary` (id, agent_id, status, started_at) | `AgentRunDetail` (+tool_calls, llm_calls, summary) |

---

## Pattern 2: Repository (ORM → Domain Conversion)

Repositories are the ONLY layer that touches the database.

Key rules:
- Extend `BaseRepository` (gets `self.db` session)
- Return **Domain models** (not ORM models) from public query methods
- Use private `_to_summary()` and `_to_detail()` helpers for conversion
- Raw ORM access methods (e.g., `get_by_id`) return ORM model for internal use

---

## Pattern 3: Dependency Injection via deps.py

All wiring lives in `druppie/api/deps.py`:

```
Route → Depends(get_xxx_service)
           → Depends(get_xxx_repository)
                → Depends(get_db)
```

Each entity adds two functions to deps.py:
1. `get_<entity>_repository(db)` → returns `<Entity>Repository(db)`
2. `get_<entity>_service(repo)` → returns `<Entity>Service(repo)`

---

## Pattern 4: MCP Server (server + module)

Each MCP server has two files:
- `server.py` — FastMCP tool definitions (HTTP transport layer)
- `module.py` — Business logic class (testable, no HTTP concerns)

---

## Code Templates

> **Placeholder convention:** Replace `<Entity>` with PascalCase entity name
> (e.g., `Sensor`), `<entity>` with snake_case (e.g., `sensor`),
> and `<entities>` with snake_case plural (e.g., `sensors`).

---

### Template: Domain Model

File: `druppie/domain/<entity>.py`

```python
"""<Entity> domain models."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class <Entity>Summary(BaseModel):
    """Lightweight <entity> for lists and embedding."""

    id: UUID
    name: str
    created_at: datetime


class <Entity>Detail(<Entity>Summary):
    """Full <entity> with additional data."""

    description: str | None = None
    owner_id: UUID
    # Add detail-specific fields here
```

After creating, add to `druppie/domain/__init__.py`:
```python
from .<entity> import <Entity>Summary, <Entity>Detail
```

---

### Template: DB Model (SQLAlchemy)

File: `druppie/db/models/<entity>.py`

```python
"""<Entity> database model."""

from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID

from .base import Base, utcnow


class <Entity>(Base):
    """<Short description>."""

    __tablename__ = "<entities>"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    owner_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    # Add columns here — NO JSON/JSONB for structured domain data!
    # Exception: dynamic external data (LLM messages, tool args) may use JSON.
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
```

After creating, add to `druppie/db/models/__init__.py`:
```python
from .<entity> import <Entity>
```

---

### Template: Repository

File: `druppie/repositories/<entity>_repository.py`

```python
"""<Entity> repository for database access."""

from uuid import UUID

from .base import BaseRepository
from ..domain import <Entity>Summary, <Entity>Detail
from ..db.models import <Entity>


class <Entity>Repository(BaseRepository):
    """Database access for <entities>."""

    def get_by_id(self, <entity>_id: UUID) -> <Entity> | None:
        """Get raw <entity> ORM model."""
        return self.db.query(<Entity>).filter_by(id=<entity>_id).first()

    def list_all(
        self,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[<Entity>Summary], int]:
        """List all <entities> with pagination (admin use)."""
        query = self.db.query(<Entity>)
        total = query.count()
        items = (
            query.order_by(<Entity>.created_at.desc())
            .limit(limit)
            .offset(offset)
            .all()
        )
        return [self._to_summary(item) for item in items], total

    def list_for_user(
        self,
        user_id: UUID,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[<Entity>Summary], int]:
        """List <entities> owned by a specific user."""
        query = self.db.query(<Entity>).filter_by(owner_id=user_id)
        total = query.count()
        items = (
            query.order_by(<Entity>.created_at.desc())
            .limit(limit)
            .offset(offset)
            .all()
        )
        return [self._to_summary(item) for item in items], total

    def get_detail(self, <entity>_id: UUID) -> <Entity>Detail | None:
        """Get full <entity> detail."""
        item = self.get_by_id(<entity>_id)
        if not item:
            return None
        return self._to_detail(item)

    def create(self, name: str, owner_id: UUID, **kwargs) -> <Entity>:
        """Create a new <entity>."""
        item = <Entity>(name=name, owner_id=owner_id, **kwargs)
        self.db.add(item)
        self.db.flush()
        return item

    def _to_summary(self, item: <Entity>) -> <Entity>Summary:
        """Convert ORM model to summary domain object."""
        return <Entity>Summary(
            id=item.id,
            name=item.name,
            created_at=item.created_at,
        )

    def _to_detail(self, item: <Entity>) -> <Entity>Detail:
        """Convert ORM model to detail domain object."""
        return <Entity>Detail(
            id=item.id,
            name=item.name,
            created_at=item.created_at,
            description=item.description,
            owner_id=item.owner_id,
        )
```

After creating, add to `druppie/repositories/__init__.py`:
```python
from .<entity>_repository import <Entity>Repository
```

---

### Template: Service

File: `druppie/services/<entity>_service.py`

```python
"""<Entity> service for business logic."""

from uuid import UUID

import structlog

from ..repositories import <Entity>Repository
from ..domain import <Entity>Detail, <Entity>Summary
from ..api.errors import AuthorizationError, NotFoundError

logger = structlog.get_logger()


class <Entity>Service:
    """Business logic for <entities>."""

    def __init__(self, <entity>_repo: <Entity>Repository):
        self.<entity>_repo = <entity>_repo

    def list_all(
        self,
        user_id: UUID,
        user_roles: list[str],
        page: int = 1,
        limit: int = 20,
    ) -> tuple[list[<Entity>Summary], int]:
        """List <entities> with pagination and access control."""
        offset = (page - 1) * limit
        if "admin" in user_roles:
            return self.<entity>_repo.list_all(limit, offset)
        return self.<entity>_repo.list_for_user(user_id, limit, offset)

    def get_detail(self, <entity>_id: UUID, user_id: UUID, user_roles: list[str]) -> <Entity>Detail:
        """Get <entity> detail with access check.

        Raises:
            NotFoundError: If <entity> not found
            AuthorizationError: If user lacks access
        """
        item = self.<entity>_repo.get_by_id(<entity>_id)
        if not item:
            raise NotFoundError("<entity>", str(<entity>_id))

        is_owner = item.owner_id == user_id
        is_admin = "admin" in user_roles
        if not is_owner and not is_admin:
            raise AuthorizationError("Only owner or admin can view this <entity>")

        return self.<entity>_repo.get_detail(<entity>_id)
```

After creating, add to `druppie/services/__init__.py`:
```python
from .<entity>_service import <Entity>Service
```

---

### Template: API Route

File: `druppie/api/routes/<entities>.py`

```python
"""<Entity> API routes."""

from uuid import UUID

from fastapi import APIRouter, Depends

from druppie.api.deps import get_current_user, get_user_roles, get_<entity>_service
from druppie.domain import <Entity>Summary, <Entity>Detail
from druppie.services import <Entity>Service

router = APIRouter(prefix="/<entities>", tags=["<entities>"])


@router.get("", response_model=list[<Entity>Summary])
async def list_<entities>(
    page: int = 1,
    limit: int = 20,
    service: <Entity>Service = Depends(get_<entity>_service),
    user: dict = Depends(get_current_user),
) -> list[<Entity>Summary]:
    """List all <entities>."""
    user_id = UUID(user["sub"])
    user_roles = get_user_roles(user)
    items, _ = service.list_all(user_id, user_roles, page=page, limit=limit)
    return items


@router.get("/{<entity>_id}", response_model=<Entity>Detail)
async def get_<entity>(
    <entity>_id: UUID,
    service: <Entity>Service = Depends(get_<entity>_service),
    user: dict = Depends(get_current_user),
) -> <Entity>Detail:
    """Get <entity> detail."""
    user_id = UUID(user["sub"])
    user_roles = get_user_roles(user)
    return service.get_detail(<entity>_id, user_id, user_roles)
```

After creating, register the router in `druppie/api/main.py`:
```python
from druppie.api.routes.<entities> import router as <entities>_router
app.include_router(<entities>_router, prefix="/api")
```

---

### Template: Dependency Injection Entry

Add to `druppie/api/deps.py`:

```python
# In the imports section:
from druppie.repositories import <Entity>Repository
from druppie.services import <Entity>Service

# In the REPOSITORY DEPENDENCIES section:
def get_<entity>_repository(db: Session = Depends(get_db)) -> <Entity>Repository:
    """Get <Entity>Repository with DB session injected."""
    return <Entity>Repository(db)

# In the SERVICE DEPENDENCIES section:
def get_<entity>_service(
    <entity>_repo: <Entity>Repository = Depends(get_<entity>_repository),
) -> <Entity>Service:
    """Get <Entity>Service with repositories injected."""
    return <Entity>Service(<entity>_repo)
```

---

### Template: Frontend Page

File: `frontend/src/pages/<EntityName>.jsx`

```jsx
/**
 * <EntityName> Page
 */

import { useQuery } from '@tanstack/react-query'

import PageHeader from '../components/shared/PageHeader'
import { get<Entities> } from '../services/api'

export default function <EntityName>Page() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['<entities>'],
    queryFn: get<Entities>,
  })

  if (isLoading) return <div className="p-6">Loading...</div>
  if (error) return <div className="p-6 text-red-500">Error: {error.message}</div>

  return (
    <div className="space-y-6 p-6">
      <PageHeader title="<Entity Name>" />
      <div className="grid gap-4">
        {data?.map(item => (
          <div key={item.id} className="rounded-lg border p-4">
            <h3 className="font-medium">{item.name}</h3>
          </div>
        ))}
      </div>
    </div>
  )
}
```

---

### Template: Frontend API Service Functions

Add to `frontend/src/services/api.js`:

```javascript
// <Entity> API
export const get<Entities> = (page = 1, limit = 20) =>
  request(`/api/<entities>?page=${page}&limit=${limit}`)

export const get<Entity> = (id) =>
  request(`/api/<entities>/${id}`)

export const create<Entity> = (data) =>
  request('/api/<entities>', {
    method: 'POST',
    body: JSON.stringify(data),
  })
```

Note: The `request()` function does not support a `params` option —
build query parameters directly into the URL string.

---

### Template: MCP Server

File: `druppie/mcp-servers/<name>/server.py`

```python
"""<Name> MCP Server.

Provides <description> via MCP tools over HTTP.
"""

import logging
import os

from fastmcp import FastMCP

from module import <Name>Module

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("<name>-mcp")

mcp = FastMCP("<Name> MCP Server")
module = <Name>Module()


@mcp.tool()
def <tool_name>(<params>) -> dict:
    """<Tool description>."""
    return module.<method_name>(<args>)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 9003))
    mcp.run(transport="streamable-http", host="0.0.0.0", port=port)
```

File: `druppie/mcp-servers/<name>/module.py`

```python
"""<Name> module — business logic for the <Name> MCP server."""

import logging

logger = logging.getLogger("<name>-module")


class <Name>Module:
    """Business logic for <name> operations."""

    def <method_name>(self, <params>) -> dict:
        """<Description>."""
        # Implementation here
        return {"success": True, "result": ...}
```

---

## Checklist: Adding a New Entity

When the Builder creates a new entity (e.g., "Sensor"), it should create
files in this order:

1. **Domain model** — `druppie/domain/sensor.py` (SensorSummary, SensorDetail)
2. **Export** — add to `druppie/domain/__init__.py`
3. **DB model** — `druppie/db/models/sensor.py`
4. **Export** — add to `druppie/db/models/__init__.py`
5. **Repository** — `druppie/repositories/sensor_repository.py`
6. **Export** — add to `druppie/repositories/__init__.py`
7. **Service** — `druppie/services/sensor_service.py`
8. **Export** — add to `druppie/services/__init__.py`
9. **DI wiring** — add `get_sensor_repository` + `get_sensor_service` to `druppie/api/deps.py`
10. **Route** — `druppie/api/routes/sensors.py`
11. **Register** — add router to `druppie/api/main.py`
12. **Frontend page** — `frontend/src/pages/Sensors.jsx` (if UI needed)
13. **API functions** — add to `frontend/src/services/api.js` (if UI needed)
