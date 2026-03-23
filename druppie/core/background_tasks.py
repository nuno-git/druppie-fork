"""Background task tracking for fire-and-forget asyncio tasks.

Solves two problems with bare asyncio.create_task():
1. Unhandled exceptions are silently swallowed (only a WARNING log on GC)
2. No graceful shutdown — untracked tasks get killed mid-operation

Usage:
    from druppie.core.background_tasks import create_tracked_task, run_session_task

    # Track a raw coroutine:
    create_tracked_task(some_coro(), name="my-task")

    # Run orchestrator work with DB lifecycle + error handling:
    async def my_work(ctx):
        await ctx.orchestrator.resume_paused_session(session_id)

    create_session_task(
        session_id,
        run_session_task(session_id, my_work, "resume"),
        name=f"resume-{session_id}",
    )
"""

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any
from uuid import UUID

import structlog

logger = structlog.get_logger()

# Module-level set: prevents GC of running tasks and enables shutdown enumeration.
_background_tasks: set[asyncio.Task] = set()

# Per-session guard: maps session_id → running Task.
# Prevents concurrent background tasks for the same session (e.g. rapid
# stop → resume → stop → resume spawning two tasks that both run agents).
_active_session_tasks: dict[UUID, asyncio.Task] = {}


def _on_task_done(task: asyncio.Task) -> None:
    """Log unhandled exceptions from background tasks at ERROR level."""
    _background_tasks.discard(task)

    if task.cancelled():
        logger.warning("background_task_cancelled", task_name=task.get_name())
        return

    exc = task.exception()
    if exc is not None:
        logger.error(
            "background_task_unhandled_exception",
            task_name=task.get_name(),
            error=f"{type(exc).__name__}: {exc}",
            exc_info=(type(exc), exc, exc.__traceback__),
        )


def create_tracked_task(
    coro: Coroutine[Any, Any, Any],
    *,
    name: str | None = None,
) -> asyncio.Task:
    """Create an asyncio task with proper tracking and error logging.

    The task is stored in a module-level set to:
    - Prevent garbage collection (which would silently discard exceptions)
    - Enable enumeration for graceful shutdown
    """
    task = asyncio.create_task(coro, name=name)
    _background_tasks.add(task)
    task.add_done_callback(_on_task_done)
    return task


class SessionTaskConflict(Exception):
    """Raised when a background task is already running for a session."""
    pass


def is_session_task_running(session_id: UUID) -> bool:
    """Check if a background task is already running for a session."""
    task = _active_session_tasks.get(session_id)
    return task is not None and not task.done()


def create_session_task(
    session_id: UUID,
    coro: Coroutine[Any, Any, Any],
    *,
    name: str | None = None,
) -> asyncio.Task:
    """Create a tracked task for a session, ensuring only one runs at a time.

    This MUST be called synchronously from the endpoint handler (no await
    between the call site and this function) so the check+add is atomic
    in the single-threaded event loop.

    Raises:
        SessionTaskConflict: If a task is already running for this session.
    """
    existing = _active_session_tasks.get(session_id)
    if existing is not None and not existing.done():
        logger.warning(
            "session_task_conflict",
            session_id=str(session_id),
            existing_task=existing.get_name(),
            requested_task=name,
        )
        raise SessionTaskConflict(
            f"A background task is already running for session {session_id}"
        )

    task = create_tracked_task(coro, name=name)
    _active_session_tasks[session_id] = task

    def _cleanup(_t: asyncio.Task) -> None:
        _active_session_tasks.pop(session_id, None)

    task.add_done_callback(_cleanup)
    return task


