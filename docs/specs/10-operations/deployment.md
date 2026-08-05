# Deployment

Druppie today ships as a Docker Compose stack. There is no production Terraform for Druppie itself yet (the `background-agents/terraform/` provisions only the sandbox system).

## Production-shape requirements

To run Druppie in an environment beyond a developer laptop:

### Secrets
Override defaults:
- `INTERNAL_API_KEY` — the app refuses to start with the default value if `ENVIRONMENT=production`.
- `SANDBOX_API_SECRET` — same guard.
- `KEYCLOAK_ADMIN_PASSWORD`.
- `GITEA_ADMIN_PASSWORD`.
- `DRUPPIE_DB_PASSWORD` / `KEYCLOAK_DB_PASSWORD` / `GITEA_DB_PASSWORD`.
- `KEYCLOAK_CLIENT_SECRET` / `GITEA_CLIENT_SECRET` / `GITEA_SECRET_KEY` — regenerated via init if empty.

### Domain + TLS
Front the stack with nginx / Traefik / Cloudflare for:
- TLS termination.
- Routing: `druppie.example.com` → frontend:5273, `api.druppie.example.com` → backend:8100, `auth.druppie.example.com` → keycloak:8180, `git.druppie.example.com` → gitea:3100.
- WebSocket upgrade for any live channels (currently the app is polling-only, but MCP streams may change that).

### External Postgres
Replace the compose-provided `druppie-db` with a managed PostgreSQL. Set `DATABASE_URL=postgresql://...` and remove the compose DB service.

### Keycloak production mode
- Run `start` instead of `start-dev`.
- Set `KC_HOSTNAME`, `KC_HTTPS_CERTIFICATE_FILE`, etc.
- Consider Keycloak clustering.

### LLM keys
Production keys should have:
- Usage quotas matched to expected volume.
- Monitoring alerts on unusual spend.
- Rotation schedule.

### Sandbox path
- Option A: continue with `local-sandbox-manager` on a dedicated Docker host. Simpler. Host becomes a pet.
- Option B: deploy `background-agents/terraform/` (Cloudflare + Modal). Fully serverless. Requires adapting Druppie's `SANDBOX_CONTROL_PLANE_URL` to the CF Workers URL.

### Observability
- Aggregate logs: ship container stdout to ELK / Loki / Cloud logging.
- Metrics: add a Prometheus exporter to the backend (none today).
- Alerting: on health endpoint failures, DB connection errors, sandbox watchdog firings.

## CI/CD

Today's repo has one workflow: `.github/workflows/sync-main-to-colab-dev.yml` — on merge to `main`, sync back to `colab-dev`. Given `main` is deprecated, this will change.

For production:
- Build + push Druppie images to a container registry on merge to `colab-dev`.
- Deploy to staging → smoke test → promote to production.
- Image tags: `druppie-backend:<commit-sha>`, `druppie-frontend:<sha>`, etc.

None of this is wired. It's a roadmap item.

## Backups

- **Postgres** — `pg_dump` on a schedule. Restore: `pg_restore`.
- **Gitea** — volume snapshot + Gitea's own dump tool.
- **Keycloak** — realm export (`kc.sh export`) or DB snapshot.
- **Dep cache** — optional; rebuilt on first sandbox runs after loss.

## Upgrade path

Druppie has no migrations — schema changes require `reset-db` which drops data. This is fine for dev, unacceptable for production. Production deployments will need:
- Alembic (or similar) migrations.
- Backward-compatible upgrades (no destructive column changes within a minor version).

Until then, production Druppie deployments are pinned to one version and replaced wholesale on upgrade.

## Scaling

Single instance assumptions:
- Session locks are in-process (`druppie/core/background_tasks.py:_session_locks`) — not shared.
- Zombie recovery runs at startup — assumes the crashed instance is the same one restarting.
- WebSocket (if ever added) would be process-local.

To scale horizontally:
- Move session locks to Redis.
- Use distributed coordination for zombie recovery.
- Sticky sessions or a pub/sub layer for cross-instance notifications.

Not prioritised — the scale today is one backend per deployment.

## Health monitoring

Standard checks to wire into external monitoring:
- `GET /health` — liveness.
- `GET /health/ready` — readiness.
- `GET /api/status` — detailed.
- For each MCP: `GET http://module-<name>:<port>/health`.
- Sandbox control plane: `GET http://sandbox-control-plane:8787/health`.

## Staging

The compose setup is adequate for staging. Stand up a second copy with different ports, different secrets, and a separate database. Use it for:
- Pre-merge smoke testing.
- Agent prompt iteration without touching prod data.
- Backup restore drills.
