"""Chat session models and routes.

Provides a ChatGPT-style conversational interface backed by the Druppie SDK.
Every project gets this out of the box — customize the agent logic in agent.py.

Architecture: messages are processed asynchronously. When a user sends a
message, the backend saves it, creates a "thinking" placeholder, and
processes the agent in a background thread. The frontend polls for updates.
This way navigating away doesn't cancel the AI response.
"""

import threading
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer, String, Text, ForeignKey, JSON
from sqlalchemy.orm import relationship

from app.database import Base, get_db, SessionLocal


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(200), default="Nieuw gesprek")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    messages = relationship("ChatMessage", back_populates="session",
                            cascade="all, delete-orphan",
                            order_by="ChatMessage.created_at")


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(Integer, ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(20), nullable=False)  # "user" or "assistant"
    content = Column(Text, nullable=False, default="")
    # "thinking" while agent processes, "done" when complete, "error" on failure
    status = Column(String(20), nullable=False, default="done")
    # Agent metadata — search terms, found documents, reasoning steps
    metadata_ = Column("metadata", JSON, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    session = relationship("ChatSession", back_populates="messages")


# ---------------------------------------------------------------------------
# Background agent processing
# ---------------------------------------------------------------------------

def _process_message_background(session_id: int, assistant_msg_id: int, user_text: str, history: list[dict]):
    """Run the agent in a background thread with its own DB session."""
    db = SessionLocal()
    try:
        from app.agent import run_agent
        result = run_agent(user_text, history, db)

        msg = db.query(ChatMessage).filter(ChatMessage.id == assistant_msg_id).first()
        if msg:
            msg.content = result.get("answer", "")
            msg.status = "done"
            msg.metadata_ = result.get("steps")

        session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
        if session:
            session.updated_at = datetime.now(timezone.utc)

        db.commit()
    except Exception as e:
        db.rollback()
        try:
            msg = db.query(ChatMessage).filter(ChatMessage.id == assistant_msg_id).first()
            if msg:
                msg.content = f"Fout bij verwerking: {e}"
                msg.status = "error"
            db.commit()
        except Exception:
            pass
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

from flask import Blueprint, jsonify, request

chat_api = Blueprint("chat_api", __name__)


@chat_api.route("/chat/sessions", methods=["POST"])
def create_session():
    db = next(get_db())
    session = ChatSession()
    db.add(session)
    db.commit()
    db.refresh(session)
    return jsonify(_session_to_dict(session)), 201


@chat_api.route("/chat/sessions")
def list_sessions():
    db = next(get_db())
    sessions = db.query(ChatSession).order_by(ChatSession.updated_at.desc()).all()
    return jsonify([_session_to_dict(s) for s in sessions])


@chat_api.route("/chat/sessions/<int:session_id>")
def get_session(session_id):
    db = next(get_db())
    session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if not session:
        return jsonify(error="Sessie niet gevonden"), 404
    return jsonify({
        **_session_to_dict(session),
        "messages": [_message_to_dict(m) for m in session.messages],
    })


@chat_api.route("/chat/sessions/<int:session_id>", methods=["DELETE"])
def delete_session(session_id):
    db = next(get_db())
    session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if not session:
        return jsonify(error="Sessie niet gevonden"), 404
    db.delete(session)
    db.commit()
    return jsonify(ok=True)


@chat_api.route("/chat/sessions/<int:session_id>/rename", methods=["POST"])
def rename_session(session_id):
    db = next(get_db())
    session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if not session:
        return jsonify(error="Sessie niet gevonden"), 404
    data = request.get_json(silent=True)
    if data and "title" in data:
        session.title = data["title"][:200]
        db.commit()
    return jsonify(_session_to_dict(session))


@chat_api.route("/chat/sessions/<int:session_id>/messages", methods=["POST"])
def send_message(session_id):
    """Send a message. Returns immediately with a 'thinking' assistant message.

    The agent processes in a background thread. Poll GET /sessions/{id}
    to check when the assistant message status changes from 'thinking' to 'done'.
    """
    db = next(get_db())
    session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if not session:
        return jsonify(error="Sessie niet gevonden"), 404

    data = request.get_json(silent=True)
    if not data or "message" not in data:
        return jsonify(error="Bericht is verplicht"), 400

    user_text = data["message"].strip()
    if not user_text:
        return jsonify(error="Leeg bericht"), 400

    # Save user message
    user_msg = ChatMessage(session_id=session_id, role="user", content=user_text)
    db.add(user_msg)

    # Auto-title from first message
    if session.title == "Nieuw gesprek":
        session.title = user_text[:80] + ("..." if len(user_text) > 80 else "")

    # Create placeholder assistant message
    assistant_msg = ChatMessage(
        session_id=session_id, role="assistant",
        content="", status="thinking",
    )
    db.add(assistant_msg)
    db.commit()
    db.refresh(assistant_msg)

    # Get conversation history (excluding the new messages)
    history = [{"role": m.role, "content": m.content}
               for m in session.messages
               if m.id not in (user_msg.id, assistant_msg.id) and m.status == "done"]

    # Process in background thread
    thread = threading.Thread(
        target=_process_message_background,
        args=(session_id, assistant_msg.id, user_text, history),
        daemon=True,
    )
    thread.start()

    return jsonify(_message_to_dict(assistant_msg)), 202


def _session_to_dict(s):
    return {
        "id": s.id,
        "title": s.title,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
        "message_count": len(s.messages) if s.messages else 0,
    }


def _message_to_dict(m):
    return {
        "id": m.id,
        "role": m.role,
        "content": m.content,
        "status": m.status,
        "steps": m.metadata_,
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }
