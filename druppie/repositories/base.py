"""Base repository class."""

from sqlalchemy.orm import Session


class BaseRepository:
    """Base class for all repositories."""

    def __init__(self, db: Session):
        self.db = db

    def commit(self):
        """Commit the current transaction."""
        self.db.commit()

    def rollback(self):
        """Rollback the current transaction."""
        self.db.rollback()

    def flush(self):
        """Flush pending changes without committing."""
        self.db.flush()
