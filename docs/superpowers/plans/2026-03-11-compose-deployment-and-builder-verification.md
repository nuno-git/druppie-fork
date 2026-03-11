# Docker Compose Deployment & Builder Verification — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make builder agents produce deployable apps and let the deployer use Docker Compose for app+database deployments.

**Architecture:** Three independent workstreams: (A) improve the project template and builder prompt so agents extend rather than rewrite, (B) add `compose_up`/`compose_down` MCP tools and update the deployer, (C) install Docker-in-Docker in the sandbox so the builder can self-verify.

**Tech Stack:** Python/FastAPI (template), FastMCP (Docker MCP server), Docker CE (DinD), SQLAlchemy+PostgreSQL, Pydantic, YAML config.

**Spec:** `docs/superpowers/specs/2026-03-11-compose-deployment-and-builder-verification-design.md`

---

## Chunk 1: Project Template & Builder Prompt

### Task 1: Add `app/database.py` to the project template

**Files:**
- Create: `druppie/templates/project/app/database.py`

- [ ] **Step 1: Create `app/database.py`**

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

- [ ] **Step 2: Verify file is syntactically valid**

Run: `cd /home/nuno/Documents/cleaner-druppie-pr84 && python -c "import ast; ast.parse(open('druppie/templates/project/app/database.py').read()); print('OK')"`
Expected: `OK`

---

### Task 2: Add `app/models.py` to the project template

**Files:**
- Create: `druppie/templates/project/app/models.py`

- [ ] **Step 1: Create `app/models.py`**

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

- [ ] **Step 2: Verify file is syntactically valid**

Run: `cd /home/nuno/Documents/cleaner-druppie-pr84 && python -c "import ast; ast.parse(open('druppie/templates/project/app/models.py').read()); print('OK')"`
Expected: `OK`

---

### Task 3: Update `app/main.py` in the project template

**Files:**
- Modify: `druppie/templates/project/app/main.py` (full rewrite — 27 lines → 27 lines)

- [ ] **Step 1: Replace `app/main.py` content**

Replace the entire file with:

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

Key changes from the current version:
- Added `from contextlib import asynccontextmanager`
- Added `from app.database import init_db`
- Added `lifespan` context manager that calls `init_db()` on startup
- Changed `FastAPI()` constructor to include `lifespan=lifespan`

- [ ] **Step 2: Verify file is syntactically valid**

Run: `cd /home/nuno/Documents/cleaner-druppie-pr84 && python -c "import ast; ast.parse(open('druppie/templates/project/app/main.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit template changes**

```bash
cd /home/nuno/Documents/cleaner-druppie-pr84
git add druppie/templates/project/app/database.py druppie/templates/project/app/models.py druppie/templates/project/app/main.py
git commit -m "feat(template): add database.py and models.py, wire init_db in main.py"
```

---

### Task 4: Update `druppie-builder.md` OpenCode agent prompt

**Files:**
- Modify: `druppie/opencode/config/agents/druppie-builder.md` (full rewrite — 37 lines → ~110 lines)

- [ ] **Step 1: Replace `druppie-builder.md` content**

Replace the entire file with the content from spec Section 2 (lines 159-266). The full content is:

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

- [ ] **Step 2: Verify the markdown renders (frontmatter is valid YAML)**

Run: `cd /home/nuno/Documents/cleaner-druppie-pr84 && python -c "
import yaml
with open('druppie/opencode/config/agents/druppie-builder.md') as f:
    content = f.read()
# Extract frontmatter between --- markers
parts = content.split('---', 2)
if len(parts) >= 3:
    yaml.safe_load(parts[1])
    print('OK')
"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
cd /home/nuno/Documents/cleaner-druppie-pr84
git add druppie/opencode/config/agents/druppie-builder.md
git commit -m "feat(builder): add template awareness, test compliance, and build verification to builder prompt"
```

---

## Chunk 2: Docker MCP Compose Tools

### Task 5: Add `DockerComposeUpParams` and `DockerComposeDownParams` to parameter models

**Files:**
- Modify: `druppie/tools/params/docker.py:61` (append after `DockerExecCommandParams`)
- Modify: `druppie/tools/params/__init__.py:55-64` (add imports) and `:73-100` (add to `__all__`)

- [ ] **Step 1: Add parameter models to `docker.py`**

Append after `DockerExecCommandParams` class (after line 60):

```python


