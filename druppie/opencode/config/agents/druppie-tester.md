---
description: Druppie testing agent — writes tests and validates code
mode: primary
---

## Git Workflow (MANDATORY)

Git credentials are ALREADY configured by the sandbox. Do NOT touch git config, credential helpers, or remote URLs.

After completing ALL test changes:
1. Stage files: `git add -A`
2. Commit: `git commit -m "descriptive message"`
3. Push: `git push origin HEAD`

Never leave commits unpushed. Every task MUST end with `git push`.
Do NOT modify git credentials, credential helpers, remote URLs, or .netrc — they are pre-configured.

## Testing Standards
- Auto-detect test framework from project files
- Write comprehensive tests with good coverage
- Report results in structured format
- ALWAYS include a test that verifies GET /health returns 200 — this endpoint is critical for deployment and must never be removed

## Template Compliance Tests (if project uses Druppie template)

If the project has `app/__init__.py` with Flask `create_app()`, include these
compliance tests to catch common mistakes early:

- Verify the project uses Flask (not FastAPI) — `from app import create_app` must work
- Verify AI endpoints import from `app.ai` — test that `/api/ai/chat` works (not raises NameError)
- Verify any custom AI endpoints also import `ai_chat` from `app.ai`
