# Docker Compose Deployment & Builder Verification

**Date:** 2026-03-11
**Status:** Approved
**Branch:** feature/project-coding-standards (PR84 worktree)

---

## Problem

Generated apps fail at deployment because:

1. The **builder agent** rewrites the project template from scratch instead of extending it, introducing bugs (wrong DB types, missing imports, broken Dockerfile)
2. The **deployer** runs a single container (`docker run`) with no database — but the template assumes PostgreSQL
3. The **builder has no way to verify** its own output matches what the deployer will do — it can't build or start the app in the sandbox

Real example: FAQ app used `sqlalchemy.dialects.postgresql.UUID` with SQLite, forgot to import models before `create_all()`, created a separate `backend/` package ignoring the template's `app/` structure.

---

## Solution

Five changes that work together:

1. **Improve the project template** — add database setup with PostgreSQL, pre-wired models file
2. **Update `druppie-builder.md`** — teach the sandbox agent about the template, test compliance, and Docker Compose verification (if DinD is available)
3. **Add `compose_up` / `compose_down` to Docker MCP server** — deploy app + db together
4. **Update deployer prompt** — switch from `build` + `run` to `compose_up`
5. **Docker-in-Docker in sandbox** — install Docker CE in the sandbox image so the builder can verify builds

---

## 1. Project Template Changes

**Location:** `druppie/templates/project/`

### New file: `app/database.py`

```python
"""Database setup — PostgreSQL via DATABASE_URL env var."""

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings

engine = create_engine(settings.database_url)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI dependency for DB sessions."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Import all models and create tables. Call on app startup."""
    from app import models  # noqa: F401 — registers models with Base
    Base.metadata.create_all(bind=engine)
```

### New file: `app/models.py`

```python
"""Application models. Add your SQLAlchemy models here."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base

# Example model — replace or extend as needed:
#
# class Category(Base):
#     __tablename__ = "categories"
#     id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
#     name = Column(String(255), nullable=False)
#     created_at = Column(DateTime, default=datetime.utcnow)
```

### Updated: `app/main.py`

```python
"""Application entrypoint."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.database import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="app/templates")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
async def landing(request: Request):
    return templates.TemplateResponse("index.html", {
        "request": request,
        "app_name": settings.app_name,
    })
```

### `app/config.py` — unchanged

Already defaults to `postgresql://app:app@db:5432/app`. No changes needed.

### `docker-compose.yaml` — unchanged (already correct)

Already has `app` + `db` services, health check, pgdata volume. No changes needed.

### `Dockerfile` — unchanged

Already correct: `python:3.11-slim`, port 8000, uvicorn CMD.

### `requirements.txt` — unchanged

Already has `sqlalchemy`, `psycopg2-binary`, `fastapi`, `uvicorn`, `jinja2`.

---

## 2. `druppie-builder.md` — OpenCode Agent Prompt

**Location:** `druppie/opencode/config/agents/druppie-builder.md`

Replace current content with:

```markdown
---
description: Druppie coding agent — implements code and pushes to git
mode: primary
permission:
  skill:
    "fullstack-architecture": "allow"
    "project-coding-standards": "allow"
    "standards-validation": "allow"
---

## Project Template

This repo was initialized from a Druppie project template. The following is
already set up and working — extend it, don't replace it:

- `app/` — main Python package (FastAPI)
- `app/main.py` — entrypoint, creates the FastAPI `app` instance, calls `init_db()` on startup
- `app/database.py` — SQLAlchemy engine, `Base`, `get_db()` dependency, `init_db()`
- `app/models.py` — add your SQLAlchemy models here (imports are pre-wired)
- `app/config.py` — settings from environment variables
- `app/templates/` — Jinja2 HTML templates
- `static/` — static CSS/JS files
- `Dockerfile` — Python 3.11-slim, uvicorn on port 8000
- `docker-compose.yaml` — app + PostgreSQL database
- `requirements.txt` — base dependencies

### Rules

- **Use the `app/` package** — do NOT create separate `backend/`, `src/`, or other top-level packages
- **Extend existing files** — add models to `app/models.py`, add routes to `app/main.py` or new files in `app/`
- **Add dependencies** to `requirements.txt` — do NOT rewrite the file from scratch
- **Do NOT modify** `Dockerfile` or `docker-compose.yaml` unless you change the entrypoint or add services
- **Use PostgreSQL types** — this project runs on PostgreSQL, use `sqlalchemy.dialects.postgresql.UUID` for UUIDs
- **`/health` endpoint must stay** — the deployment system uses it to verify the app is running

## Test Compliance

Tests written by the test agent are already in this repo. They are the source of truth.

1. After implementing your code, run the tests:
   - Python: `pip install -r requirements.txt && pytest -v`
   - Node.js: `npm install && npm test`
2. Read any failures carefully, fix the code, re-run
3. **Never modify test files** — if a test fails, your implementation is wrong
4. All tests must pass before proceeding to verification

## Build Verification (if Docker is available)

After tests pass, check if Docker is available in the sandbox:

```bash
docker info > /dev/null 2>&1
```

If Docker IS available, verify the app builds and starts correctly using Docker Compose.
This is the same method used to deploy your app — if it works here, deployment will succeed.

```bash
# Build and start app + database
docker compose up -d --build

# Wait for services to be healthy (up to 30 seconds)
for i in $(seq 1 30); do
  curl -sf http://localhost:8000/health && break
  sleep 1
done

# Check the health endpoint returns 200
curl -f http://localhost:8000/health

# If health check fails, check the logs:
docker compose logs app

# Clean up
docker compose down -v
```

If the build fails or health check doesn't pass:
1. Read the error from `docker compose logs app`
2. Fix the code
3. Re-run tests
4. Re-run build verification
5. Repeat until both tests and build verification pass

If Docker is NOT available, skip build verification — tests alone are sufficient.
The deployer will catch build issues during deployment.

## Git Workflow (MANDATORY)

After tests pass (and build verification succeeds, if Docker was available):
1. Stage files explicitly: `git add <specific-files>` (avoid `git add -A`)
2. Commit: `git commit -m "descriptive message"`
3. Push: `git push origin HEAD`

Never leave commits unpushed. Every task MUST end with `git push`.

## Completion Summary (MANDATORY)

Before your final git push, output a summary in this exact format:

---SUMMARY---
Files created: [list of new files]
Files modified: [list of modified files]
Tests: [pass/fail count]
Build verification: [pass/fail/skipped (no Docker)]
Key decisions: [any non-obvious implementation choices]
---END SUMMARY---
```

---

## 3. Docker MCP Server — `compose_up` and `compose_down`

**Location:** `druppie/mcp-servers/docker/server.py`

### `compose_up` tool

```python
@mcp.tool()
async def compose_up(
    repo_name: str | None = None,
    repo_owner: str | None = None,
    git_url: str | None = None,
    branch: str = "main",
    compose_project_name: str | None = None,
    project_id: str | None = None,
    session_id: str | None = None,
    user_id: str | None = None,
    health_path: str = "/health",
    health_timeout: int = 30,
) -> dict:
```

**Steps:**
1. Clone from Gitea (same as `build` tool — `git clone --branch {branch} --depth 1`)
2. Verify `docker-compose.yaml` exists in repo root
3. Allocate host port from 9100-9199 via existing `get_next_port()`
4. Determine compose project name: `compose_project_name` param, or derive as `{repo_name}-{session_id[:8]}` to guarantee uniqueness
5. Write a temporary `docker-compose.override.yaml` in the cloned directory to inject labels:
   ```yaml
   services:
     app:
       labels:
         druppie.project_id: "{project_id}"
         druppie.session_id: "{session_id}"
         druppie.user_id: "{user_id}"
         druppie.branch: "{branch}"
         druppie.compose_project: "{compose_project_name}"
   ```
6. Run:
   ```
   APP_PORT={port} docker compose -p {compose_project_name} up -d --build
   ```
   - `APP_PORT` env var overrides the port mapping in the compose file (`${APP_PORT:-8000}:8000`)
   - `-p` sets the compose project name for isolation
   - The override file is automatically picked up by compose
7. Store port mapping: `compose_port_registry[compose_project_name] = port` (module-level dict, alongside existing `used_ports`)
8. Poll health endpoint: `GET http://localhost:{port}{health_path}` for up to `health_timeout` seconds
9. Clean up cloned temp directory (compose containers run detached — compose tracks projects by name, not directory)
10. Return:
   ```json
   {
     "success": true,
     "url": "http://localhost:{port}",
     "port": 9101,
     "compose_project_name": "faq-app-abc12345",
     "containers": ["faq-app-abc12345-app-1", "faq-app-abc12345-db-1"],
     "health_check": "passed",
     "labels": { ... }
   }
   ```