async def shutdown_background_tasks(timeout: float = 30.0) -> None:
    """Wait for running background tasks to finish, then cancel stragglers.

    Called from the application lifespan shutdown handler.
    """
    if not _background_tasks:
        logger.info("shutdown_no_background_tasks")
        return

    task_names = [t.get_name() for t in _background_tasks]
    logger.info(
        "shutdown_waiting_for_background_tasks",
        count=len(_background_tasks),
        tasks=task_names,
    )

    # Give tasks time to finish their current operation
    done, pending = await asyncio.wait(
        _background_tasks.copy(),
        timeout=timeout,
    )

    if not pending:
        logger.info("shutdown_all_tasks_completed", completed=len(done))
        return

    # Cancel remaining tasks
    pending_names = [t.get_name() for t in pending]
    logger.warning(
        "shutdown_cancelling_remaining_tasks",
        count=len(pending),
        tasks=pending_names,
    )
    for task in pending:
        task.cancel()

    # Wait briefly for cancellation to propagate
    await asyncio.wait(pending, timeout=5.0)
    logger.info("shutdown_complete")


# =============================================================================
# Session task helper — DB lifecycle + error handling for background work
# =============================================================================


class SessionTaskContext:
    """Context passed to session task callables.

    Provides access to the DB session, repositories, and orchestrator
    so task functions don't need to create their own.
    """

    __slots__ = ("db", "session_repo", "execution_repo", "project_repo", "question_repo", "orchestrator")

    def __init__(self, db, session_repo, execution_repo, project_repo, question_repo, orchestrator):
        self.db = db
        self.session_repo = session_repo
        self.execution_repo = execution_repo
        self.project_repo = project_repo
        self.question_repo = question_repo
        self.orchestrator = orchestrator


async def run_session_task(
    session_id: UUID,
    task_fn: Callable[[SessionTaskContext], Coroutine[Any, Any, None]],
    task_name: str,
) -> None:
    """Run an async task with a fresh DB session, repos, and orchestrator.

    Handles the full lifecycle:
    1. Create DB session + repositories + orchestrator
    2. Call task_fn(ctx)
    3. On error: rollback, mark session FAILED, commit
    4. Always: close DB session

    Usage:
        async def my_work(ctx: SessionTaskContext):
            await ctx.orchestrator.process_message(...)

        create_tracked_task(
            run_session_task(session_id, my_work, "orchestrator"),
            name=f"orchestrator-{session_id}",
        )
    """
    from druppie.db.database import SessionLocal
    from druppie.domain.common import SessionStatus
    from druppie.repositories import (
        SessionRepository,
        ExecutionRepository,
        ProjectRepository,
        QuestionRepository,
    )
    from druppie.execution import Orchestrator

    db = SessionLocal()
    try:
        session_repo = SessionRepository(db)
        execution_repo = ExecutionRepository(db)
        project_repo = ProjectRepository(db)
        question_repo = QuestionRepository(db)

        orchestrator = Orchestrator(
            session_repo=session_repo,
            execution_repo=execution_repo,
            project_repo=project_repo,
            question_repo=question_repo,
        )

        ctx = SessionTaskContext(
            db=db,
            session_repo=session_repo,
            execution_repo=execution_repo,
            project_repo=project_repo,
            question_repo=question_repo,
            orchestrator=orchestrator,
        )

        await task_fn(ctx)

    except asyncio.CancelledError:
        # Graceful shutdown (e.g. uvicorn reload) — mark session as paused
        # so zombie recovery on restart can handle it cleanly instead of
        # leaving the session stuck in 'active' status.
        logger.warning(
            f"{task_name}_cancelled",
            session_id=str(session_id),
        )
        try:
            db.rollback()
            SessionRepository(db).update_status(
                session_id,
                SessionStatus.PAUSED,
            )
            db.commit()
        except Exception:
            pass  # Best-effort — process is dying
        raise

    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}"
        logger.error(
            f"{task_name}_error",
            session_id=str(session_id),
            error=error_msg,
            exc_info=True,
        )
        try:
            db.rollback()
            SessionRepository(db).update_status(
                session_id,
                SessionStatus.FAILED,
                error_message=error_msg[:2000],
            )
            db.commit()
        except Exception as update_error:
            logger.error(
                f"failed_to_update_session_status_after_{task_name}",
                session_id=str(session_id),
                error=str(update_error),
            )
    finally:
        db.close()