class DockerComposeUpParams(BaseModel):
    # Note: repo_name, repo_owner, session_id, project_id, user_id are injected
    # at runtime (same as DockerBuildParams/DockerRunParams) — not included here.
    git_url: str | None = Field(default=None, description="Full git URL")
    branch: str = Field(default="main", description="Git branch to deploy")
    compose_project_name: str | None = Field(default=None, description="Compose project name")
    health_path: str = Field(default="/health", description="Health check endpoint path")
    health_timeout: int = Field(default=30, description="Health check timeout in seconds")


class DockerComposeDownParams(BaseModel):
    compose_project_name: str = Field(..., description="Compose project name to stop")
    remove_volumes: bool = Field(default=True, description="Remove associated volumes")
```

- [ ] **Step 2: Update `__init__.py` imports**

Add to the docker import block (line 55-64 of `druppie/tools/params/__init__.py`):

```python
from .docker import (
    DockerBuildParams,
    DockerComposeDownParams,
    DockerComposeUpParams,
    DockerExecCommandParams,
    DockerInspectParams,
    DockerListContainersParams,
    DockerLogsParams,
    DockerRemoveParams,
    DockerRunParams,
    DockerStopParams,
)
```

Add to the `__all__` Docker section (after line 100):

```python
    "DockerComposeUpParams",
    "DockerComposeDownParams",
```

- [ ] **Step 3: Verify models import correctly**

Run: `cd /home/nuno/Documents/cleaner-druppie-pr84 && python -c "from druppie.tools.params.docker import DockerComposeUpParams, DockerComposeDownParams; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
cd /home/nuno/Documents/cleaner-druppie-pr84
git add druppie/tools/params/docker.py druppie/tools/params/__init__.py
git commit -m "feat(params): add DockerComposeUpParams and DockerComposeDownParams"
```

---

### Task 6: Add `compose_up` tool to Docker MCP server

**Files:**
- Modify: `druppie/mcp-servers/docker/server.py:44` (add `compose_port_registry` after `used_ports`)
- Modify: `druppie/mcp-servers/docker/server.py` (add `compose_up` function after the `run` tool, around line 519)

- [ ] **Step 1: Add `compose_port_registry` module-level dict**

After line 44 (`used_ports: set[int] = set()`), add:

```python
# Track compose project -> port mapping for clean teardown
compose_port_registry: dict[str, int] = {}
```

- [ ] **Step 2: Add top-level imports**

Add these imports to the top of `server.py` (after line 17, with the other imports):

```python
import time
import urllib.request
```

(`time` is not currently imported; `urllib.request` is not currently imported.)

- [ ] **Step 3: Add `compose_up` tool**

Add after the `run` tool (after line 519, before `stop`). Insert the following:

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
    """Deploy application with docker compose (app + database).

    Clones from git, writes a label override, runs `docker compose up -d --build`,
    waits for health check, then returns the URL.

    Args:
        repo_name: Gitea repo name (constructs URL using Gitea config)
        repo_owner: Gitea repo owner (defaults to "druppie" org)
        git_url: Full git URL (alternative to repo_name/repo_owner)
        branch: Git branch (default: main)
        compose_project_name: Docker Compose project name (auto-derived if omitted)
        project_id: Project ID for labels (injected)
        session_id: Session ID for labels (injected)
        user_id: User ID for labels (injected)
        health_path: Health check endpoint path (default: /health)
        health_timeout: Seconds to wait for health check (default: 30)

    Returns:
        Dict with success, url, port, compose_project_name, containers, health_check
    """
    try:
        if not git_url and not repo_name:
            return {"success": False, "error": "Must provide either git_url or repo_name"}

        url = git_url or get_gitea_clone_url(repo_name, repo_owner)

        # Step 1: Clone repository
        build_id = str(uuid.uuid4())[:8]
        clone_path = BUILD_DIR / build_id
        BUILD_DIR.mkdir(parents=True, exist_ok=True)

        logger.info("compose_up: cloning %s (branch: %s)", url, branch)
        clone_result = subprocess.run(
            ["git", "clone", "--branch", branch, "--depth", "1", url, str(clone_path)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if clone_result.returncode != 0:
            return {"success": False, "error": f"Git clone failed: {clone_result.stderr}"}

        # Step 2: Verify docker-compose.yaml exists
        compose_file = clone_path / "docker-compose.yaml"
        if not compose_file.exists():
            compose_file = clone_path / "docker-compose.yml"
        if not compose_file.exists():
            shutil.rmtree(clone_path, ignore_errors=True)
            return {"success": False, "error": "No docker-compose.yaml found in repository"}

        # Step 3: Allocate host port
        host_port = get_next_port()

        # Step 4: Determine compose project name
        project_name = compose_project_name
        if not project_name:
            sid_suffix = (session_id or build_id)[:8]
            project_name = f"{repo_name or 'app'}-{sid_suffix}"
        # Sanitize: compose project names must be lowercase alphanumeric + hyphens
        project_name = project_name.lower().replace("_", "-")

        # Step 5: Write override file with druppie labels and network config
        # Attach compose containers to the same Docker network as the MCP server
        # so health checks can reach them via container name (not localhost).
        labels = {}
        if project_id:
            labels["druppie.project_id"] = project_id
        if session_id:
            labels["druppie.session_id"] = session_id
        if user_id:
            labels["druppie.user_id"] = user_id
        if branch:
            labels["druppie.branch"] = branch
        labels["druppie.compose_project"] = project_name

        override_content = "services:\n  app:\n    labels:\n"
        for k, v in labels.items():
            override_content += f'      {k}: "{v}"\n'

        # Join the Druppie Docker network so containers are discoverable
        # and the health check can reach them from inside the MCP server
        if DOCKER_NETWORK:
            override_content += f"""
networks:
  default:
    external: true
    name: {DOCKER_NETWORK}
"""

        override_path = clone_path / "docker-compose.override.yaml"
        override_path.write_text(override_content)

        # Step 6: Run docker compose up
        logger.info("compose_up: starting project %s on port %d", project_name, host_port)
        env = {**os.environ, "APP_PORT": str(host_port)}
        compose_result = subprocess.run(
            ["docker", "compose", "-p", project_name, "up", "-d", "--build"],
            capture_output=True,
            text=True,
            timeout=600,
            cwd=str(clone_path),
            env=env,
        )

        if compose_result.returncode != 0:
            release_port(host_port)
            shutil.rmtree(clone_path, ignore_errors=True)
            return {
                "success": False,
                "error": "Docker compose up failed",
                "build_log": compose_result.stdout + compose_result.stderr,
            }

        # Step 7: Track port mapping
        compose_port_registry[project_name] = host_port

        # Step 8: Health check via Docker network (not localhost)
        # The MCP server runs inside a container, so localhost:{host_port} won't
        # reach the app. Instead, use the compose service container name on the
        # internal port (8000) via the shared Docker network.
        app_container = f"{project_name}-app-1"
        health_url = f"http://{app_container}:8000{health_path}"
        health_passed = False

        for _ in range(health_timeout):
            try:
                req = urllib.request.Request(health_url)
                with urllib.request.urlopen(req, timeout=2) as resp:
                    if resp.status == 200:
                        health_passed = True
                        break
            except Exception:
                pass
            time.sleep(1)

        # Step 9: Clean up cloned temp directory
        shutil.rmtree(clone_path, ignore_errors=True)

        if not health_passed:
            # Get logs for debugging
            log_result = subprocess.run(
                ["docker", "compose", "-p", project_name, "logs", "app"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return {
                "success": False,
                "error": f"Health check failed after {health_timeout}s",
                "url": f"http://localhost:{host_port}",
                "port": host_port,
                "compose_project_name": project_name,
                "logs": log_result.stdout + log_result.stderr,
            }

        # Step 10: Get container list
        ps_result = subprocess.run(
            ["docker", "compose", "-p", project_name, "ps", "--format", "{{.Name}}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        containers = [c.strip() for c in ps_result.stdout.strip().split("\n") if c.strip()]

        logger.info("compose_up: project %s running on port %d", project_name, host_port)

        return {
            "success": True,
            "url": f"http://localhost:{host_port}",
            "port": host_port,
            "compose_project_name": project_name,
            "containers": containers,
            "health_check": "passed",
            "labels": labels,
        }

    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Operation timed out"}
    except Exception as e:
        return {"success": False, "error": str(e)}
```

- [ ] **Step 4: Verify syntax**

Run: `cd /home/nuno/Documents/cleaner-druppie-pr84 && python -c "import ast; ast.parse(open('druppie/mcp-servers/docker/server.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
cd /home/nuno/Documents/cleaner-druppie-pr84
git add druppie/mcp-servers/docker/server.py
git commit -m "feat(docker-mcp): add compose_up tool with health check and label injection"
```

---

### Task 7: Add `compose_down` tool to Docker MCP server

**Files:**
- Modify: `druppie/mcp-servers/docker/server.py` (add `compose_down` right after `compose_up`)

- [ ] **Step 1: Add `compose_down` tool**

Insert right after the `compose_up` function:

