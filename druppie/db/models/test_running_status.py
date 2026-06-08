"""Tracks which tests are currently executing within a batch run.

One row per actively-running test.  Rows are inserted when a test starts
and deleted when it finishes, so the table is always small and represents
only real-time state.  Fully stateless — survives restarts and works
across multiple backend instances.
"""

from sqlalchemy import Column, DateTime, ForeignKey, String

from .base import Base, utcnow


class TestRunningStatus(Base):
    """One row per test currently executing in a batch run."""

    __tablename__ = "test_running_status"

    id = Column(String(36), primary_key=True)
    run_id = Column(
        String(36), ForeignKey("test_batch_runs.id"), nullable=False, index=True
    )
    test_name = Column(String(255), nullable=False)
    started_at = Column(DateTime(timezone=True), default=utcnow)
