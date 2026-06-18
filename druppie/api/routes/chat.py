"""Chat API routes.

Main endpoint for processing user messages.

Architecture:
    POST /api/chat
      │
      ├── Create session (fast)
      ├── Spawn background task
      └── Return immediately with session_id

    Background task:
      └──▶ Orchestrator ──▶ Agent execution
              (router → planner → execute pending runs)

The endpoint returns immediately with session_id. The client polls
GET /api/sessions/{id} to track progress.

When the workflow pauses (needs approval or HITL question), the session
status changes. The frontend fetches SessionDetail to see pending
approvals/questions and uses:
- POST /approvals/{id}/approve or /reject
- POST /questions/{id}/answer
"""

from uuid import UUID

import httpx
import structlog
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from druppie.api.deps import get_attachment_repository, get_current_user, get_optional_user, get_session_repository, get_user_roles
from druppie.repositories import SessionRepository
from druppie.repositories.attachment_repository import AttachmentRepository
from druppie.domain.common import SessionStatus
from druppie.api.errors import NotFoundError, AuthorizationError
from druppie.core.background_tasks import create_session_task, SessionTaskConflict, run_session_task
from druppie.services import attachment_service

logger = structlog.get_logger()

router = APIRouter()


# =============================================================================
# REQUEST/RESPONSE MODELS
# =============================================================================


class ChatRequest(BaseModel):
    """Request for chat endpoint."""

    message: str = Field(
        ...,
        description="The user's message",
        max_length=10000,
    )
    session_id: str | None = Field(
        None,
        description="Session ID to continue an existing conversation",
    )
    project_id: str | None = Field(
        None,
        description="Project ID to work on",
    )
    attachment_ids: list[str] = Field(
        default=[],
        description="Attachment IDs from prior upload calls",
    )


class ChatResponse(BaseModel):
    """Response from chat endpoint."""

    success: bool = Field(..., description="Whether the request succeeded")
    session_id: str = Field(..., description="Session ID")
    status: str = Field(
        ...,
        description="Session status: active, completed, paused_approval, paused_hitl, failed",
    )
    message: str | None = Field(None, description="Status message")


# =============================================================================
# BACKGROUND TASK
# =============================================================================


async def _run_orchestrator_background(
    message: str,
    user_id: UUID,
    session_id: UUID,
    project_id: UUID | None,
    attachment_ids: list[UUID] | None = None,
) -> None:
    """Run orchestrator in background with its own DB session."""

    async def task(ctx):
        await ctx.orchestrator.process_message(
            message=message,
            user_id=user_id,
            session_id=session_id,
            project_id=project_id,
            attachment_ids=attachment_ids or [],
        )

    await run_session_task(session_id, task, "background_orchestrator")


