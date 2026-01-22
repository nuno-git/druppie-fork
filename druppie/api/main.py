"""FastAPI application for Druppie platform.

Main entry point for the API.
"""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
import httpx
import structlog

from druppie.api.routes import chat, sessions, approvals, mcps, projects, questions, workspace
from druppie.api.websocket import handle_websocket
from druppie.core.loop import get_main_loop
from druppie.core.auth import get_auth_service
from druppie.agents import Agent
from druppie.workflows import Workflow

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup
    logger.info("druppie_starting")

    # Initialize main loop and list available agents/workflows
    get_main_loop()
    agents = Agent.list_agents()
    workflows = Workflow.list_workflows()
    logger.info(
        "main_loop_initialized",
        agents=len(agents),
        workflows=len(workflows),
    )

    yield

    # Shutdown
    logger.info("druppie_stopping")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Druppie Platform",
        description="AI-powered governance platform with MCP tool permissions",
        version="2.0.0",
        lifespan=lifespan,
    )

    # CORS middleware
    # Default origins include:
    # - 5173: Vite dev server default
    # - 5273: Full stack docker-compose frontend
    # - 3000: Alternative dev port
    cors_origins = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://localhost:5273,http://localhost:3000").split(",")
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
    app.include_router(approvals.router, prefix="/api", tags=["Approvals"])
    app.include_router(mcps.router, prefix="/api", tags=["MCPs"])
    app.include_router(projects.router, prefix="/api", tags=["Projects"])
    app.include_router(questions.router, prefix="/api/questions", tags=["Questions"])
    app.include_router(workspace.router, prefix="/api", tags=["Workspace"])

    @app.get("/health")
    async def health_check():
        """Health check endpoint."""
        return {"status": "healthy", "version": "2.0.0"}

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

        # Check LLM provider configuration
        llm_provider = os.getenv("LLM_PROVIDER", "auto")
        llm_healthy = False
        if llm_provider == "mock":
            llm_healthy = True
        elif llm_provider in ("zai", "auto"):
            # Check if API key is configured
            zai_key = os.getenv("ZAI_API_KEY", "")
            llm_healthy = bool(zai_key)

        # Check Gitea health
        gitea_healthy = False
        gitea_url = os.getenv("GITEA_INTERNAL_URL", os.getenv("GITEA_URL", "http://gitea:3000"))
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{gitea_url}/api/v1/version")
                gitea_healthy = response.status_code == 200
        except Exception as e:
            logger.warning("gitea_health_check_failed", error=str(e))

        return {
            "status": "healthy",
            "version": "2.0.0",
            "environment": os.getenv("ENVIRONMENT", "development"),
            "keycloak": keycloak_healthy,
            "database": database_healthy,
            "llm": llm_healthy,
            "gitea": gitea_healthy,
            "agents": Agent.list_agents(),
            "workflows": Workflow.list_workflows(),
            "llm_provider": llm_provider,
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
