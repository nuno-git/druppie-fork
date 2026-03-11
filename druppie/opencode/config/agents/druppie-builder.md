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

### Backend (Flask + PostgreSQL)

- `app/` — main Python package (Flask)
- `app/__init__.py` — Flask app factory with `create_app()`, serves SPA frontend, `/health` endpoint
- `app/database.py` — SQLAlchemy engine, `Base`, `get_db()`, `init_db()`
- `app/models.py` — add your SQLAlchemy models here (imports are pre-wired)
- `app/config.py` — settings from environment variables
- `app/routes.py` — Flask Blueprint at `/api/*` with AI endpoints built-in
- `app/ai.py` — DeepInfra AI helper (see AI section below)
- `requirements.txt` — base dependencies (flask, sqlalchemy, openai, gunicorn)

### Frontend (Vite + React + shadcn/ui)

- `frontend/` — React 19 + TypeScript + Tailwind CSS + shadcn/ui
- `frontend/src/App.tsx` — main app component
- `frontend/src/components/ui/` — pre-installed shadcn components (Button, Card, Input)
- `frontend/src/lib/utils.ts` — `cn()` utility for Tailwind class merging
- `frontend/src/lib/ai.ts` — frontend AI helper (calls backend `/api/ai/*`)
- `frontend/src/index.css` — Tailwind + shadcn CSS variables (light/dark theme)
- `frontend/components.json` — shadcn config (new-york style)

### Infrastructure

- `Dockerfile` — multi-stage: Node builds frontend → Python serves everything with gunicorn
- `docker-compose.yaml` — app + PostgreSQL database
- `/health` endpoint is used by the deployment system — do NOT remove it

### Rules

- **Use the `app/` package** — do NOT create separate `backend/`, `src/`, or other top-level packages
- **Extend existing files** — add models to `app/models.py`, add routes to `app/routes.py`
- **Add Python dependencies** to `requirements.txt` — do NOT rewrite the file from scratch
- **Add npm dependencies** with `npm install <pkg>` in `frontend/` — or edit `package.json`
- **Do NOT modify** `Dockerfile` or `docker-compose.yaml` unless you change the entrypoint or add services
- **Use PostgreSQL types** — `sqlalchemy.dialects.postgresql.UUID` for UUIDs
- **`/health` endpoint must stay** — the deployment system uses it to verify the app is running
- **Frontend uses `@/` alias** — import components as `@/components/ui/button`, `@/lib/utils`, etc.
- **shadcn components** — add new ones by creating files in `frontend/src/components/ui/`. Follow the pattern in `button.tsx` and `card.tsx`. Do NOT run `npx shadcn` — write the component files directly.

## AI Integration (DeepInfra)

This project has DeepInfra AI built in. The API key is injected at deploy time
via the `DEEPINFRA_API_KEY` environment variable — you never hardcode it.

### Backend (Python) — `app/ai.py`

Two ready-to-use functions:

```python
from app.ai import ai_chat, ocr_extract

# LLM chat completion
answer = ai_chat("What is the capital of France?")
answer = ai_chat("Summarize this...", system="You are a summarizer.")

# OCR: extract text from an image URL
text = ocr_extract("https://example.com/receipt.png")
```

Models (defined in `app/ai.py`, change as needed):
- `AI_MODEL` = `meta-llama/Llama-4-Maverick-17B-128E-Instruct-FP8` — general LLM
- `OCR_MODEL` = `PaddlePaddle/PaddleOCR-VL-0.9B` — OCR vision model

### Backend API endpoints (already in `app/routes.py`)

```
POST /api/ai/chat   {"prompt": "...", "system": "..."}  → {"answer": "..."}
POST /api/ai/ocr    {"image_url": "https://..."}        → {"text": "..."}
```

### Frontend (TypeScript) — Vercel AI SDK + helper

The Vercel AI SDK (`ai` + `@ai-sdk/deepinfra`) is pre-installed. For
server-side calls (API routes, server actions), use the SDK directly:

```typescript
import { createDeepInfra } from "@ai-sdk/deepinfra";
import { generateText } from "ai";

const deepinfra = createDeepInfra({
  // Key comes from backend — don't use in frontend directly
  apiKey: "from-env",
});

// Chat with LLM
const { text } = await generateText({
  model: deepinfra("meta-llama/Llama-4-Maverick-17B-128E-Instruct-FP8"),
  messages: [{ role: "user", content: "Hello!" }],
});

// OCR from image URL
const { text: ocrText } = await generateText({
  maxOutputTokens: 4092,
  model: deepinfra("PaddlePaddle/PaddleOCR-VL-0.9B"),
  messages: [{
    role: "user",
    content: [{ type: "image", image: "https://example.com/receipt.png" }],
  }],
});
```

For frontend components, call the backend proxy endpoints instead (key stays
server-side):

```typescript
import { aiChat, aiOcr } from "@/lib/ai";

// Chat
const answer = await aiChat("What is the capital of France?");

// OCR
const text = await aiOcr("https://example.com/receipt.png");
```

### When to use AI

- If the user's app needs chat, Q&A, summarization → use `ai_chat()` / `aiChat()`
- If the user's app needs OCR, document scanning, receipt reading → use `ocr_extract()` / `aiOcr()`
- Always call AI through the backend API endpoints (keeps the key server-side)
- Do NOT hardcode API keys anywhere

## Test Compliance

Tests written by the test agent are already in this repo. They are the source of truth.

1. After implementing your code, run the tests:
   - Python: `pip install -r requirements.txt && pytest -v`
   - Node.js: `cd frontend && npm install && npm test`
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
