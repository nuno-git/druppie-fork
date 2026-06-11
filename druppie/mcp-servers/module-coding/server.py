"""Coding MCP Server — Version Router."""

from module_router import create_module_app, run_module
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route


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
    from v1.tools import sandbox_containers
    containers = [
        {
            "key": key,
            "container_name": entry["container_name"],
            "session_id": entry["session_id"],
            "git_scope": entry["git_scope"],
            "created_at": entry["created_at"],
        }
        for key, entry in sandbox_containers.items()
    ]
    return JSONResponse({
        "active_containers": containers,
        "count": len(containers),
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
app.router.routes = [
    Mount("/management", routes=_management_routes),
    *app.router.routes,
]

if __name__ == "__main__":
    import os
    import uvicorn
    port = int(os.getenv("MCP_PORT", "9001"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