**Error cases:**
- No `docker-compose.yaml` → return `{success: false, error: "No docker-compose.yaml found"}`
- Build fails → return `{success: false, error: ..., build_log: ...}`
- Health check times out → return `{success: false, error: "Health check failed after {timeout}s", logs: ...}`
  - Also runs `docker compose -p {name} logs app` to capture app logs in the error

### `compose_down` tool

```python
@mcp.tool()
async def compose_down(
    compose_project_name: str,
    remove_volumes: bool = True,
) -> dict:
```

**Steps:**
1. Look up port from `compose_port_registry[compose_project_name]`
2. Run `docker compose -p {compose_project_name} down` (add `-v` if `remove_volumes`)
3. Release the port via `release_port()` and remove from `compose_port_registry`
4. Return `{success: true, stopped: compose_project_name}`

### `mcp_config.yaml` entries

Add to the `docker` section in `druppie/core/mcp_config.yaml`:

```yaml
    compose_up:
      description: "Deploy application with docker compose (app + database)"
      requires_approval: true
      required_role: developer
      parameters:
        repo_name:
          type: string
          description: "Gitea repository name"
          required: false
        repo_owner:
          type: string
          description: "Gitea repository owner"
          required: false
        git_url:
          type: string
          description: "Full git URL (alternative to repo_name/repo_owner)"
          required: false
        branch:
          type: string
          description: "Git branch to deploy"
          required: false
        compose_project_name:
          type: string
          description: "Docker Compose project name"
          required: false
        health_path:
          type: string
          description: "Health check endpoint path"
          required: false
        health_timeout:
          type: integer
          description: "Health check timeout in seconds"
          required: false
      injection_rules:
        - parameter: session_id
          source: session.id
          hidden: true
          tools: [compose_up]
        - parameter: repo_name
          source: project.repo_name
          hidden: true
          tools: [compose_up]
        - parameter: repo_owner
          source: project.repo_owner
          hidden: true
          tools: [compose_up]
        - parameter: user_id
          source: session.user_id
          hidden: true
          tools: [compose_up]
        - parameter: project_id
          source: session.project_id
          hidden: true
          tools: [compose_up]

    compose_down:
      description: "Stop and remove a docker compose deployment"
      requires_approval: true
      required_role: developer
      parameters:
        compose_project_name:
          type: string
          description: "Docker Compose project name to stop"
          required: true
        remove_volumes:
          type: boolean
          description: "Remove associated volumes"
          required: false
```

### Parameter models

Add to `druppie/tools/params/docker.py`:

```python
class DockerComposeUpParams(BaseModel):
    repo_name: str | None = Field(None, description="Gitea repository name")
    repo_owner: str | None = Field(None, description="Gitea repository owner")
    git_url: str | None = Field(None, description="Full git URL")
    branch: str = Field("main", description="Git branch to deploy")
    compose_project_name: str | None = Field(None, description="Compose project name")
    session_id: str | None = Field(None, description="Session ID (injected)")
    project_id: str | None = Field(None, description="Project ID (injected)")
    user_id: str | None = Field(None, description="User ID (injected)")
    health_path: str = Field("/health", description="Health check endpoint path")
    health_timeout: int = Field(30, description="Health check timeout in seconds")


class DockerComposeDownParams(BaseModel):
    compose_project_name: str = Field(..., description="Compose project name to stop")
    remove_volumes: bool = Field(True, description="Remove associated volumes")
```

---

## 4. Deployer Agent Prompt Changes

**Location:** `druppie/agents/definitions/deployer.yaml`

### Key changes to the deployment workflow section:

**Old flow (8 steps):**
```
list_containers → list_dir → read Dockerfile → create if missing →
run_git → docker:build → docker:run → docker:logs → done()
```

**New flow (4 steps):**
```
1. docker:list_containers — discover existing containers for this project
2. docker:compose_up — clone, build, start app + db, health check
   - branch: from PREVIOUS AGENT SUMMARY or "main"
   - compose_project_name: based on naming rules (project name or project-preview)
3. Verify: if compose_up returns success with health_check "passed", deployment is good
   - If it fails, read the error/logs, try to fix (write_file + run_git to commit + retry)
4. done() — include URL, compose project name, branch
```

