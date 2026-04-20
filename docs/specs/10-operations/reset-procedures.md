# Reset Procedures

Druppie has four reset levels, progressively more destructive.

## Level 1 — reset-db (preserves users)

```bash
docker compose --profile reset-db run --rm reset-db
```

Drops application tables:
- `projects, sessions, agent_runs, messages, tool_calls, llm_calls, approvals, questions, sandbox_sessions, project_dependencies, tool_call_normalizations, llm_retries`.

Preserves: user tables (`users, user_roles, user_tokens`), evaluation tables (`benchmark_runs, evaluation_results, test_runs, test_batch_runs, test_assertion_results, test_run_tags`).

When to use: accumulated dev session clutter, want a clean slate but keep evaluation history and users.

After: backend reconnects to the cleaned DB. No restart needed.

## Level 2 — reset-hard (full stack, re-init users)

```bash
docker compose --profile dev down
docker compose --profile infra --profile reset-hard run --rm reset-hard
docker compose --profile dev up -d --build
```

Steps (in `scripts/reset-hard.sh`):
1. Stop all services, remove their named volumes.
2. Bring infrastructure back up (databases, Keycloak, Gitea, MCPs).
3. Wait for healthchecks.
4. Re-run `setup_keycloak.py` + `setup_gitea.py` — recreates realm, users, OAuth clients, admin token.
5. Print next-step banner.

After that, run dev profile up with `--build` so MCP server images refresh against the fresh volumes.

When to use: Keycloak/Gitea got weird, DB schema is stale, you want to recreate the baseline test users.

## Level 3 — nuke (destroy everything + rebuild)

```bash
docker compose --profile nuke run --rm nuke
```

By default `START_AFTER=true` — after destruction, it runs `docker compose --profile dev --profile init up -d --build` automatically.

Destroys:
- All containers (every profile).
- All named volumes.
- Locally-built images (preserves upstream like `postgres:15-alpine`).

When to use: "I don't know what's broken, start over." The CI-equivalent — matches a fresh clone state.

Set `START_AFTER=false` to leave the stack down:
```bash
START_AFTER=false docker compose --profile nuke run --rm nuke
```

## Level 4 — reset-cache (sandbox dep cache only)

```bash
docker compose --profile reset-cache run --rm reset-cache
```

Wipes `druppie_sandbox_dep_cache`. First sandbox runs after this will be slow as they repopulate.

When to use: cache poisoning suspected, or OSV scan flagged a cached package.

## Decision tree

```
Is the whole app broken?
├─ Yes → nuke
└─ No
    │
    Are users/realm broken?
    ├─ Yes → reset-hard
    └─ No
        │
        Is the DB too cluttered for dev?
        ├─ Yes → reset-db
        └─ No
            │
            Sandbox builds acting weird?
            ├─ Yes → reset-cache
            └─ No → specific container restart
```

## Partial restarts

Sometimes you just need to restart one service:

```bash
docker compose restart druppie-backend-dev
docker compose restart module-coding
docker compose up -d --build module-docker    # rebuild + restart
```

No state is lost — volumes persist.

## Database-only manual operations

If you need to fix one row:
```bash
docker compose exec druppie-db psql -U druppie -d druppie
```

Or use Adminer at http://localhost:8081 with server `druppie-db`, user `druppie`, password from `.env`.

## Keycloak-only manual operations

Admin console at http://localhost:8180/admin. Log in with `KEYCLOAK_ADMIN`/`_PASSWORD`. Changes here do NOT survive a `reset-hard` — edit `iac/realm.yaml` + `iac/users.yaml` for persistent changes.

## Warning about images

After `reset-hard`, MCP server images are NOT rebuilt (they're pulled from local cache). If you've edited MCP code and want it reflected, add `--build`:

```bash
docker compose --profile dev up -d --build
```

The `dev` profile mounts `druppie/` into the backend but NOT into MCP containers, so MCP code changes always need a rebuild.

## Production reset procedure

For production deployments, these profiles may not apply verbatim. The principle is: same order (app tables → realm → volumes → everything), but orchestrated via the production infrastructure (Terraform, managed PostgreSQL, etc.).

Don't use `nuke` in production.