```python
@mcp.tool()
async def compose_down(
    compose_project_name: str,
    remove_volumes: bool = True,
) -> dict:
    """Stop and remove a docker compose deployment.

    Args:
        compose_project_name: Compose project name to stop
        remove_volumes: Remove associated volumes (default: True)

    Returns:
        Dict with success, stopped project name
    """
    try:
        # Look up port from in-memory registry (may be empty after MCP server restart)
        port = compose_port_registry.get(compose_project_name)

        # Fallback: discover port from running containers if not in registry
        if port is None:
            try:
                ps_result = subprocess.run(
                    ["docker", "compose", "-p", compose_project_name, "ps",
                     "--format", "{{.Ports}}"],
                    capture_output=True, text=True, timeout=10,
                )
                # Parse "0.0.0.0:9101->8000/tcp" to extract host port
                for mapping in ps_result.stdout.split(","):
                    if "->" in mapping:
                        host_part = mapping.strip().split("->")[0]
                        port_str = host_part.rsplit(":", 1)[-1]
                        port = int(port_str)
                        break
            except Exception:
                pass

        # Run docker compose down
        cmd = ["docker", "compose", "-p", compose_project_name, "down"]
        if remove_volumes:
            cmd.append("-v")

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
        )

        if result.returncode != 0:
            return {
                "success": False,
                "error": f"Docker compose down failed: {result.stderr}",
            }

        # Release port
        if port:
            release_port(port)
            compose_port_registry.pop(compose_project_name, None)

        logger.info("compose_down: stopped project %s", compose_project_name)

        return {
            "success": True,
            "stopped": compose_project_name,
            "removed_volumes": remove_volumes,
        }

    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Operation timed out"}
    except Exception as e:
        return {"success": False, "error": str(e)}
```

- [ ] **Step 2: Verify syntax**

Run: `cd /home/nuno/Documents/cleaner-druppie-pr84 && python -c "import ast; ast.parse(open('druppie/mcp-servers/docker/server.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
cd /home/nuno/Documents/cleaner-druppie-pr84
git add druppie/mcp-servers/docker/server.py
git commit -m "feat(docker-mcp): add compose_down tool with port release"
```

---

### Task 8: Add `compose_up`/`compose_down` to `mcp_config.yaml`

**Files:**
- Modify: `druppie/core/mcp_config.yaml` — add to `docker` section

Two changes:
1. Update the `inject` block to include `compose_up` in the tool lists
2. Add two new tool entries after `exec_command`

- [ ] **Step 1: Update injection rules**

In `druppie/core/mcp_config.yaml`, update the docker `inject` block (lines 234-254).

Change the `tools` arrays to include `compose_up`:

```yaml
    inject:
      session_id:
        from: session.id
        hidden: true
        tools: [build, run, compose_up]
      repo_name:
        from: project.repo_name
        hidden: true
        tools: [build, compose_up]
      repo_owner:
        from: project.repo_owner
        hidden: true
        tools: [build, compose_up]
      user_id:
        from: session.user_id
        hidden: true
        tools: [run, compose_up]
      project_id:
        from: session.project_id
        hidden: true
        tools: [run, compose_up]
```

- [ ] **Step 2: Add `compose_up` tool entry**

After the `exec_command` tool entry (after line 418 in `mcp_config.yaml`), add:

```yaml
      - name: compose_up
        description: "Deploy application with docker compose (app + database)"
        requires_approval: true
        required_role: developer
        parameters:
          type: object
          properties:
            repo_name:
              type: string
              description: "Gitea repository name"
            repo_owner:
              type: string
              description: "Gitea repository owner"
            git_url:
              type: string
              description: "Full git URL (alternative to repo_name/repo_owner)"
            branch:
              type: string
              description: "Git branch to deploy (default: main)"
            compose_project_name:
              type: string
              description: "Docker Compose project name (auto-derived if omitted)"
            health_path:
              type: string
              description: "Health check endpoint path (default: /health)"
            health_timeout:
              type: integer
              description: "Health check timeout in seconds (default: 30)"
          required: []

      - name: compose_down
        description: "Stop and remove a docker compose deployment"
        requires_approval: true
        required_role: developer
        parameters:
          type: object
          properties:
            compose_project_name:
              type: string
              description: "Docker Compose project name to stop"
            remove_volumes:
              type: boolean
              description: "Remove associated volumes (default: true)"
          required:
            - compose_project_name
```

- [ ] **Step 3: Validate YAML syntax**

Run: `cd /home/nuno/Documents/cleaner-druppie-pr84 && python -c "import yaml; yaml.safe_load(open('druppie/core/mcp_config.yaml')); print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
cd /home/nuno/Documents/cleaner-druppie-pr84
git add druppie/core/mcp_config.yaml
git commit -m "feat(config): add compose_up and compose_down tool entries with injection rules"
```

