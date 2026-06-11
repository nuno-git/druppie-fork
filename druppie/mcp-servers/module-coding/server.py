"""Coding MCP Server — Version Router."""

import logging
from contextlib import asynccontextmanager

from module_router import create_module_app, run_module
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

_logger = logging.getLogger("coding-mcp")


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

app = create_module_app("coding", default_port=9001)

_base_lifespan = app.router.lifespan_context

@asynccontextmanager
async def _extended_lifespan(app_ref):
    from v1.tools import _cleanup_orphan_containers
    try:
        cleaned = await _cleanup_orphan_containers()
        _logger.info("Startup: cleaned %d orphan sandbox containers", cleaned)
    except Exception as exc:
        _logger.warning("Startup orphan cleanup failed: %s", exc)

    async with _base_lifespan(app_ref):
        yield

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
