"""PostgreSQL advisory lock based leader election for multi-replica deployments.

Ensures only one backend replica runs singleton background tasks (job scheduler,
sandbox watchdog). Uses `pg_try_advisory_lock` which is non-blocking and
session-scoped: the lock is automatically released when the DB connection closes
or the session ends.

How it works:
    1. On startup, try to acquire an advisory lock with a well-known integer ID.
    2. If acquired → this replica is the leader. Run the singleton task.
    3. If not acquired → another replica is the leader. Skip the task.
    4. Periodically renew the lock (advisory locks are session-scoped, so
       keeping the DB connection alive is sufficient).

Why advisory locks:
    - No extra infrastructure (no Redis, no ZooKeeper)
    - Non-blocking: `pg_try_advisory_lock` returns immediately
    - Automatic cleanup: lock dies with the DB connection
    - Works with any PostgreSQL (CloudNativePG, RDS, etc.)

Usage:
    from druppie.core.leader_election import try_acquire_leader_lock

    if try_acquire_leader_lock("job-scheduler"):
        # This replica is the leader — start the scheduler
        scheduler.start()
    else:
        logger.info("another_replica_is_leader", task="job-scheduler")
"""

import hashlib
import struct

import structlog

logger = structlog.get_logger()


def _name_to_lock_id(name: str) -> int:
    """Convert a human-readable name to a PostgreSQL advisory lock integer.

    Uses MD5 hash truncated to a signed 64-bit int. PostgreSQL advisory locks
    accept int4 (-2^31 to 2^31-1) for single-argument form. We use the
    two-argument form (int4, int4) to get 64 bits of entropy.

    Returns:
        Tuple of (lock_id_part1, lock_id_part2) — both int4 compatible.
    """
    digest = hashlib.md5(name.encode()).digest()
    part1 = struct.unpack_from("<i", digest, 0)[0]
    part2 = struct.unpack_from("<i", digest, 4)[0]
    return part1, part2


def try_acquire_leader_lock(task_name: str) -> bool:
    """Try to acquire a PostgreSQL advisory lock for a named task.

    Non-blocking. Returns True if this replica acquired the lock (is the leader),
    False if another replica holds it.

    The lock is held on a dedicated DB connection stored in the module-level
    `_lock_connections` dict. The connection stays open for the lifetime of
    the process — when the process dies, the lock is automatically released.

    Args:
        task_name: Human-readable name (e.g. "job-scheduler", "sandbox-watchdog").

    Returns:
        True if leader (lock acquired), False otherwise.
    """
    from sqlalchemy import text

    part1, part2 = _name_to_lock_id(task_name)

    # Open a dedicated connection that stays alive for the lifetime of the lock.
    # We use the raw engine connection (not SessionLocal) because advisory locks
    # are connection-scoped — they release when the connection closes.
    from druppie.db.database import engine

    try:
        conn = engine.connect()
        result = conn.execute(
            text("SELECT pg_try_advisory_lock(:p1, :p2)"),
            {"p1": part1, "p2": part2},
        )
        acquired = result.scalar()

        if acquired:
            # Store the connection so it stays open (keeps the lock held).
            # When the process exits, the connection closes and the lock releases.
            _lock_connections[task_name] = conn
            logger.info(
                "leader_lock_acquired",
                task=task_name,
                hint="this_replica_is_leader",
            )
            return True
        else:
            conn.close()
            logger.info(
                "leader_lock_not_acquired",
                task=task_name,
                hint="another_replica_is_leader",
            )
            return False
    except Exception as e:
        logger.warning(
            "leader_lock_failed",
            task=task_name,
            error=str(e),
            hint="proceeding_without_leader_election",
        )
        # If we can't reach the DB, don't block startup.
        # The singleton tasks have their own idempotency guards.
        return False


# Module-level storage for lock-holding connections.
# Key: task_name, Value: open SQLAlchemy connection.
# These connections must stay open for the lock to remain held.
_lock_connections: dict[str, object] = {}