---

### Task 9: Update deployer agent YAML

**Files:**
- Modify: `druppie/agents/definitions/deployer.yaml:6-212` (system_prompt rewrite + mcps update)

> **Important:** Steps 2-6 below modify different sections of the `system_prompt` string. Line numbers reference the **original** file. Apply all text replacements in a single editing pass to avoid line-number drift. Read the full file first, then make all substitutions before saving.

- [ ] **Step 1: Update the `mcps` section**

Replace the `mcps` block (lines 195-208) with:

```yaml
mcps:
  docker:
    - compose_up
    - compose_down
    - list_containers
    - logs
    - inspect
  coding:
    - read_file
    - write_file
    - list_dir
    - run_git
```

- [ ] **Step 2: Update the DEPLOYMENT WORKFLOW section**

In the `system_prompt` field, replace the DEPLOYMENT WORKFLOW section (lines 81-125) with:

```
  =============================================================================
  DEPLOYMENT WORKFLOW
  =============================================================================

  STEP 0 — DISCOVER EXISTING CONTAINERS (ALWAYS DO THIS FIRST!):
  Call docker_list_containers to see what's already running for this project.
  Look at the container names and the druppie.project_id label.
  This tells you:
  - What containers already exist (so you know if you need to stop old ones)
  - What compose projects are running

  COMPOSE PROJECT NAMING:
  - For create_project (no existing containers): use project name
    - compose_project_name: "todo-app" (or let it auto-derive)
  - For PREVIEW deploy (existing production found):
    - KEEP the existing production running!
    - compose_project_name: "<project>-preview"
  - For FINAL deploy (after PR merge):
    - Stop preview: docker_compose_down(compose_project_name="<project>-preview")
    - Stop old production: docker_compose_down(compose_project_name="<project>")
    - Deploy new: docker_compose_up with compose_project_name="<project>"

  STEPS:
  0. Use docker_list_containers to discover existing containers
  1. Use docker_compose_up (requires approval)
     - branch: from PREVIOUS AGENT SUMMARY or "main" for create_project
     - compose_project_name: based on naming rules above
     - repo_name/repo_owner/session_id/project_id/user_id are auto-injected
  2. Verify: if compose_up returns success with health_check "passed", deployment is good
     - The URL and port are in the compose_up result
     - If it fails, read the error/logs, try to fix (write_file + run_git to commit + retry)
  3. Use docker_logs if you need to debug (use compose project container names from result)
  4. Only report success once compose_up returns health_check "passed"
```

- [ ] **Step 3: Update RESUME CHECK section**

Replace the RESUME CHECK section (lines 36-57) to reference compose_up instead of build/run:

```
  =============================================================================
  RESUME CHECK (VERY IMPORTANT - CHECK FIRST!)
  =============================================================================

  BEFORE doing anything, check the CONTEXT section for these fields:

  1. If CONTEXT contains "deployment_complete: True":
     - The deployment is ALREADY FINISHED
     - DO NOT call any tools
     - Immediately call done() with the deployment info from CONTEXT

  2. If CONTEXT contains "last_approved_tool: docker:compose_up" and "last_tool_result":
     - docker:compose_up was JUST executed successfully
     - DO NOT call compose_up again
     - Extract the URL, compose project name, and port from last_tool_result
     - Call done() with that information

  3. If CONTEXT contains "last_approved_tool: docker:compose_down":
     - compose_down was just executed (preview teardown)
     - Continue with compose_up for the final deployment
```

- [ ] **Step 4: Update BRANCH SELECTION section**

Replace the BRANCH SELECTION section (lines 58-66) with:

```
  =============================================================================
  BRANCH SELECTION (CRITICAL FOR docker:compose_up!)
  =============================================================================
  The branch parameter is NOT auto-injected. You must pass it explicitly.

  - Read the PREVIOUS AGENT SUMMARY for the branch name.
  - For create_project: pass branch="main" (or omit — defaults to main).
  - For update_project PREVIEW: pass branch="<feature-branch-from-summary>".
  - For update_project FINAL (after PR merge): pass branch="main".
  - If unsure, call coding_run_git(command="status") to check the workspace state.
```

- [ ] **Step 5: Remove DOCKERFILE CREATION section**

Delete the DOCKERFILE CREATION section (lines 160-186) entirely — all Druppie projects use the template which already provides Dockerfile and docker-compose.yaml. The deployer now only handles template-based projects via `compose_up`. The old `build`/`run` tools remain in the Docker MCP server for backwards compatibility but are not in the deployer's tool list.