**Container naming** (using compose project names now):
- `create_project`: compose project = `{project-name}` (e.g., `faq-app-abc12345`)
- Preview deploy: compose project = `{project-name}-preview`
- Final deploy:
  1. `compose_down({project-name}-preview)` — stop preview
  2. `compose_down({project-name})` — stop old production
  3. `compose_up` with compose project = `{project-name}`

**MCP tools update:**
```yaml
mcps:
  docker:
    - compose_up        # NEW — replaces build + run
    - compose_down      # NEW — replaces stop + remove
    - list_containers   # keep — for discovery
    - logs              # keep — for debugging
    - inspect           # keep — for debugging
  coding:
    - read_file         # keep
    - write_file        # keep
    - list_dir          # keep
    - run_git           # keep — used for git commit/push operations
```

Remove `build`, `run`, `stop` from the deployer's tool list (they still exist in the MCP server but the deployer doesn't need them anymore).

---

## 5. Docker-in-Docker in Sandbox

**Goal:** The builder agent can run `docker compose up --build` inside the sandbox to verify its own output before pushing.

### Sandbox Image Changes

**Location:** `vendor/open-inspect/packages/local-sandbox-manager/Dockerfile.sandbox`

Add Docker CE CLI + Docker Compose + dockerd to the sandbox image:

```dockerfile
# Install Docker CE (daemon + CLI + compose plugin)
RUN install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc \
    && chmod a+r /etc/apt/keyrings/docker.asc \
    && echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian bookworm stable" \
       > /etc/apt/sources.list.d/docker.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
       docker-ce docker-ce-cli containerd.io docker-compose-plugin \
    && rm -rf /var/lib/apt/lists/*
```

This adds ~350-450MB to the image (Docker CE + containerd + compose plugin). The Docker daemon (`dockerd`) runs inside the sandbox as a local service — completely isolated from the host Docker.

### Entrypoint Changes

**Location:** `vendor/open-inspect/packages/modal-infra/src/sandbox/entrypoint.py`

Add a new phase between Git Sync and OpenCode startup:

```
Phase 2.7 — Start Docker Daemon (DinD)
1. Create tmpfs for Docker storage: mkdir -p /var/lib/docker
   (avoids overlay-on-overlay issues when sandbox itself runs on overlay2)
2. Start dockerd in background: `dockerd --storage-driver=overlay2 &`
   Store PID: DOCKERD_PID=$!
3. Wait for Docker socket: poll /var/run/docker.sock for up to 10s
4. Verify: `docker info` succeeds
5. Log: "Docker daemon ready (DinD)"
```

If the daemon fails to start (e.g. missing capabilities), log a warning and continue — Docker verification becomes unavailable but the builder can still code and run tests. This makes it gracefully degrade.

### Cleanup on Shutdown

Add to the supervisor's `shutdown()` method in `entrypoint.py`:

```python
# Stop inner Docker containers and daemon
if DOCKERD_PID:
    subprocess.run(["docker", "compose", "down", "-v"], capture_output=True, timeout=10)
    os.kill(DOCKERD_PID, signal.SIGTERM)
```

This ensures inner containers are cleaned up when the sandbox shuts down.

### Runtime-Specific Considerations

**Kata containers (VM isolation):**
- DinD works out of the box — the sandbox has its own kernel inside a VM
- No capability changes needed, `--net-host` already gives full network access within the VM
- Docker daemon runs as root inside the VM — safe because VM is the isolation boundary

**Docker containers:**
- Current security: `--cap-drop=ALL` + minimal cap-adds + `--security-opt=no-new-privileges`
- DinD requires `SYS_ADMIN` capability for the Docker daemon to manage cgroups/namespaces
- DinD also requires removing `--security-opt=no-new-privileges` — the inner `containerd-shim` needs to gain capabilities when spawning inner containers. With `no-new-privileges` set, inner container creation will fail.
- Changes to `docker_manager.py`'s `create_sandbox()`:
  ```python
  # Add capabilities for DinD
  "--cap-add=SYS_ADMIN",      # Required for Docker-in-Docker (cgroups/namespaces)
  "--cap-add=MKNOD",          # Required for device nodes (DinD)

  # Remove --security-opt=no-new-privileges (incompatible with DinD)
  # The inner containerd-shim requires privilege escalation to spawn containers
  ```