# =============================================================================
# ROUTES
# =============================================================================


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    user: dict | None = Depends(get_optional_user),
    session_repo: SessionRepository = Depends(get_session_repository),
    attachment_repo: AttachmentRepository = Depends(get_attachment_repository),
) -> ChatResponse:
    """Process a chat message.

    Creates a session and starts processing in the background.
    Returns immediately with the session ID.

    The client should poll GET /api/sessions/{id} to track progress.
    Session status will be:
    - active: Processing in progress
    - completed: All agents finished
    - paused_approval: Waiting for tool approval
    - paused_hitl: Waiting for user answer
    - failed: Error occurred

    Args:
        request: Chat message and optional session/project IDs

    Returns:
        Response with session ID (processing continues in background)
    """
    # User ID is required for the orchestrator (to fetch projects)
    if not user or not user.get("sub"):
        return ChatResponse(
            success=False,
            session_id="",
            status="error",
            message="Authentication required",
        )

    user_id = UUID(user["sub"])
    project_id = UUID(request.project_id) if request.project_id else None
    session_id_param = UUID(request.session_id) if request.session_id else None

    logger.info(
        "chat_request",
        session_id=str(session_id_param) if session_id_param else "new",
        user_id=str(user_id),
        message_length=len(request.message),
    )

    try:
        # Step 1: Get or create session (fast, synchronous)
        if session_id_param:
            existing = session_repo.get_by_id_for_update(session_id_param)
            if not existing:
                return ChatResponse(
                    success=False,
                    session_id=str(session_id_param),
                    status="error",
                    message=f"Session {session_id_param} not found",
                )
            user_roles = get_user_roles(user)
            is_owner = existing.user_id == user_id
            is_admin = "admin" in user_roles
            if not is_owner and not is_admin:
                raise AuthorizationError("Cannot continue this session")
            if existing.status != SessionStatus.COMPLETED.value:
                return ChatResponse(
                    success=False,
                    session_id=str(session_id_param),
                    status="error",
                    message=f"Cannot continue session: status is '{existing.status}', must be 'completed'",
                )
            session_repo.commit()
            current_session_id = session_id_param
        else:
            session = session_repo.create(
                user_id=user_id,
                project_id=project_id,
                title=request.message[:100] if request.message else "New Session",
            )
            session_repo.commit()
            current_session_id = session.id

        logger.info(
            "chat_session_created",
            session_id=str(current_session_id),
            is_new=session_id_param is None,
        )

        # Step 2: Spawn background task (does NOT block)
        # New sessions: skip_lock=True — just created, no other request can
        # reference this session_id yet, so no race is possible.
        # Existing sessions: guard via SELECT FOR UPDATE in create_session_task.
        is_new_session = session_id_param is None
        try:
            attachment_uuids = [UUID(aid) for aid in request.attachment_ids] if request.attachment_ids else None
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid attachment ID format")
        if attachment_uuids:
            try:
                attachment_repo.validate_ownership(attachment_uuids, current_session_id, owner_user_id=user_id)
            except ValueError as e:
                raise HTTPException(status_code=403, detail=str(e))

        try:
            create_session_task(
                current_session_id,
                _run_orchestrator_background(
                    message=request.message,
                    user_id=user_id,
                    session_id=current_session_id,
                    project_id=project_id,
                    attachment_ids=attachment_uuids,
                ),
                name=f"orchestrator-{current_session_id}",
                skip_lock=is_new_session,
            )
        except SessionTaskConflict:
            return ChatResponse(
                success=False,
                session_id=str(current_session_id),
                status="error",
                message="A task is already running for this session",
            )

        # Step 3: Return immediately
        return ChatResponse(
            success=True,
            session_id=str(current_session_id),
            status=SessionStatus.ACTIVE.value,
            message="Processing started",
        )

    except (HTTPException, AuthorizationError, NotFoundError):
        raise
    except Exception as e:
        logger.error(
            "chat_error",
            session_id=str(session_id_param) if session_id_param else "new",
            error=str(e),
            exc_info=True,
        )

        return ChatResponse(
            success=False,
            session_id=str(session_id_param) if session_id_param else "",
            status="error",
            message=f"Error: {str(e)}",
        )


STOPPABLE_STATUSES = {"active", "paused_approval", "paused_hitl"}


@router.post("/chat/{session_id}/cancel")
async def stop_session(
    session_id: UUID,
    user: dict = Depends(get_current_user),
    session_repo: SessionRepository = Depends(get_session_repository),
):
    """Stop a running session (soft stop — always resumable).

    Sets session status to PAUSED. The background orchestrator/agent loop
    will detect this on its next DB poll and exit cleanly after the current
    LLM call + tool execution completes.

    Agent runs keep their current status:
    - RUNNING → will be marked PAUSED_USER when the agent loop detects the pause
    - PAUSED_TOOL/PAUSED_HITL → stay as-is, resume restores their session status
    - PENDING → stay PENDING for later execution

    URL kept as /cancel for backwards compatibility with existing frontend.
    """
    user_id = UUID(user["sub"])
    user_roles = user.get("realm_access", {}).get("roles", [])

    # Read without row lock — avoid deadlocking with the background task's
    # long-running transaction (agent execution holds an open DB session).
    # Setting PAUSED is a "fire and forget" flag; the background task's
    # SessionPauseToken polls for it cooperatively.
    session = session_repo.get_by_id(session_id)
    if not session:
        raise NotFoundError("session", str(session_id))

    # Only owner or admin can stop
    is_owner = session.user_id == user_id
    is_admin = "admin" in user_roles
    if not is_owner and not is_admin:
        raise AuthorizationError("Cannot stop this session")

    if session.status not in STOPPABLE_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot stop session with status '{session.status}'",
        )

    # Signal the pause two ways:
    # 1. Direct in-memory cancel (zero latency — agent loop checks is_cancelled)
    # 2. DB status flag (fallback if token not registered yet, or for resume flows)
    from druppie.agent_runtime.types import SessionPauseToken
    from druppie.db.database import SessionLocal
    _db = SessionLocal()
    try:
        _repo = SessionRepository(_db)
        _repo.update_status(session_id, SessionStatus.PAUSED)
        _db.commit()
    finally:
        _db.close()

    SessionPauseToken.cancel_session(session_id)

    from druppie.db.listen_notify import notify_session_cancel
    notify_session_cancel(session_id)

    try:
        import os
        coding_url = os.getenv("MCP_CODING_URL", "http://module-coding:9001")
        async with httpx.AsyncClient() as client:
            await client.post(
                f"{coding_url}/management/sandbox/cleanup/{session_id}",
                timeout=10,
            )
    except Exception as e:
        logger.warning("sandbox_cleanup_failed_on_stop", session_id=str(session_id), error=str(e))

    logger.info("session_stopped", session_id=str(session_id))

    return {
        "success": True,
        "session_id": str(session_id),
        "message": "Session stopped",
    }