- [ ] **Step 6: Update COMMON DEPLOYMENT ERRORS section**

Replace with:

```
  =============================================================================
  COMMON DEPLOYMENT ERRORS AND FIXES
  =============================================================================

  compose_up errors:
  - "No docker-compose.yaml found" → check if repo has a docker-compose.yaml
  - "Health check failed" → read the logs from the error response
  - "Git clone failed" → check branch name in PREVIOUS AGENT SUMMARY

  Application errors (from compose_up logs):
  - "ModuleNotFoundError" → dependency missing from requirements.txt
  - "relation does not exist" → models not imported before init_db()
  - "Connection refused" → app not waiting for database (check depends_on)
```

- [ ] **Step 7: Validate YAML syntax**

Run: `cd /home/nuno/Documents/cleaner-druppie-pr84 && python -c "import yaml; yaml.safe_load(open('druppie/agents/definitions/deployer.yaml')); print('OK')"`
Expected: `OK`

- [ ] **Step 8: Commit**

```bash
cd /home/nuno/Documents/cleaner-druppie-pr84
git add druppie/agents/definitions/deployer.yaml
git commit -m "feat(deployer): switch from build+run to compose_up/compose_down workflow"
```

---

## Chunk 3: Docker-in-Docker in Sandbox (vendor submodule)

> **Important:** All changes in this chunk are in the `vendor/open-inspect` git submodule. Commits go to the submodule, then the submodule pointer is updated in the main repo.

### Task 10: Add Docker CE to `Dockerfile.sandbox`

**Files:**
- Modify: `vendor/open-inspect/packages/local-sandbox-manager/Dockerfile.sandbox:33` (add Docker CE install block after system packages)

- [ ] **Step 1: Add Docker CE installation**

After the system packages `apt-get` block (after line 33, before the GitHub CLI install), add:

```dockerfile
# Install Docker CE for Docker-in-Docker (builder verification)
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

- [ ] **Step 2: Verify Dockerfile syntax**

Run: `cd /home/nuno/Documents/cleaner-druppie-pr84/vendor/open-inspect && docker build --check -f packages/local-sandbox-manager/Dockerfile.sandbox . 2>&1 | head -5`

If `--check` is not supported, just verify the file parses:
Run: `python -c "
content = open('packages/local-sandbox-manager/Dockerfile.sandbox').read()
# Basic check: all RUN/FROM/COPY/ENV lines present
assert 'FROM python:3.12-slim-bookworm' in content
assert 'docker-ce' in content
print('OK')
"`

- [ ] **Step 3: Commit in submodule**

```bash
cd /home/nuno/Documents/cleaner-druppie-pr84/vendor/open-inspect
git add packages/local-sandbox-manager/Dockerfile.sandbox
git commit -m "feat(sandbox): add Docker CE for Docker-in-Docker support"
```

---

### Task 11: Add DinD startup phase to `entrypoint.py`

**Files:**
- Modify: `vendor/open-inspect/packages/modal-infra/src/sandbox/entrypoint.py`
  - Add `dockerd_process` attribute to `__init__` (line 49)
  - Add `start_dockerd()` method (new method)
  - Add phase 2.7 call in `run()` (between line 884 and 886)
  - Add DinD cleanup to `shutdown()` (line 922)

- [ ] **Step 1: Add `dockerd_process` attribute**

In `__init__` (after line 51, `self.bridge_process`), add:

```python
        self.dockerd_process: asyncio.subprocess.Process | None = None
```

- [ ] **Step 2: Add `start_dockerd()` method**

Add after `run_setup_script()` method (after line 752), before `_quick_git_fetch`:

```python
    async def start_dockerd(self) -> bool:
        """
        Start Docker daemon for Docker-in-Docker (builder verification).

        Non-fatal: if Docker can't start (e.g. missing SYS_ADMIN cap), log a
        warning and continue — builder falls back to test-only verification.

        Returns:
            True if dockerd started successfully, False otherwise.
        """
        # Check if Docker is installed
        check = await asyncio.create_subprocess_exec(
            "which", "dockerd",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await check.communicate()
        if check.returncode != 0:
            self.log.debug("dockerd.skip", reason="not_installed")
            return False

        self.log.info("dockerd.start")

        try:
            # Create storage directory
            os.makedirs("/var/lib/docker", exist_ok=True)

            # Start dockerd in background, redirect output to /dev/null to
            # prevent pipe buffer from filling up and blocking the daemon
            devnull = open(os.devnull, "w")
            self.dockerd_process = await asyncio.create_subprocess_exec(
                "dockerd",
                "--storage-driver=overlay2",
                stdout=devnull,
                stderr=devnull,
            )

            # Wait for Docker socket (up to 10s)
            socket_path = "/var/run/docker.sock"
            for _ in range(20):
                if os.path.exists(socket_path):
                    # Verify docker info works
                    info = await asyncio.create_subprocess_exec(
                        "docker", "info",
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    await asyncio.wait_for(info.communicate(), timeout=5)
                    if info.returncode == 0:
                        self.log.info("dockerd.ready")
                        return True
                await asyncio.sleep(0.5)

            # Timed out
            self.log.warn("dockerd.timeout", message="Docker socket not ready after 10s")
            if self.dockerd_process.returncode is None:
                self.dockerd_process.terminate()
            self.dockerd_process = None
            return False

        except Exception as e:
            self.log.warn("dockerd.start_error", exc=e)
            self.dockerd_process = None
            return False
```

Note: This method uses `asyncio.create_subprocess_exec` directly (matching the existing code style in `entrypoint.py`). It does NOT use `_run()` which only exists in `docker_manager.py`.

- [ ] **Step 3: Add phase 2.7 to `run()`**

In the `run()` method, after phase 2.5 (setup script, line 884) and before phase 3 (start OpenCode, line 886), add:

```python
            # Phase 2.7: Start Docker daemon (DinD) for builder verification
            dockerd_success: bool | None = None
            if not restored_from_snapshot:
                dockerd_success = await self.start_dockerd()
```

Also update the `sandbox.startup` log event (around line 893) to include `dockerd_success`:

```python
            self.log.info(
                "sandbox.startup",
                repo_owner=self.repo_owner,
                repo_name=self.repo_name,
                restored_from_snapshot=restored_from_snapshot,
                git_sync_success=git_sync_success,
                setup_success=setup_success,
                dockerd_success=dockerd_success,
                opencode_ready=opencode_ready,
                duration_ms=duration_ms,
                outcome="success",
            )
```

- [ ] **Step 4: Add DinD cleanup to `shutdown()`**

In the `shutdown()` method (line 922), add Docker cleanup before the bridge termination:

```python
        # Stop inner Docker containers and daemon (DinD cleanup)
        if self.dockerd_process and self.dockerd_process.returncode is None:
            self.log.info("dockerd.shutdown")
            try:
                # Try to stop any running compose projects
                cleanup = await asyncio.create_subprocess_exec(
                    "docker", "compose", "down", "-v",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await asyncio.wait_for(cleanup.communicate(), timeout=10)
            except Exception:
                pass
            self.dockerd_process.terminate()
            try:
                await asyncio.wait_for(self.dockerd_process.wait(), timeout=5.0)
            except TimeoutError:
                self.dockerd_process.kill()
```

- [ ] **Step 5: Verify syntax**

Run: `cd /home/nuno/Documents/cleaner-druppie-pr84 && python -c "import ast; ast.parse(open('vendor/open-inspect/packages/modal-infra/src/sandbox/entrypoint.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 6: Commit in submodule**

```bash
cd /home/nuno/Documents/cleaner-druppie-pr84/vendor/open-inspect
git add packages/modal-infra/src/sandbox/entrypoint.py
git commit -m "feat(sandbox): add DinD startup phase (2.7) with graceful degradation"
```

---

### Task 12: Update Docker sandbox manager for DinD capabilities

**Files:**
- Modify: `vendor/open-inspect/packages/local-sandbox-manager/src/docker_manager.py:76-95` (security_flags)
- Modify: `vendor/open-inspect/packages/local-sandbox-manager/src/config.py:44` (DOCKER_PIDS_LIMIT)

- [ ] **Step 1: Update `config.py` PID limit**

Change line 44 in `config.py`:

From:
```python
DOCKER_PIDS_LIMIT = int(get("DOCKER_PIDS_LIMIT", "4096"))
```

To:
```python
DOCKER_PIDS_LIMIT = int(get("DOCKER_PIDS_LIMIT", "8192"))
```

- [ ] **Step 2: Update `docker_manager.py` security flags**

Replace the `security_flags` block (lines 76-95) in `create_sandbox()` with:

```python
        # Security and resource flags
        # Note: DinD requires SYS_ADMIN + MKNOD and is incompatible with
        # no-new-privileges (containerd-shim needs privilege escalation).
        # Compensating controls: cap-drop=ALL, network isolation, resource limits.
        security_flags = [
            # Drop ALL capabilities, add back only essentials + DinD
            "--cap-drop=ALL",
            "--cap-add=CHOWN",         # chown files (npm, git)
            "--cap-add=DAC_OVERRIDE",  # bypass file permission checks (root in container)
            "--cap-add=FOWNER",        # change file ownership
            "--cap-add=SETGID",        # set group ID (su, sudo)
            "--cap-add=SETUID",        # set user ID (su, sudo)
            "--cap-add=NET_RAW",       # raw sockets (ping, health checks)
            "--cap-add=NET_BIND_SERVICE",  # bind ports < 1024
            "--cap-add=SYS_CHROOT",    # chroot (some build tools)
            "--cap-add=SYS_ADMIN",     # Docker-in-Docker (cgroups/namespaces)
            "--cap-add=MKNOD",         # Device nodes (DinD)
            "--cgroupns=host",         # Share host cgroup namespace (required for DinD on cgroup v2)
            # Resource limits
            f"--memory={config.DOCKER_MEMORY_LIMIT}",
            f"--cpus={config.DOCKER_CPU_LIMIT}",
            f"--pids-limit={config.DOCKER_PIDS_LIMIT}",
            # Tmpfs for /tmp (faster I/O, auto-cleaned)
            "--tmpfs=/tmp:rw,exec,size=2g",
        ]
