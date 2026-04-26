# Project Template

`druppie/templates/project/` — stub project structure Druppie copies when creating a new STANDALONE project. This is what user apps look like at `t=0`.

## Structure

```
druppie/templates/project/
├── Dockerfile                     # multi-stage (Python backend + React frontend build + nginx)
├── docker-compose.yaml            # app + postgres services
├── requirements.txt               # Python backend deps
├── .gitignore
├── app/                           # FastAPI backend
│   ├── __init__.py                # creates FastAPI app + /health endpoint
│   ├── config.py                  # env-driven settings
│   ├── database.py                # SQLAlchemy session
│   ├── models.py                  # SQLAlchemy models
│   └── routes.py                  # REST endpoints
└── frontend/
    ├── index.html
    ├── vite.config.ts
    ├── tsconfig.json
    ├── tailwind.config.js
    ├── postcss.config.js
    ├── components.json            # shadcn/ui config
    ├── package.json               # React, Vite, TypeScript, shadcn/ui, @testing-library, vitest
    └── src/
        ├── main.tsx
        ├── App.tsx
        ├── vite-env.d.ts
        ├── index.css
        ├── lib/utils.ts
        └── components/ui/         # shadcn/ui primitives (button, card, input, …)
```

## `/health` endpoint — critical

`app/__init__.py` defines:

```python
@app.get("/health")
def health():
    return {"status": "ok"}
```

This endpoint is **required by the deployer**. `module-docker:compose_up` polls it after bringing the stack up; if it doesn't respond with 200 within the timeout, the deploy is considered failed and rolled back.

Multiple agent prompts explicitly reinforce:
- `builder_planner.yaml`: "PRESERVE /health endpoint — deployment depends on it."
- `test_builder.yaml`: "include a test that GET /health returns 200 with status 'ok'."

## TypeScript vs Druppie itself

The template uses TypeScript + shadcn/ui — a richer stack than Druppie's own JSX frontend. This is intentional: user apps are the showcase and should use best-in-class tooling. Druppie's UI is pragmatic and will migrate when there's a reason.

## Backend stack

- FastAPI
- SQLAlchemy 2.0
- PostgreSQL via `postgres:15-alpine` in the compose file
- `/health` endpoint + a small set of demo routes

## Frontend stack

- React 18 + Vite + TypeScript
- Tailwind CSS
- shadcn/ui component library
- Vitest + @testing-library for tests

## docker-compose.yaml

Two services: `app` (FastAPI) and `postgres` (database). App depends on postgres healthcheck. Ports exposed for external access.

## How the template is used

When the router + business_analyst + architect decide to create a new project:
1. `set_intent(intent="create_project", project_name="todo-app")` creates a Gitea repo and `druppie_new_workspace/<session_id>/` workspace.
2. The workspace is **not pre-populated** from this template today — the builder_planner writes the starting code following the template's patterns, and the builder sandbox produces the actual files.
3. Historical note: earlier versions copied the template directly; current approach is "template as reference" for the agents.

The template thus functions as an executable spec: agents reading it see the expected shape.

## Evolving the template

Changes here affect every newly created project. Minimum bar:
- `/health` endpoint must remain.
- Compose file must remain runnable standalone (`docker compose up`).
- Test framework must remain auto-detectable (pytest for Python, vitest for frontend).
- `tests/` directory must exist.

PRs changing the template should include a working build in CI.
