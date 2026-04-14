"""Test batch run model — tracks batch-level execution status.

Replaces the in-memory _test_run_status dict that was used to track
background test run progress.  Polling endpoints query this table
instead of an in-memory dict, so state survives process restarts.
"""

from sqlalchemy import Column, DateTime, Integer, String, Text

from .base import Base, utcnow


class TestBatchRun(Base):
    """Batch-level test run status (one per "Run" click)."""

    __tablename__ = "test_batch_runs"

    id = Column(String(36), primary_key=True)  # batch_id (UUID string)
    status = Column(String(50), nullable=False, default="running")
    message = Column(Text, nullable=True)
    current_test = Column(String(255), nullable=True)
    total_tests = Column(Integer, default=0)
    started_at = Column(DateTime(timezone=True), default=utcnow)
    completed_at = Column(DateTime(timezone=True), nullable=True)