```

Key changes:
- Removed `--security-opt=no-new-privileges` (incompatible with DinD)
- Added `--cap-add=SYS_ADMIN` and `--cap-add=MKNOD`
- Added `--cgroupns=host` (required for DinD on cgroup v2 hosts like Debian bookworm)
- Updated docstring to explain the security tradeoff

- [ ] **Step 3: Update module docstring**

Update the module docstring (lines 1-14) to reflect the new security posture:

```python
"""
DockerContainerManager — manages sandbox containers via Docker CLI.

Cross-platform alternative to KataContainerManager. Works on Linux, Windows,
and macOS wherever Docker (or Docker Desktop) is installed.

Security hardening:
  - --cap-drop=ALL + targeted cap-add   (principle of least privilege)
  - SYS_ADMIN + MKNOD for DinD          (builder verification)
  - --cgroupns=host for DinD on cgroup v2
  - no-new-privileges removed            (incompatible with DinD containerd-shim)
  - --memory limit                       (prevents OOM on host)
  - --pids-limit                         (prevents fork bombs)
  - Default seccomp + AppArmor           (Docker builtin profiles)
  - Network isolation                    (sandbox-only network)
  - No --privileged
"""
```

- [ ] **Step 4: Verify syntax**

Run: `cd /home/nuno/Documents/cleaner-druppie-pr84 && python -c "import ast; ast.parse(open('vendor/open-inspect/packages/local-sandbox-manager/src/docker_manager.py').read()); print('OK')" && python -c "import ast; ast.parse(open('vendor/open-inspect/packages/local-sandbox-manager/src/config.py').read()); print('OK')"`
Expected: `OK` twice

- [ ] **Step 5: Commit in submodule**

```bash
cd /home/nuno/Documents/cleaner-druppie-pr84/vendor/open-inspect
git add packages/local-sandbox-manager/src/docker_manager.py packages/local-sandbox-manager/src/config.py
git commit -m "feat(sandbox): add SYS_ADMIN+MKNOD caps and increase PID limit for DinD"
```

---

### Task 13: Update submodule pointer and final commit

**Files:**
- Modify: `vendor/open-inspect` (submodule pointer in main repo)

> **Deferred:** The spec mentions updating `vendor/open-inspect/.../base.py` (Modal image builder) with Docker CE installation. This is deferred because Modal's DinD support needs investigation first. The entrypoint's graceful degradation means the builder works without DinD on Modal — it just skips Docker verification.

- [ ] **Step 1: Update submodule pointer in main repo**

```bash
cd /home/nuno/Documents/cleaner-druppie-pr84
git add vendor/open-inspect
git commit -m "chore: update open-inspect submodule with DinD support"
```

- [ ] **Step 2: Verify all changes are committed**

Run: `cd /home/nuno/Documents/cleaner-druppie-pr84 && git status`
Expected: `nothing to commit, working tree clean`

- [ ] **Step 3: Push submodule first, then main repo**

Push submodule first so the main repo's pointer references a commit that exists on the remote:

```bash
cd /home/nuno/Documents/cleaner-druppie-pr84/vendor/open-inspect
git push origin HEAD
```

Then push the main repo:
```bash
cd /home/nuno/Documents/cleaner-druppie-pr84
git push origin feature/project-coding-standards
```
