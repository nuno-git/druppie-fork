"""FastAPI application for Druppie platform.

Main entry point for the API.
"""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import httpx
import structlog

from druppie.api.routes import agents, approvals, cache, chat, deployments, documentation, evaluations, jobs, mcp_bridge, mcps, model_management, modules, projects, questions, sandbox, sessions, workspace
from druppie.api.errors import register_exception_handlers
from druppie.core.auth import get_auth_service
from druppie.core.config import get_settings
from druppie.agents import Agent
from druppie.core.background_tasks import create_tracked_task, shutdown_background_tasks
from druppie.core.leader_election import try_acquire_leader_lock

logger = structlog.get_logger()


def _recover_zombie_sessions() -> None:
    """Recover sessions that were active when the server stopped.

    On startup, any session with status='active' and running agent runs
    is a zombie — mark it as PAUSED so users can resume via the UI.
    """
    from druppie.db.database import SessionLocal
    from druppie.repositories import ExecutionRepository

    db = SessionLocal()
    try:
        execution_repo = ExecutionRepository(db)
        recovered = execution_repo.recover_zombie_sessions()

        if recovered:
            db.commit()
            logger.warning(
                "zombie_sessions_recovered",
                count=len(recovered),
                session_ids=[str(sid) for sid in recovered],
            )
        else:
            logger.info("no_zombie_sessions_found")
    except Exception as e:
        logger.error("zombie_recovery_failed", error=str(e), exc_info=True)
        db.rollback()
    finally:
        db.close()


def _recover_stuck_job_runs() -> None:
    """Mark job runs that have been RUNNING for too long as FAILED.

    If the server crashed or the job background task was killed,
    RUNNING job runs stay stuck forever with no heartbeat. On startup
    we know no background task is alive, so anyRUNNING run is orphaned.
    """
    from datetime import timedelta
    from druppie.db.database import SessionLocal
    from druppie.repositories import JobRepository
    from druppie.domain.common import JobRunStatus
    from druppie.db.models.base import utcnow

    db = SessionLocal()
    try:
        job_repo = JobRepository(db)
        cutoff = utcnow() - timedelta(minutes=30)
        stuck_runs = job_repo.get_stuck_runs(
            status=JobRunStatus.RUNNING.value,
            older_than=cutoff,
        )
        for run in stuck_runs:
            job_repo.update_job_run_status(
                run.id,
                JobRunStatus.FAILED.value,
                error_message="Server restarted while job was running — marked as failed.",
            )
        if stuck_runs:
            db.commit()
            logger.warning(
                "stuck_job_runs_recovered",
                count=len(stuck_runs),
                run_ids=[str(r.id) for r in stuck_runs],
            )
        else:
            logger.info("no_stuck_job_runs")
    except Exception as e:
        logger.error("stuck_job_run_recovery_failed", error=str(e), exc_info=True)
        db.rollback()
    finally:
        db.close()


def _recover_orphaned_batch_runs() -> None:
    """Mark orphaned test batch runs as error on startup.

    If the server was killed mid-test, the batch run stays "running" in the
    DB forever, blocking all future test runs.  On startup we know no test
    thread is alive, so any "running" batch is an orphan.
    """
    from druppie.db.database import SessionLocal
    from druppie.db.models import TestBatchRun
    from druppie.db.models.base import utcnow

    db = SessionLocal()
    try:
        orphans = db.query(TestBatchRun).filter(TestBatchRun.status == "running").all()
        for batch in orphans:
            batch.status = "error"
            batch.message = "Server restarted while test was running"
            batch.completed_at = utcnow()
        if orphans:
            db.commit()
            logger.warning(
                "orphaned_batch_runs_recovered",
                count=len(orphans),
                batch_ids=[b.id for b in orphans],
            )
        else:
            logger.info("no_orphaned_batch_runs")
    except Exception as e:
        logger.error("orphaned_batch_recovery_failed", error=str(e), exc_info=True)
        db.rollback()
    finally:
        db.close()


