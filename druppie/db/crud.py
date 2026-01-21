"""CRUD operations for Druppie database.

Simple database operations without complex ORM patterns.
"""

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session as DBSession

from .models import Approval, Session


# =============================================================================
# SESSION CRUD
# =============================================================================


def create_session(
    db: DBSession,
    session_id: str,
    user_id: str | None = None,
    status: str = "active",
) -> Session:
    """Create a new session."""
    session = Session(
        id=session_id,
        user_id=user_id,
        status=status,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def get_session(db: DBSession, session_id: str) -> Session | None:
    """Get a session by ID."""
    return db.query(Session).filter(Session.id == session_id).first()


def update_session(
    db: DBSession,
    session_id: str,
    status: str | None = None,
    state: dict | None = None,
) -> Session | None:
    """Update a session."""
    session = get_session(db, session_id)
    if not session:
        return None

    if status is not None:
        session.status = status
    if state is not None:
        session.state = state
    session.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(session)
    return session


def delete_session(db: DBSession, session_id: str) -> bool:
    """Delete a session."""
    session = get_session(db, session_id)
    if not session:
        return False

    db.delete(session)
    db.commit()
    return True


def get_session_state(db: DBSession, session_id: str) -> dict | None:
    """Get execution state for a session."""
    session = get_session(db, session_id)
    if not session:
        return None
    return session.state


def save_session_state(db: DBSession, session_id: str, state: dict) -> bool:
    """Save execution state for a session."""
    session = get_session(db, session_id)
    if not session:
        # Create session if it doesn't exist
        session = create_session(db, session_id)

    session.state = state
    session.updated_at = datetime.utcnow()
    db.commit()
    return True


def delete_session_state(db: DBSession, session_id: str) -> bool:
    """Delete session state (but not the session itself)."""
    session = get_session(db, session_id)
    if not session:
        return False

    session.state = None
    session.updated_at = datetime.utcnow()
    db.commit()
    return True


def list_sessions(
    db: DBSession,
    user_id: str | None = None,
    status: str | None = None,
    limit: int = 50,
) -> list[Session]:
    """List sessions with optional filters."""
    query = db.query(Session)

    if user_id:
        query = query.filter(Session.user_id == user_id)
    if status:
        query = query.filter(Session.status == status)

    return query.order_by(Session.created_at.desc()).limit(limit).all()


def upsert_session(
    db: DBSession,
    session_id: str,
    user_id: str | None = None,
    status: str = "active",
    state: dict | None = None,
) -> Session:
    """Create or update a session.

    This is the preferred method for saving sessions from the main loop.
    """
    session = get_session(db, session_id)

    if session:
        # Update existing session
        if user_id is not None:
            session.user_id = user_id
        session.status = status
        if state is not None:
            session.state = state
        session.updated_at = datetime.utcnow()
    else:
        # Create new session
        session = Session(
            id=session_id,
            user_id=user_id,
            status=status,
            state=state,
        )
        db.add(session)

    db.flush()
    return session


# =============================================================================
# APPROVAL CRUD
# =============================================================================


def create_approval(db: DBSession, data: dict[str, Any]) -> Approval:
    """Create a new approval request."""
    approval = Approval(
        id=data.get("id"),
        session_id=data.get("session_id"),
        tool_name=data.get("tool_name"),
        arguments=data.get("arguments"),
        status=data.get("status", "pending"),
        required_roles=data.get("required_roles"),
        approvals_received=data.get("approvals_received", []),
        danger_level=data.get("danger_level", "low"),
        description=data.get("description"),
    )
    db.add(approval)
    db.commit()
    db.refresh(approval)
    return approval


def get_approval(db: DBSession, approval_id: str) -> Approval | None:
    """Get an approval by ID."""
    return db.query(Approval).filter(Approval.id == approval_id).first()


def update_approval(db: DBSession, approval_id: str, data: dict[str, Any]) -> Approval | None:
    """Update an approval."""
    approval = get_approval(db, approval_id)
    if not approval:
        return None

    if "status" in data:
        approval.status = data["status"]
    if "approvals_received" in data:
        approval.approvals_received = data["approvals_received"]

    db.commit()
    db.refresh(approval)
    return approval


def list_pending_approvals(
    db: DBSession,
    session_id: str | None = None,
    limit: int = 50,
) -> list[Approval]:
    """List pending approvals."""
    query = db.query(Approval).filter(Approval.status == "pending")

    if session_id:
        query = query.filter(Approval.session_id == session_id)

    return query.order_by(Approval.created_at.desc()).limit(limit).all()


def list_approvals_for_session(db: DBSession, session_id: str) -> list[Approval]:
    """List all approvals for a session."""
    return (
        db.query(Approval)
        .filter(Approval.session_id == session_id)
        .order_by(Approval.created_at.desc())
        .all()
    )
