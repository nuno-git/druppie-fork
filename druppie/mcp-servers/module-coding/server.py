"""Coding MCP Server — Version Router."""

import asyncio
import logging
import time
from contextlib import asynccontextmanager

from module_router import create_module_app, run_module
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

_logger = logging.getLogger("coding-mcp")

WATCHDOG_INTERVAL = 60  # seconds between health checks


async def cleanup_session(request):
    session_id = request.path_params["session_id"]
    from v1.tools import _destroy_all_for_session
    await _destroy_all_for_session(session_id)
    return JSONResponse({"status": "ok", "session_id": session_id})


async def cleanup_scope(request):
    session_id = request.path_params["session_id"]
    git_scope = request.path_params["git_scope"]
    from v1.tools import _destroy_container
    await _destroy_container(session_id, git_scope)
    return JSONResponse({"status": "ok", "session_id": session_id, "git_scope": git_scope})


async def sandbox_status(request):
    from v1.tools import sandbox_containers, _is_container_running
    containers = []
    stale_count = 0
    for key, entry in sandbox_containers.items():
        container_id = entry.get("container_id", entry["container_name"])
        running = await _is_container_running(container_id)
        if not running:
            stale_count += 1
        containers.append({
            "key": key,
            "container_name": entry["container_name"],
            "session_id": entry["session_id"],
            "git_scope": entry["git_scope"],
            "created_at": entry["created_at"],
            "running": running,
        })
    return JSONResponse({
        "active_containers": containers,
        "count": len(containers),
        "stale_count": stale_count,
    })


async def warmup_pool(request):
    return JSONResponse({"status": "noop", "message": "Warm pool not implemented"})


_management_routes = [
    Route("/sandbox/cleanup/{session_id}", cleanup_session, methods=["POST"]),
    Route("/sandbox/cleanup/{session_id}/{git_scope}", cleanup_scope, methods=["POST"]),
    Route("/sandbox/status", sandbox_status, methods=["GET"]),
    Route("/sandbox/warmup", warmup_pool, methods=["POST"]),
]

async def _sandbox_watchdog():
    """Periodic background task that monitors sandbox container health.

    Detects dead containers and removes stale entries so the next tool call
    gets a fresh container instead of hitting a dead one. Also removes
    containers that have been idle beyond CONTAINER_MAX_IDLE.
    """
    from v1.tools import (
        sandbox_containers,
        _is_container_running,
        _get_container_death_reason,
        _destroy_container,
        SANDBOX_MAX_IDLE,
    )

    while True:
        await asyncio.sleep(WATCHDOG_INTERVAL)
        try:
            now = time.time()
            keys_to_check = list(sandbox_containers.keys())
            dead_count = 0
            stale_count = 0

            for key in keys_to_check:
                entry = sandbox_containers.get(key)
                if not entry:
                    continue

                container_name = entry.get("container_name", "")
                session_id = entry.get("session_id", "")
                git_scope = entry.get("git_scope", "")

                running = await _is_container_running(container_name)
                if not running:
                    reason = await _get_container_death_reason(container_name)
                    _logger.warning(
                        "Watchdog: dead container %s (session=%s, scope=%s): %s",
                        container_name, session_id, git_scope, reason,
                    )
                    try:
                        await _destroy_container(session_id, git_scope)
                    except Exception:
                        sandbox_containers.pop(key, None)
                    dead_count += 1
                    continue

                # Idle reap: a sandbox whose pod is Running but which has seen
                # no tool activity for > SANDBOX_MAX_IDLE is a wedged/abandoned
                # session pinning cluster capacity. created_at is the fallback
                # for entries that don't track last_activity (e.g. docker mode).
                last = entry.get("last_activity") or entry.get("created_at") or now
                idle = now - last
                if idle > SANDBOX_MAX_IDLE:
                    _logger.info(
                        "Watchdog: reaping idle sandbox %s (idle=%.0fs, max=%ss, session=%s)",
                        container_name, idle, SANDBOX_MAX_IDLE, session_id,
                    )
                    try:
                        await _destroy_container(session_id, git_scope)
                    except Exception:
                        sandbox_containers.pop(key, None)
                    stale_count += 1

            if dead_count or stale_count:
                _logger.info(
                    "Watchdog cycle: removed %d dead, %d stale containers",
                    dead_count, stale_count,
                )

            # Reap untracked leaked SandboxClaims (k8s). The loop above only
            # handles tracked sandboxes; orphaned claims (restart, or a recreate
            # before the destroy-before-recreate fix) accumulate and pin cluster
            # capacity. cheap list/delete, gated by an age threshold inside.
            try:
                from v1.tools import _cleanup_orphan_containers as _sweep, SANDBOX_MODE
                if SANDBOX_MODE == "k8s":
                    orphans = await _sweep()
                    if orphans:
                        _logger.info(
                            "Watchdog: reaped %d orphan k8s SandboxClaim(s)", orphans,
                        )
            except Exception as exc:
                _logger.warning("Watchdog k8s orphan sweep failed: %s", exc)
        except Exception as exc:
            _logger.warning("Watchdog error: %s", exc)


app = create_module_app("coding", default_port=9001)

_base_lifespan = app.router.lifespan_context

@asynccontextmanager
async def _extended_lifespan(app_ref):
    from v1.tools import _cleanup_orphan_containers, SANDBOX_MAX_IDLE
    try:
        cleaned = await _cleanup_orphan_containers()
        _logger.info("Startup: cleaned %d orphan sandbox containers", cleaned)
    except Exception as exc:
        _logger.warning("Startup orphan cleanup failed: %s", exc)

    watchdog_task = asyncio.create_task(_sandbox_watchdog())
    _logger.info("Sandbox watchdog started (interval=%ds, max_idle=%ss)", WATCHDOG_INTERVAL, SANDBOX_MAX_IDLE)

    async with _base_lifespan(app_ref):
        try:
            yield
        finally:
            watchdog_task.cancel()
            try:
                await watchdog_task
            except asyncio.CancelledError:
                pass
            _logger.info("Sandbox watchdog stopped")

app.router.lifespan_context = _extended_lifespan

app.router.routes = [
    Mount("/management", routes=_management_routes),
    *app.router.routes,
]

if __name__ == "__main__":
    import os
    import uvicorn
    port = int(os.getenv("MCP_PORT", "9001"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
