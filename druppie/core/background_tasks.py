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

Concurrency is guarded at the database level via SELECT ... FOR UPDATE.
create_session_task() acquires a row lock on the session and checks that
no other task is active before spawning. This works across replicas.
"""

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any
from uuid import UUID

import structlog

from druppie.llm.base import clean_llm_error

logger = structlog.get_logger()

# Module-level set: prevents GC of running tasks and enables shutdown enumeration.
_background_tasks: set[asyncio.Task] = set()


class SessionTaskConflict(Exception):
    """Raised when a background task is already running for a session."""
    pass


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


# Status that indicates a background task is currently in flight for this
# session. The guard claims this status under the row lock before spawning, so
# a concurrent request observes it and is rejected. Paused states are NOT here:
# resuming a paused session is exactly what most callers do.
_TASK_ACTIVE_STATES = frozenset({"active"})


def create_session_task(
    session_id: UUID,
    coro: Coroutine[Any, Any, Any],
    *,
    name: str | None = None,
    skip_lock: bool = False,
) -> asyncio.Task:
    """Create a tracked task for a session with a DB-level concurrency guard.

    Opens a short-lived DB session, locks the session row with SELECT FOR UPDATE,
    verifies no other task is active, and atomically claims the session by
    setting its status to ACTIVE before releasing the lock. If the session is
    already ACTIVE, raises SessionTaskConflict. Claiming the status under the
    lock (rather than letting the spawned task set it later) closes the window
    where two requests could both pass the guard and spawn duplicate tasks.

    Args:
        session_id: Session to guard.
        coro: Coroutine to run as a background task.
        name: Task name for logging.
        skip_lock: Skip the DB guard. Use ONLY when the caller already holds
            a DB lock (e.g. lock_for_retry / lock_for_resume) or for brand-new
            sessions that no other request can reference yet.

    Raises:
        SessionTaskConflict: If a task is already running for this session.
    """
    if not skip_lock:
        from druppie.db.database import SessionLocal
        from druppie.db.models import Session as SessionModel
        from druppie.domain.common import SessionStatus

        db = SessionLocal()
        try:
            session = (
                db.query(SessionModel)
                .filter_by(id=session_id)
                .with_for_update()
                .first()
            )
            if session is not None and session.status in _TASK_ACTIVE_STATES:
                logger.warning(
                    "session_task_conflict",
                    session_id=str(session_id),
                    session_status=session.status,
                    requested_task=name,
                )
                raise SessionTaskConflict(
                    f"A background task is already running for session {session_id} "
                    f"(status={session.status})"
                )
            # No active task — claim the session by marking it ACTIVE within the
            # same locked transaction, then release the lock. This is what the
            # spawned orchestrator would set anyway, done atomically here so a
            # concurrent request sees ACTIVE and is rejected (no double-spawn).
            if session is not None:
                session.status = SessionStatus.ACTIVE.value
            db.commit()  # Persist the ACTIVE claim and release the row lock.
        except SessionTaskConflict:
            db.rollback()
            raise
        except Exception:
            db.rollback()
            logger.warning(
                "session_task_guard_failed",
                session_id=str(session_id),
                requested_task=name,
            )
            # If the guard itself fails (e.g. DB connection issue), still
            # allow the task to proceed — the guard is a safety net, not a
            # gate. Worst case: a duplicate task runs, which the orchestrator
            # handles gracefully via session status checks.
        finally:
            db.close()

    return create_tracked_task(coro, name=name)


def cancel_session_task(session_id: UUID | str) -> int:
    """Forcefully cancel in-flight background task(s) for a session.

    The cooperative cancel (DB PAUSED flag + SessionPauseToken) only fires when
    the orchestrator reaches its next checkpoint — which never happens if it is
    wedged in a hanging tool call (a sandbox/git/MCP await with no hard
    timeout). This locates the session's tracked task(s) by name and cancels
    them, so the wedged ``await`` raises CancelledError and ``run_session_task``'s
    handler cleans up (agent_runs -> PAUSED_USER, session -> PAUSED). Returns the
    number of tasks scheduled for cancellation.

    Safe when no task exists (returns 0). Cancellation propagates on the next
    event-loop tick; the cleanup runs asynchronously in ``run_session_task``.
    """
    sid = str(session_id)
    targets = [
        t for t in list(_background_tasks)
        if not t.done() and sid in (t.get_name() or "")
    ]
    for t in targets:
        t.cancel()
    return len(targets)


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

    __slots__ = ("db", "session_repo", "execution_repo", "project_repo", "question_repo", "job_repo", "attachment_repo", "orchestrator")

    def __init__(self, db, session_repo, execution_repo, project_repo, question_repo, job_repo, attachment_repo, orchestrator):
        self.db = db
        self.session_repo = session_repo
        self.execution_repo = execution_repo
        self.project_repo = project_repo
        self.question_repo = question_repo
        self.job_repo = job_repo
        self.attachment_repo = attachment_repo
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
        AttachmentRepository,
    )
    from druppie.execution import Orchestrator

    db = SessionLocal()
    try:
        session_repo = SessionRepository(db)
        execution_repo = ExecutionRepository(db)
        project_repo = ProjectRepository(db)
        question_repo = QuestionRepository(db)
        from druppie.repositories import JobRepository
        job_repo = JobRepository(db)
        attachment_repo = AttachmentRepository(db)

        orchestrator = Orchestrator(
            session_repo=session_repo,
            execution_repo=execution_repo,
            project_repo=project_repo,
            question_repo=question_repo,
            job_repo=job_repo,
            attachment_repo=attachment_repo,
        )

        ctx = SessionTaskContext(
            db=db,
            session_repo=session_repo,
            execution_repo=execution_repo,
            project_repo=project_repo,
            question_repo=question_repo,
            job_repo=job_repo,
            attachment_repo=attachment_repo,
            orchestrator=orchestrator,
        )

        await task_fn(ctx)

    except asyncio.CancelledError:
        try:
            db.rollback()
            from druppie.db.database import SessionLocal as _SL
            from druppie.domain.common import AgentRunStatus
            from druppie.repositories import SessionRepository as _SR
            from druppie.repositories import ExecutionRepository as _ER
            from druppie.db.models.agent_run import AgentRun as _AR
            _db = _SL()
            try:
                _db.query(_AR).filter(
                    _AR.session_id == session_id,
                    _AR.status == AgentRunStatus.RUNNING.value,
                ).update({"status": AgentRunStatus.PAUSED_USER.value}, synchronize_session=False)
                _SR(_db).update_status(session_id, SessionStatus.PAUSED)
                _db.commit()
            finally:
                _db.close()
            logger.info("session_cancelled_clean", session_id=str(session_id))
        except Exception as cleanup_err:
            logger.error("session_cancel_cleanup_failed", session_id=str(session_id), error=str(cleanup_err))

    except Exception as e:
        raw_error = f"{type(e).__name__}: {e}"
        error_msg = clean_llm_error(raw_error)
        logger.error(
            f"{task_name}_error",
            session_id=str(session_id),
            error=raw_error,
            exc_info=True,
        )
        try:
            db.rollback()
            SessionRepository(db).update_status(
                session_id,
                SessionStatus.FAILED,
                error_message=error_msg,
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
