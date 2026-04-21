import logging
from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings

logger = logging.getLogger(__name__)

engine = create_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create tables if they don't exist.

    Uses an advisory lock to prevent race conditions when multiple
    gunicorn workers start simultaneously.
    """
    import app.models  # noqa: F401
    try:
        import app.chat  # noqa: F401 — register chat models
    except ImportError:
        pass

    with engine.connect() as conn:
        # PostgreSQL advisory lock to prevent concurrent CREATE TABLE
        try:
            conn.execute(text("SELECT pg_advisory_lock(42)"))
            Base.metadata.create_all(bind=engine)
            conn.execute(text("SELECT pg_advisory_unlock(42)"))
            conn.commit()
        except Exception:
            # Fallback for non-PostgreSQL (e.g. SQLite in tests)
            Base.metadata.create_all(bind=engine)
