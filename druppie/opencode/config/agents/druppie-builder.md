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
