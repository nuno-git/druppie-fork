"""Postgres LISTEN/NOTIFY for cross-replica session cancellation.

When a user clicks Stop, the cancel endpoint writes PAUSED to the DB and
calls ``notify_session_cancel(session_id)``. Every replica receives the
NOTIFY via a dedicated connection; the replica running the agent task
finds it in ``SessionPauseToken._active_tokens`` and calls
``task.cancel()`` to interrupt the in-flight LLM call (<10ms latency).

SQLite does not support LISTEN/NOTIFY — all functions are no-ops when
the database is SQLite.
"""

import asyncio
import logging
import select
import threading
import time

import structlog

logger = structlog.get_logger()

_CHANNEL = "session_cancel"
_listener_thread: threading.Thread | None = None
_listener_stop = threading.Event()
_event_loop: asyncio.AbstractEventLoop | None = None


def _is_postgres() -> bool:
    from druppie.db.database import DATABASE_URL
    return "postgresql" in DATABASE_URL or "postgres" in DATABASE_URL


def start_cancel_listener() -> None:
    global _listener_thread, _event_loop
    if not _is_postgres():
        logger.info("listen_notify_skipped", reason="not_postgres")
        return
    _event_loop = asyncio.get_event_loop()
    _listener_stop.clear()
    _listener_thread = threading.Thread(
        target=_listen_worker,
        daemon=True,
        name="pg-listen-session-cancel",
    )
    _listener_thread.start()
    logger.info("listen_notify_started", channel=_CHANNEL)


def stop_cancel_listener() -> None:
    global _listener_thread
    if _listener_thread is None:
        return
    _listener_stop.set()
    _listener_thread.join(timeout=5)
    _listener_thread = None
    logger.info("listen_notify_stopped")


def notify_session_cancel(session_id) -> None:
    if not _is_postgres():
        return
    from sqlalchemy import text
    from druppie.db.database import SessionLocal
    db = SessionLocal()
    try:
        db.execute(
            text("SELECT pg_notify(:channel, :payload)"),
            {"channel": _CHANNEL, "payload": str(session_id)},
        )
        db.commit()
    except Exception as e:
        logger.warning("notify_failed", session_id=str(session_id), error=str(e))
    finally:
        db.close()


def _listen_worker() -> None:
    from druppie.db.database import DATABASE_URL

    while not _listener_stop.is_set():
        conn = None
        try:
            import psycopg2
            conn = psycopg2.connect(DATABASE_URL)
            conn.set_isolation_level(0)  # AUTOCOMMIT
            cursor = conn.cursor()
            cursor.execute(f"LISTEN {_CHANNEL}")
            cursor.close()
            logger.info("listen_connected", channel=_CHANNEL)

            while not _listener_stop.is_set():
                select.select([conn], [], [], 1.0)
                if _listener_stop.is_set():
                    break
                conn.poll()
                while conn.notifies:
                    notify = conn.notifies.pop(0)
                    _dispatch_cancel(notify.payload)
        except Exception as e:
            if not _listener_stop.is_set():
                logger.warning("listen_error", error=str(e))
                time.sleep(2)
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass


def _dispatch_cancel(session_id: str) -> None:
    if _event_loop is None or _event_loop.is_closed():
        return
    _event_loop.call_soon_threadsafe(_do_cancel, session_id)


def _do_cancel(session_id: str) -> None:
    from druppie.agent_runtime.types import SessionPauseToken
    found = SessionPauseToken.cancel_session(session_id)
    if found:
        logger.info("listen_cancel_dispatched", session_id=session_id)
