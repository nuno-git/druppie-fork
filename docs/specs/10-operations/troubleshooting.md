# Troubleshooting

Common failure modes and their fixes.

## Stack won't start

### `druppie-init` keeps running
Check logs:
```bash
docker compose logs druppie-init
```

Likely causes:
- Keycloak not ready — the init retries 10× over 50s. If Keycloak was super slow, extend retries or wait and `docker compose up -d` again (init is idempotent unless marker is cleared).
- Gitea not ready — same pattern.
- LLM provider keys missing — init doesn't check, but later agent runs will fail.

### Backend health check fails
```bash
docker compose logs druppie-backend-dev
```

- "Database connection refused" — `druppie-db` isn't healthy. Check `docker compose logs druppie-db`.
- "Could not load agents" — YAML syntax error in `druppie/agents/definitions/*.yaml`. Fix and restart.
- "Keycloak unreachable" — check Keycloak health, `KEYCLOAK_URL` env var.

## Agent runs fail repeatedly

### "Max iterations reached" on builder
Usually means the sandbox can't make tests pass. Check:
- The test_builder generated sane tests (read them in the session timeline).
- The builder's `execute_coding_task` task prompt had enough context.
- The sandbox control plane is healthy (`docker compose logs sandbox-control-plane`).

### Architect can't find ArchiMate models
`module-archimate` mounts `/models` — may be empty on fresh installs. Add model XML files to the mounted path or accept that `archimate:list_models` returns empty.

### Business analyst writes English, not Dutch
Verify the BA YAML's system_prompt has the Dutch instruction intact. Check if LLM provider is routing to a model that ignores the instruction (some cheap models drop instructions). Switch profile or model.

## Approval won't resolve

### Click Approve, nothing happens
Check:
- Browser console for 403/500.
- Backend logs for the `/api/approvals/{id}/approve` call.
- Does the user have the required role? `/api/admin/table/users/{id}` to inspect roles.
- Is the session still PAUSED_APPROVAL? Could have been resolved already by someone else.

### Approved but agent doesn't continue
Phase 1 (DB update) succeeded but phase 2 (resume task) failed. Typical cause: backend crashed between. Fix: click Resume on the session (sessions.md → PAUSED_APPROVAL → ACTIVE via the retry code path).

## Sandbox never completes

### Status stuck on WAITING_SANDBOX
Check `docker ps` for the sandbox container. If absent:
- Container died before completing.
- Watchdog will mark FAILED after `SANDBOX_TIMEOUT_MINUTES` (default 30).

If running but not progressing:
- `docker logs <sandbox-container>` — what is OpenCode doing?
- `docker compose logs sandbox-control-plane` — are events flowing?

Manual cleanup:
```bash
docker stop <sandbox-container>
docker rm <sandbox-container>
# Then in DB:
UPDATE tool_calls SET status = 'failed', error_message = 'manual kill'
WHERE id = '<uuid>';
UPDATE agent_runs SET status = 'failed'
WHERE id = (SELECT agent_run_id FROM tool_calls WHERE id = '<uuid>');
```

Or let the watchdog handle it.

### Webhook signature mismatch
Seen as 401 in the backend logs when the sandbox control plane POSTs completion. Causes:
- `webhook_secret` mismatch between what Druppie stored and what the control plane has.
- Clock skew (HMAC includes timestamp in the body).

Fix: kill the sandbox, let the user retry.

## Docker tools fail

### "No ports available"
`module-docker` allocates from 9100-9199. If all taken by leaked containers:
```bash
docker ps --format '{{.Names}}  {{.Ports}}' | grep -E '910[0-9]|91[1-9][0-9]'
```

Stop orphans:
```bash
docker stop $(docker ps -q --filter label=druppie.session_id=<uuid>)
```

### `compose_up` health check failing
The project's `/health` endpoint must return 200 with `{"status": "ok"}`. Common reasons it fails:
- Missing `/health` endpoint (check `app/__init__.py` in the project).
- Backend depends on postgres which isn't ready (compose's `depends_on` with `condition: service_healthy` should handle this; if absent, deploy is flaky).
- App takes > `health_timeout` to start (increase via the tool argument).

## LLM errors

### Consistent 5xx from one provider
The proxy retries and fails over. If ALL providers fail:
- Check each provider's API status page.
- Try `LLM_FORCE_PROVIDER=ollama` with a local model for quick diagnostic.

### "Context length exceeded"
Agent prompts grew too long. Fixes:
- Reset session and start fresh.
- For a specific agent, shorten its YAML `system_prompt`.
- Lower `max_iterations` so the message history stays shorter.
- Implement better history truncation in `druppie/agents/message_history.py`.

### Tool call arguments invalid
LLM produced a malformed call. The argument normaliser handles common cases ("null" → None). For uncommon:
- Check `tool_call_normalizations` for audit rows.
- If a tool's schema is too complex, simplify it and restart (the LLM will be more accurate on simpler shapes).

## UI issues

### "Unauthorized" on every request
- Token expired and refresh failed. Hard-reload (`Ctrl-Shift-R`).
- Keycloak down. Check `/api/status`.

### Dashboard shows "Loading..." forever
- Backend down. Check `docker compose logs druppie-backend-dev`.
- Network issue. Check `localhost:8100/health` directly.

### Session timeline out of order
Shouldn't happen — repository sorts by `created_at`. If observed, it's a bug in `_build_timeline`; check clock skew on the host (unlikely inside containers but possible on VMs).

## Gitea issues

### "Authorization required" on git push from sandbox
The `GITEA_TOKEN` expired or wasn't propagated. Re-run `setup_gitea.py`:
```bash
docker compose --profile init up -d druppie-init
```

### Project delete leaves Gitea repo
`ProjectService.delete()` calls Gitea asynchronously and logs warnings on failure. Clean up manually in the Gitea UI or via API.

## Evaluation quirks

### Batch stuck in `running`
`TestBatchRun.status = running` with no ongoing threads. Startup recovery handles this — restart the backend.

Manually:
```sql
UPDATE test_batch_runs SET status='failed', message='manual cleanup'
WHERE id='<batch_uuid>' AND status='running';
```

### Judge returns inconsistent verdicts
- Use Judge Eval mode (`expected: true/false` in check) to calibrate.
- Switch judge to a stronger model via `testing/profiles/judges.yaml`.
- Narrow context filter (less noise → more consistent verdicts).

## Performance

### DB queries slow
Likely missing indexes. Check the admin DB browser or `pg_stat_statements`. Add indexes in the relevant `druppie/db/models/*.py` and do a `reset-db`.

### Frontend sluggish
- Mermaid + Recharts are heavy. Code-splitting by route helps (default in Vite).
- React Query poll intervals can be tuned — excessive polling (every 1 s) loads the backend.

## Last-resort

```bash
docker compose --profile nuke run --rm nuke
```

Starts over. Takes ~5 min. All session data, projects, and Gitea repos gone. Use when:
- You don't care about local state.
- Nothing else has worked.
- You want to reproduce a fresh-install bug.

Before nuking: pull any important code to a separate clone; dumped DB if you need to inspect it later.