def _load_model_override_cache():
    """Populate the resolver's DB override cache from the model_overrides table."""
    from druppie.db.database import SessionLocal
    from druppie.repositories.model_override_repository import ModelOverrideRepository
    from druppie.llm.resolver import set_db_overrides

    db = SessionLocal()
    try:
        repo = ModelOverrideRepository(db)
        overrides = repo.get_agent_overrides()
        override_map = {
            o.target_id: (o.provider, o.model)
            for o in overrides
            if o.target_type == "agent" and o.enabled
        }
        set_db_overrides(override_map)
        if override_map:
            logger.info("model_override_cache_loaded", count=len(override_map))
    except Exception as e:
        logger.warning("model_override_cache_load_failed", error=str(e))
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup
    logger.info("druppie_starting")

    # List available agents
    agents_list = Agent.list_agents()
    logger.info("druppie_initialized", agents=len(agents_list))

    # Recover zombie sessions (active sessions with running agent runs
    # that were interrupted by server shutdown/crash)
    _recover_zombie_sessions()

    # Recover orphaned test batch runs left in "running" state by a crash/restart
    _recover_orphaned_batch_runs()

    _recover_stuck_job_runs()

    # Load DB model overrides into the resolver cache so agents use
    # admin-configured models immediately, not just after the first
    # Model Management page load.
    _load_model_override_cache()

    # Clean up orphaned sandbox Gitea users from previous runs
    from druppie.opencode.gitea_cleanup import cleanup_orphaned_sandbox_users
    await cleanup_orphaned_sandbox_users()

    # Initialize tool registry (discovers MCP tools from servers via tools/list)
    from druppie.core.tool_registry import initialize_tool_registry, get_tool_registry
    try:
        await initialize_tool_registry()
        logger.info("tool_registry_initialized")
    except Exception as e:
        logger.warning("tool_registry_init_failed", error=str(e),
                       hint="MCP servers may not be ready yet. Registry will load builtin tools only.")

    # Retry any MCP servers that failed during startup
    registry = get_tool_registry()
    failed = registry._failed_servers
    if failed:
        create_tracked_task(
            registry._retry_failed_servers(failed),
            name="mcp-registry-retry",
        )

    # Start sandbox watchdog (detects stuck WAITING_SANDBOX tool calls).
    # Leader election: only one replica runs the watchdog to avoid duplicate
    # timeout actions. Uses PostgreSQL advisory lock — no extra infra needed.
    if try_acquire_leader_lock("sandbox-watchdog"):
        from druppie.api.routes.sandbox import sandbox_watchdog_loop
        create_tracked_task(sandbox_watchdog_loop(), name="sandbox-watchdog")
    else:
        logger.info("sandbox_watchdog_skipped", hint="another_replica_is_leader")

    from druppie.db.database import SessionLocal
    from druppie.repositories import JobRepository, SessionRepository, ExecutionRepository
    from druppie.services import JobService
    from druppie.services.job_service import JobScheduler

    def _get_job_service(db):
        return JobService(
            job_repo=JobRepository(db),
            session_repo=SessionRepository(db),
            execution_repo=ExecutionRepository(db),
        )

    job_db = SessionLocal()
    try:
        job_service = _get_job_service(job_db)
        job_service.load_definitions_from_yaml()
        logger.info("job_definitions_loaded")
    except Exception as e:
        job_db.rollback()
        logger.error("job_definitions_load_failed", error=str(e))
    finally:
        job_db.close()

    # JobScheduler: leader election ensures only one replica runs the cron loop.
    # The scheduler itself already uses claim_job_trigger() for DB-level
    # deduplication, but leader election avoids N replicas polling every 60s.
    if try_acquire_leader_lock("job-scheduler"):
        app.state.job_scheduler = JobScheduler(_get_job_service)
        app.state.job_scheduler.start()
    else:
        logger.info("job_scheduler_skipped", hint="another_replica_is_leader")
        app.state.job_scheduler = None

    yield

    if hasattr(app.state, "job_scheduler") and app.state.job_scheduler is not None:
        app.state.job_scheduler.stop()

    # Shutdown — wait for background tasks before exiting
    await shutdown_background_tasks(timeout=30.0)
    logger.info("druppie_stopping")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    # Load configuration
    settings = get_settings()
    # Fail fast on known-bad configs (e.g. partial GitHub App setup) rather
    # than booting a silently-broken service. See Settings.validate_startup.
    settings.validate_startup()

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
    app.include_router(sandbox.router, prefix="/api", tags=["Sandbox"])
    app.include_router(evaluations.router, prefix="/api", tags=["Evaluations"])
    app.include_router(cache.router, prefix="/api", tags=["Cache"])
    app.include_router(modules.router, prefix="/api", tags=["Modules"])
    app.include_router(documentation.router, prefix="/api", tags=["Documentation"])
    app.include_router(jobs.router, prefix="/api/jobs", tags=["Jobs"])
    app.include_router(model_management.router, prefix="/api", tags=["Model Management"])

    @app.on_event("startup")
    async def _load_model_overrides():
        """Load model overrides from DB into resolver cache on startup."""
        try:
            from druppie.db.database import SessionLocal
            from druppie.repositories.model_override_repository import ModelOverrideRepository
            from druppie.llm.resolver import set_db_overrides
            from druppie.core.translation import get_translation_service

            db = SessionLocal()
            try:
                repo = ModelOverrideRepository(db)

                agent_overrides = repo.get_agent_overrides()
                override_map = {
                    o.target_id: (o.provider, o.model)
                    for o in agent_overrides
                    if o.enabled
                }
                set_db_overrides(override_map)

                translation_override = repo.get_translation_override()
                if translation_override and translation_override.enabled:
                    get_translation_service().configure(
                        translation_override.provider,
                        translation_override.model,
                    )

                logger.info(
                    "model_overrides_loaded",
                    agent_overrides=len(override_map),
                    translation_override=translation_override is not None,
                )
            finally:
                db.close()
        except Exception as e:
            logger.warning("model_overrides_load_failed", error=str(e))

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

        # Check LLM provider configuration and profiles
        from druppie.llm.service import get_llm_service, LLMConfigurationError
        llm_healthy = False
        llm_provider = os.getenv("LLM_PROVIDER", "zai")
        llm_profiles = {}
        try:
            llm_service = get_llm_service()
            llm_provider = llm_service.get_provider()
            llm_healthy = True
            llm_profiles = {
                name: [f"{e['provider']}/{e.get('model', 'default')}" for e in entries]
                for name, entries in llm_service.get_profiles().items()
            }
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

        agents = Agent.list_agents()

        return {
            "status": "healthy",
            "version": "2.0.0",
            "environment": os.getenv("ENVIRONMENT", "development"),
            "keycloak": keycloak_healthy,
            "database": database_healthy,
            "llm": llm_healthy,
            "gitea": gitea_healthy,
            "agents_count": len(agents),
            "llm_provider": llm_provider,
            "llm_profiles": llm_profiles,
        }

    @app.get("/")
    async def root():
        """Root endpoint."""
        return {
            "name": "Druppie Platform",
            "version": "2.0.0",
            "docs": "/docs",
        }

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
