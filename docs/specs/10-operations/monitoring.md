# Monitoring

What to watch when Druppie is running.

## Health endpoints

| Service | URL | Interval |
|---------|-----|----------|
| Backend liveness | `GET /health` | 30 s |
| Backend readiness | `GET /health/ready` | 30 s |
| Backend status | `GET /api/status` | 60 s |
| Keycloak | `GET /health/ready` (port 8180) | 15 s |
| Gitea | `GET /api/healthz` | 15 s |
| Postgres (druppie-db / keycloak-db / gitea-db) | `pg_isready` | 5 s |
| MCP coding | `GET http://module-coding:9001/health` | 30 s |
| MCP docker | `GET :9002/health` | 30 s |
| MCP filesearch | `:9004/health` | 30 s |
| MCP web | `:9005/health` | 30 s |
| MCP archimate | `:9006/health` | 30 s |
| MCP registry | `:9007/health` | 30 s |
| Sandbox control plane | `:8787/health` | 30 s |

All return 200 if healthy; 503 or timeout on degradation.

## What `/api/status` returns

Rich probe including:
- Keycloak reachability.
- Database connectivity (`SELECT 1`).
- LLM config present (at least one provider's API key).
- Gitea reachability.
- Agent count (YAML load success).

Used by the frontend's Dashboard status tile, refreshed every 30 s.

## Logs

### Structured vs unstructured
Druppie backend logs via Python `logging` — plain text, line-based. No JSON logging layer today. Helpful patterns to grep:

- `RUNNING` / `COMPLETED` / `FAILED` for session/agent run transitions.
- `ToolCall` / `MCPHttp` for MCP dispatches.
- `orchestrator` / `tool_executor` for core flow.
- Tracebacks on exceptions.

### Important log sources

| Container | What to watch |
|-----------|---------------|
| druppie-backend-dev | Orchestrator, tool exec, approval/HITL flow |
| sandbox-control-plane | Session lifecycle, LLM proxy errors, provider health |
| sandbox-manager | Docker spawn errors, OSV scan results |
| module-coding | Git errors, file-op blocks, Mermaid validation failures |
| module-docker | Port allocation, compose_up failures |
| keycloak | Login failures, token decode errors |
| gitea | Repo creation/deletion, OAuth errors |

### Tailing

```bash
docker compose logs -f druppie-backend-dev | grep -E "ERROR|WARN|Failed"
```

## Metrics (manual)

No Prometheus. For ad-hoc monitoring:

### Session rate
```sql
SELECT COUNT(*) FROM sessions WHERE created_at > NOW() - INTERVAL '1 hour';
```

### Agent run failures
```sql
SELECT agent_id, COUNT(*) FROM agent_runs
WHERE status = 'failed' AND created_at > NOW() - INTERVAL '24 hours'
GROUP BY agent_id ORDER BY 2 DESC;
```

### LLM token burn
```sql
SELECT provider, model, SUM(total_tokens) FROM llm_calls
WHERE created_at > NOW() - INTERVAL '24 hours'
GROUP BY 1, 2 ORDER BY 3 DESC;
```

### Stuck sandbox calls
```sql
SELECT id, tool_name, agent_run_id, sandbox_waiting_at FROM tool_calls
WHERE status = 'waiting_sandbox'
ORDER BY sandbox_waiting_at;
```

The watchdog catches these automatically after 30 min.

## Alerting

Recommended alerts (none configured today):

- `/health` 5xx for >2 min.
- `/health/ready` 503 for >5 min.
- Any MCP `/health` down for >5 min.
- Postgres connection failures.
- Keycloak `/health/ready` failing.
- LLM proxy consecutive errors > 10 in 5 min (available at control plane).
- Sandbox watchdog firing > N/hour (indicates systemic failures).

## Capacity

Rule of thumb for a single-host deployment:
- 1 active user: trivial.
- 10 concurrent sessions: fine on 16 GB / 8 CPU host.
- 100 concurrent sessions: move to multi-host + shared DB; sandbox path should go to Modal.

The bottleneck is usually LLM latency + sandbox CPU, not Druppie's own resources.

## Useful admin views

- `/admin/database` — generic table browser. Inspect agent_runs, tool_calls, llm_calls for a specific session.
- `/admin/tests/analytics` — aggregate evaluation data.
- `/tools/infrastructure` — live Docker container view.
- `/tools/mcp` — call any MCP tool for smoke testing.

## When the backend is unresponsive

```bash
docker compose exec druppie-db psql -U druppie -d druppie -c "SELECT count(*) FROM sessions WHERE status='active';"
```

If this hangs, DB is saturated. If it returns instantly but backend is slow, backend process issue (logs, stack trace, maybe hung LLM call).

## LLM cost tracking

No cost dashboard today. The frontend shows `total_tokens * 0.40/1M` as a proxy. Real cost per provider varies significantly — adjust `src/utils/tokenUtils.js:calculateCost` if you want accurate per-provider pricing.