# =============================================================================
# FILE UPLOAD
# =============================================================================


@router.post("/chat/upload")
async def upload_attachment(
    file: UploadFile = File(...),
    session_id: str | None = Query(None),
    user: dict = Depends(get_current_user),
    attachment_repo: AttachmentRepository = Depends(get_attachment_repository),
    session_repo: SessionRepository = Depends(get_session_repository),
):
    """Upload a file to attach to a chat message.

    Files are stored on disk and metadata saved to DB. The returned
    attachment ID should be passed in the next POST /api/chat request
    via the attachment_ids field.
    """
    filename = file.filename or "unnamed"
    content_type = attachment_service.resolve_content_type(filename, file.content_type)

    # Read and validate file content
    content = await file.read()
    file_size = len(content)
    try:
        attachment_service.validate_file(filename, content_type, file_size)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Verify session ownership when session_id is provided
    sid = UUID(session_id) if session_id else None
    owner_user_id = UUID(user["sub"])
    if sid:
        session = session_repo.get_by_id(sid)
        if not session:
            raise NotFoundError("session", str(sid))
        user_roles = get_user_roles(user)
        if session.user_id != owner_user_id and "admin" not in user_roles:
            raise AuthorizationError("Cannot upload to this session")
    attachment = attachment_repo.create(
        original_filename=filename,
        content_type=content_type,
        file_size=file_size,
        storage_path="pending",
        owner_user_id=owner_user_id,
        session_id=sid,
    )
    attachment_repo.db.flush()

    # Store file to disk keyed by attachment ID
    safe_name = attachment_service._sanitize_filename(filename)
    dir_path = attachment_service.UPLOAD_DIR / str(attachment.id)
    dir_path.mkdir(parents=True, exist_ok=True)
    file_path = dir_path / safe_name
    file_path.write_bytes(content)

    storage_path = f"uploads/{attachment.id}/{safe_name}"
    attachment.storage_path = storage_path
    attachment.extracted_text = await attachment_service.extract_text(file_path, content_type)
    attachment_repo.db.commit()

    return {
        "id": str(attachment.id),
        "original_filename": attachment.original_filename,
        "content_type": attachment.content_type,
        "file_size": attachment.file_size,
    }


@router.get("/attachments/{attachment_id}")
async def get_attachment(
    attachment_id: UUID,
    token: str | None = Query(None),
    user: dict | None = Depends(get_optional_user),
    attachment_repo: AttachmentRepository = Depends(get_attachment_repository),
    session_repo: SessionRepository = Depends(get_session_repository),
):
    """Serve an uploaded attachment file.

    Accepts auth via either the Authorization header or a ?token= query param
    so that <img src> and <a href> work without custom fetch logic.
    """
    # If no user from header, try the token query param
    if not user and token:
        from druppie.core.auth import get_auth_service
        auth = get_auth_service()
        user = auth.validate_request(f"Bearer {token}")

    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")

    attachment = attachment_repo.get_by_id(attachment_id)
    if not attachment:
        raise NotFoundError("attachment", str(attachment_id))

    # Check access: user must own the attachment or be admin.
    # Unconditional — uploads to new chats have session_id=None, so the
    # owner check cannot rely on session linkage.
    user_id = UUID(user["sub"])
    user_roles = get_user_roles(user)
    is_admin = "admin" in user_roles
    if attachment.owner_user_id != user_id and not is_admin:
        raise AuthorizationError("Cannot access this attachment")

    file_path = attachment_service.get_file_path(attachment.storage_path)
    if not file_path.exists():
        raise NotFoundError("attachment file", str(attachment_id))

    return FileResponse(
        path=str(file_path),
        media_type=attachment.content_type,
        filename=attachment.original_filename,
    )
