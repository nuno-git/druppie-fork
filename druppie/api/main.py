"""FastAPI application for Druppie platform.

Main entry point for the API.
"""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
import structlog

from druppie.api.routes import chat, sessions, approvals, mcps, projects, questions
from druppie.api.websocket import handle_websocket
from druppie.core.loop import get_main_loop
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
    cors_origins = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://localhost:3000").split(",")
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

    @app.get("/health")
    async def health_check():
        """Health check endpoint."""
        return {"status": "healthy", "version": "2.0.0"}

    @app.get("/api/status")
    async def api_status():
        """API status endpoint for frontend dashboard."""
        return {
            "status": "healthy",
            "version": "2.0.0",
            "agents": Agent.list_agents(),
            "workflows": Workflow.list_workflows(),
            "llm_provider": os.getenv("LLM_PROVIDER", "auto"),
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
