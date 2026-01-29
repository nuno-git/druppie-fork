"""FastAPI application for Druppie platform.

Main entry point for the API.
"""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
import httpx
import structlog

from druppie.api.routes import agents, approvals, chat, deployments, mcp_bridge, mcps, projects, questions, sessions, workspace
from druppie.api.websocket import handle_websocket
from druppie.api.errors import register_exception_handlers
from druppie.core.auth import get_auth_service
from druppie.core.config import get_settings
from druppie.agents import Agent
from druppie.workflows import Workflow

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup
    logger.info("druppie_starting")

    # List available agents and workflows
    agents_list = Agent.list_agents()
    workflows_list = Workflow.list_workflows()
    logger.info(
        "druppie_initialized",
        agents=len(agents_list),
        workflows=len(workflows_list),
    )

    yield

    # Shutdown
    logger.info("druppie_stopping")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    # Load configuration
    settings = get_settings()

    app = FastAPI(
        title="Druppie Platform",
        description="AI-powered governance platform with MCP tool permissions",
        version="2.0.0",
        lifespan=lifespan,
    )

    # Register standardized error handlers
    register_exception_handlers(app)

    # CORS middleware using centralized config
    cors_origins = settings.api.cors_origins_list
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include routers
    app.include_router(chat.router, prefix="/api", tags=["Chat"])
    app.include_router(sessions.router, prefix="/api", tags=["Sessions"])
    app.include_router(approvals.router, prefix="/api/approvals", tags=["Approvals"])
    app.include_router(questions.router, prefix="/api/questions", tags=["Questions"])
    app.include_router(projects.router, prefix="/api", tags=["Projects"])
    app.include_router(deployments.router, prefix="/api", tags=["Deployments"])
    app.include_router(workspace.router, prefix="/api", tags=["Workspace"])
    app.include_router(agents.router, prefix="/api", tags=["Agents"])
    app.include_router(mcps.router, prefix="/api", tags=["MCPs"])
    app.include_router(mcp_bridge.router, prefix="/api/mcp", tags=["MCP Bridge"])

    @app.get("/health")
    async def health_check():
        """Health check endpoint."""
        return {"status": "healthy", "version": "2.0.0"}

    @app.get("/health/ready")
    async def readiness_check():
        """Readiness check endpoint.

        Checks if the application is ready to serve traffic:
        - Database is connected
        - Agents are loaded
        """
        from fastapi.responses import JSONResponse

        # Check database connection
        database_ready = False
        try:
            from druppie.api.deps import engine
            from sqlalchemy import text
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
                database_ready = True
        except Exception as e:
            logger.warning("readiness_database_check_failed", error=str(e))

        # Check if agents are loaded
        agents = Agent.list_agents()
        agents_ready = bool(agents)

        is_ready = database_ready and agents_ready

        response_data = {
            "ready": is_ready,
            "database": database_ready,
            "agents_loaded": agents_ready,
        }

        if is_ready:
            return response_data
        else:
            return JSONResponse(status_code=503, content=response_data)

    @app.get("/api/status")
    async def api_status():
        """API status endpoint for frontend dashboard.

        Checks health of all dependent services:
        - Keycloak: Authentication service
        - Database: PostgreSQL/SQLite database
        - LLM: Language model provider
        - Gitea: Git repository service
        """
        # Check Keycloak health
        auth_service = get_auth_service()
        keycloak_healthy = auth_service.is_keycloak_available()

        # Check database health
        database_healthy = False
        try:
            from druppie.api.deps import engine
            from sqlalchemy import text
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
                database_healthy = True
        except Exception as e:
            logger.warning("database_health_check_failed", error=str(e))

        # Check LLM provider configuration - get actual resolved provider
        from druppie.llm.service import get_llm_service, LLMConfigurationError
        llm_provider_config = os.getenv("LLM_PROVIDER", "auto")
        llm_healthy = False
        llm_provider = llm_provider_config
        llm_model = None
        try:
            llm_service = get_llm_service()
            llm_provider = llm_service.get_provider()  # Resolves 'auto' to actual provider
            llm_healthy = True
            # Get model name for transparency
            if llm_provider == "deepinfra":
                llm_model = os.getenv("DEEPINFRA_MODEL", "Qwen/Qwen3-Next-80B-A3B-Instruct")
            elif llm_provider == "zai":
                llm_model = os.getenv("ZAI_MODEL", "GLM-4.7")
            elif llm_provider == "mock":
                llm_model = "mock"
        except LLMConfigurationError:
            llm_healthy = False

        # Check Gitea health
        gitea_healthy = False
        gitea_url = os.getenv("GITEA_INTERNAL_URL", os.getenv("GITEA_URL", "http://gitea:3000"))
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{gitea_url}/api/v1/version")
                gitea_healthy = response.status_code == 200
        except Exception as e:
            logger.warning("gitea_health_check_failed", error=str(e))

        # Return status counts instead of internal names to avoid information disclosure
        agents = Agent.list_agents()
        workflows = Workflow.list_workflows()

        return {
            "status": "healthy",
            "version": "2.0.0",
            "environment": os.getenv("ENVIRONMENT", "development"),
            "keycloak": keycloak_healthy,
            "database": database_healthy,
            "llm": llm_healthy,
            "gitea": gitea_healthy,
            "agents_count": len(agents),
            "workflows_count": len(workflows),
            "llm_provider": llm_provider,
            "llm_model": llm_model,
        }

    @app.get("/")
    async def root():
        """Root endpoint."""
        return {
            "name": "Druppie Platform",
            "version": "2.0.0",
            "docs": "/docs",
        }

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        """WebSocket endpoint for real-time updates."""
        await handle_websocket(websocket)

    @app.websocket("/ws/session/{session_id}")
    async def websocket_session_endpoint(websocket: WebSocket, session_id: str):
        """WebSocket endpoint for session-specific updates."""
        await handle_websocket(websocket, session_id)

    return app


# Create the default app instance
app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "druppie.api.main:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
        reload=os.getenv("RELOAD", "false").lower() == "true",
    )
