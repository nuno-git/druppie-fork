"""Test run tag database model for testing framework."""

from uuid import uuid4

from sqlalchemy import Column, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from .base import Base


class TestRunTag(Base):
    """A tag associated with a test run."""

    __tablename__ = "test_run_tags"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    test_run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("test_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    tag = Column(String(100), nullable=False)

    # Indexes and constraints
    __table_args__ = (
        Index("idx_test_run_tags_tag", "tag"),
        UniqueConstraint("test_run_id", "tag", name="uq_test_run_tags_run_tag"),
    )

    # Relationships
    test_run = relationship("TestRun", back_populates="tags")