- **Resource limits** — DinD runs dockerd + containerd + inner containers (app + PostgreSQL) inside the sandbox. Minimum requirements:
  - PID limit: increase from current default to at least **8192** (dockerd + containerd + shims + inner containers)
  - Memory limit: keep at **4GB** (sufficient for app + PostgreSQL + overhead)
  - CPU limit: keep at **2** CPUs
  - Update `config.py`: `DOCKER_PIDS_LIMIT = 8192`
- **Mitigations** (compensating for `no-new-privileges` removal):
  - `--cap-drop=ALL` still active — only `SYS_ADMIN` and `MKNOD` are added back
  - Network isolation: sandbox is on `druppie-sandbox-network` — cannot reach Gitea, DB, backend, MCP servers
  - Memory, CPU limits still enforced
  - Inner Docker daemon's containers share the outer sandbox's cgroup — all resource consumption counts toward the sandbox's limits
  - Sandboxes are ephemeral — destroyed after the agent task completes

**Modal sandboxes:**
- Modal's `base.py` image builder needs the same Docker CE installation
- The Modal sandbox creation may need additional flags — check Modal docs for DinD support
- If Modal doesn't support DinD, the entrypoint's graceful degradation means the builder just skips Docker verification

### What the Builder Sees

After DinD is running, the sandbox has:
- `docker` CLI available
- `docker compose` available (plugin installed with Docker CE)
- A local Docker daemon that is completely isolated
- No access to the host's Docker or any other containers outside the sandbox

The builder's verification flow from section 2 works as-is:
```bash
docker compose up -d --build    # builds app + starts PostgreSQL inside sandbox
curl -f http://localhost:8000/health
docker compose down -v
```

---

## What Stays The Same

- **Agent pipeline order** — router → planner → BA → architect → builder_planner → test_builder → builder → test_executor → deployer → summarizer
- **`set_intent` / template push** — already works correctly
- **Approval flow** — `compose_up` requires developer approval (same as `build` + `run` today)
- **Port range** — 9100-9199
- **Label-based tracking** — same labels, just applied via compose override
- **Old tools** — `build`, `run`, `stop`, `remove`, `exec_command` remain in Docker MCP for backwards compat
- **Skills** — `fullstack-architecture`, `project-coding-standards`, `standards-validation` unchanged

---

## Files Changed

| File | Change |
|------|--------|
| `druppie/templates/project/app/database.py` | **New** — SQLAlchemy setup with `init_db()` |
| `druppie/templates/project/app/models.py` | **New** — empty models file with correct imports |
| `druppie/templates/project/app/main.py` | **Updated** — use lifespan, call `init_db()` |
| `druppie/opencode/config/agents/druppie-builder.md` | **Updated** — template awareness, test compliance, conditional build verification |
| `druppie/mcp-servers/docker/server.py` | **Updated** — add `compose_up` and `compose_down` tools, `compose_port_registry` |
| `druppie/tools/params/docker.py` | **Updated** — add `DockerComposeUpParams` and `DockerComposeDownParams` |
| `druppie/agents/definitions/deployer.yaml` | **Updated** — switch to `compose_up` flow, remove `build`/`run`/`stop` |
| `druppie/core/mcp_config.yaml` | **Updated** — add `compose_up`/`compose_down` tool entries with injection + approval config |
| `vendor/open-inspect/.../Dockerfile.sandbox` | **Updated** — add Docker CE + Compose plugin for DinD (~350-450MB) |
| `vendor/open-inspect/.../entrypoint.py` | **Updated** — add Docker daemon startup phase (2.7) + shutdown cleanup |
| `vendor/open-inspect/.../docker_manager.py` | **Updated** — add `SYS_ADMIN` + `MKNOD` caps, remove `no-new-privileges`, increase PID limit |
| `vendor/open-inspect/.../config.py` | **Updated** — increase `DOCKER_PIDS_LIMIT` to 8192 |
| `vendor/open-inspect/.../base.py` | **Updated** — add Docker CE to Modal image (if Modal supports DinD) |
