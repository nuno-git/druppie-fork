"""Background task tracking for fire-and-forget asyncio tasks.

Solves two problems with bare asyncio.create_task():
1. Unhandled exceptions are silently swallowed (only a WARNING log on GC)
2. No graceful shutdown — untracked tasks get killed mid-operation

Usage:
    from druppie.core.background_tasks import create_tracked_task

    create_tracked_task(
        _run_orchestrator_background(...),
        name=f"orchestrator-{session_id}",
    )
"""

import asyncio
from collections.abc import Coroutine
from typing import Any

import structlog

logger = structlog.get_logger()

# Module-level set: prevents GC of running tasks and enables shutdown enumeration.
_background_tasks: set[asyncio.Task] = set()


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
