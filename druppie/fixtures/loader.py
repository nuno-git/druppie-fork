"""YAML fixture loader — record-only mode.

Reads validated YAML fixtures and inserts DB records via SQLAlchemy.
Replicates what ``scripts/seed_builder_retry.py`` does but from YAML data.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import yaml
from sqlalchemy.orm import Session as DbSession

from druppie.db.models import (
    AgentRun,
    Approval,
    LlmCall,
    Message,
    Project,
    Question,
    Session,
    ToolCall,
    User,
    UserRole,
)
from druppie.db.models.base import utcnow

from .ids import fixture_uuid
from .schema import AgentRunFixture, SessionFixture, ToolCallFixture

# HITL tool names that create Question records
_HITL_TOOLS = {"hitl_ask_question", "hitl_ask_multiple_choice_question"}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def load_fixtures(fixtures_dir: Path) -> list[SessionFixture]:
    """Load and validate all ``*.yaml`` fixtures from *fixtures_dir*."""
    results: list[SessionFixture] = []
    for path in sorted(fixtures_dir.glob("*.yaml")):
        with open(path) as f:
            data = yaml.safe_load(f)
        results.append(SessionFixture(**data))
    return results


def seed_fixture(db: DbSession, fixture: SessionFixture) -> None:
    """Insert DB records for a single fixture (idempotent)."""
    meta = fixture.metadata
    session_id = fixture_uuid(meta.id)

    # -- 1. Delete existing records for idempotency --
    # Delete child records explicitly in FK order (works without CASCADE)
    project_id = fixture_uuid(meta.id, "project")
    db.query(Approval).filter(Approval.session_id == session_id).delete()
    db.query(Question).filter(Question.session_id == session_id).delete()
    db.query(ToolCall).filter(ToolCall.session_id == session_id).delete()
    db.query(LlmCall).filter(LlmCall.session_id == session_id).delete()
    db.query(Message).filter(Message.session_id == session_id).delete()
    db.query(AgentRun).filter(AgentRun.session_id == session_id).delete()
    db.query(Session).filter(Session.id == session_id).delete()
    db.query(Project).filter(Project.id == project_id).delete()
    db.flush()

    # -- 2. Look up or create user --
    user = db.query(User).filter(User.username == meta.user).first()
    if not user:
        user_id = fixture_uuid(meta.id, "user")
        user = User(
            id=user_id,
            username=meta.user,
            email=f"{meta.user}@druppie.local",
            display_name=meta.user.title(),
        )
        db.add(user)
        db.add(UserRole(user_id=user_id, role="admin"))
        db.flush()

    # -- 3. Timestamps --
    base_ts = utcnow() - timedelta(hours=meta.hours_ago)

    # -- 4. Project (record-only: placeholder repo fields) --
    project_db_id = None
    if meta.project_name:
        project = Project(
            id=project_id,
            name=meta.project_name,
            description=f"Fixture: {meta.title}",
            repo_name=meta.project_name,
            repo_owner="druppie_admin",
            repo_url=f"http://gitea:3000/druppie_admin/{meta.project_name}",
            clone_url=f"http://gitea:3000/druppie_admin/{meta.project_name}.git",
            owner_id=user.id,
            status="active",
            created_at=base_ts,
            updated_at=base_ts,
        )
        db.add(project)
        project_db_id = project_id

    # -- 5. Token totals --
    completed_count = sum(1 for a in fixture.agents if a.status == "completed")
    total_prompt = completed_count * 3000
    total_completion = completed_count * 1000

    # -- 6. Session --
    session = Session(
        id=session_id,
        user_id=user.id,
        project_id=project_db_id,
        title=meta.title,
        status=meta.status,
        intent=meta.intent,
        language=meta.language,
        prompt_tokens=total_prompt,
        completion_tokens=total_completion,
        total_tokens=total_prompt + total_completion,
        created_at=base_ts,
        updated_at=base_ts,
    )
    db.add(session)

    # -- 7. User message at sequence 0 --
    # Use first user message from fixture, or fall back to title
    user_content = meta.title
    if fixture.messages:
        for msg in fixture.messages:
            if msg.role == "user":
                user_content = msg.content
                break

    db.add(Message(
        id=fixture_uuid(meta.id, "msg", 0),
        session_id=session_id,
        agent_run_id=None,
        role="user",
        content=user_content,
        agent_id=None,
        sequence_number=0,
        created_at=base_ts,
    ))

    # -- 8. Agent runs --
    msg_seq = 1  # next message sequence number
    for idx, agent in enumerate(fixture.agents):
        seq = idx + 1
        run_id = fixture_uuid(meta.id, "run", idx)
        run_ts = base_ts + timedelta(minutes=seq * 2)

        is_active = agent.status in ("completed", "failed", "running")

        # Token counts per agent run
        if agent.status == "completed":
            p_tok, c_tok = 3000, 1000
        elif agent.status == "running":
            p_tok, c_tok = 1500, 0
        else:
            p_tok, c_tok = 0, 0

        agent_run = AgentRun(
            id=run_id,
            session_id=session_id,
            agent_id=agent.id,
            status=agent.status,
            error_message=agent.error_message,
            planned_prompt=agent.planned_prompt,
            sequence_number=seq,
            iteration_count=1 if agent.status in ("completed", "failed") else 0,
            prompt_tokens=p_tok,
            completion_tokens=c_tok,
            total_tokens=p_tok + c_tok,
            started_at=run_ts if is_active else None,
            completed_at=run_ts if agent.status == "completed" else None,
            created_at=run_ts,
        )
        db.add(agent_run)

        # LLM call (only for active agents)
        llm_id = fixture_uuid(meta.id, "run", idx, "llm")
        if is_active:
            db.add(LlmCall(
                id=llm_id,
                session_id=session_id,
                agent_run_id=run_id,
                provider="zai",
                model="glm-4.7",
                prompt_tokens=p_tok,
                completion_tokens=c_tok,
                total_tokens=p_tok + c_tok,
                duration_ms=2000 + (idx * 500),
                created_at=run_ts,
            ))

        # Tool calls
        _seed_tool_calls(
            db,
            fixture=fixture,
            agent=agent,
            agent_idx=idx,
            run_id=run_id,
            llm_id=llm_id if is_active else None,
            session_id=session_id,
            run_ts=run_ts,
            user_id=user.id,
        )

        # Assistant message for completed agents with a done() tool call
        if agent.status == "completed":
            done_summary = _find_done_summary(agent)
            if done_summary:
                db.add(Message(
                    id=fixture_uuid(meta.id, "msg", msg_seq),
                    session_id=session_id,
                    agent_run_id=run_id,
                    role="assistant",
                    content=done_summary,
                    agent_id=agent.id,
                    sequence_number=msg_seq,
                    created_at=run_ts,
                ))
                msg_seq += 1

        # Error message for failed agents
        elif agent.status == "failed" and agent.error_message:
            db.add(Message(
                id=fixture_uuid(meta.id, "msg", msg_seq),
                session_id=session_id,
                agent_run_id=run_id,
                role="assistant",
                content=f"Agent {agent.id}: Failed — {agent.error_message}",
                agent_id=agent.id,
                sequence_number=msg_seq,
                created_at=run_ts,
            ))
            msg_seq += 1

    # -- 9. Extra messages from fixture --
    for msg_fix in fixture.messages:
        # Skip user messages (already handled above)
        if msg_fix.role == "user":
            continue
        db.add(Message(
            id=fixture_uuid(meta.id, "msg", msg_seq),
            session_id=session_id,
            agent_run_id=None,
            role=msg_fix.role,
            content=msg_fix.content,
            agent_id=msg_fix.agent_id,
            sequence_number=msg_seq,
            created_at=base_ts,
        ))
        msg_seq += 1

    db.flush()


def seed_all(db: DbSession, fixtures_dir: Path) -> int:
    """Load and seed all fixtures. Return the count of fixtures seeded."""
    fixtures = load_fixtures(fixtures_dir)
    for fix in fixtures:
        seed_fixture(db, fix)
    return len(fixtures)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seed_tool_calls(
    db: DbSession,
    *,
    fixture: SessionFixture,
    agent: AgentRunFixture,
    agent_idx: int,
    run_id,
    llm_id,
    session_id,
    run_ts,
    user_id,
) -> None:
    """Create ToolCall (and optional Approval / Question) records."""
    meta = fixture.metadata

    for tc_idx, tc in enumerate(agent.tool_calls):
        tc_id = fixture_uuid(meta.id, "run", agent_idx, "tc", tc_idx)

        tool_call = ToolCall(
            id=tc_id,
            session_id=session_id,
            agent_run_id=run_id,
            llm_call_id=llm_id,
            mcp_server=tc.mcp_server,
            tool_name=tc.tool_name,
            tool_call_index=tc_idx,
            arguments=tc.arguments or None,
            status=tc.status,
            result=tc.result,
            error_message=tc.error_message,
            created_at=run_ts,
            executed_at=run_ts if tc.status in ("completed", "failed") else None,
        )
        db.add(tool_call)

        # Approval record
        if tc.approval:
            resolved_at = run_ts if tc.approval.status != "pending" else None
            resolved_by = user_id if tc.approval.status != "pending" else None
            db.add(Approval(
                id=fixture_uuid(meta.id, "run", agent_idx, "tc", tc_idx, "approval"),
                session_id=session_id,
                agent_run_id=run_id,
                tool_call_id=tc_id,
                mcp_server=tc.mcp_server,
                tool_name=tc.tool_name,
                required_role=tc.approval.required_role,
                status=tc.approval.status,
                resolved_by=resolved_by,
                resolved_at=resolved_at,
                arguments=tc.arguments or None,
                agent_id=agent.id,
                created_at=run_ts,
            ))

        # Question record for HITL tools
        if tc.tool_name in _HITL_TOOLS:
            args = tc.arguments or {}
            if tc.tool_name == "hitl_ask_multiple_choice_question":
                question_type = "choice"
                choices = [{"text": c} for c in args.get("choices", [])]
            else:
                question_type = "text"
                choices = None

            has_answer = tc.answer is not None
            db.add(Question(
                id=fixture_uuid(meta.id, "run", agent_idx, "tc", tc_idx, "question"),
                session_id=session_id,
                agent_run_id=run_id,
                tool_call_id=tc_id,
                agent_id=agent.id,
                question=args.get("question", ""),
                question_type=question_type,
                choices=choices,
                status="answered" if has_answer else "pending",
                answer=tc.answer,
                answered_at=run_ts if has_answer else None,
                created_at=run_ts,
            ))


def _find_done_summary(agent: AgentRunFixture) -> str | None:
    """Return the summary from a ``done`` tool call, if present."""
    for tc in agent.tool_calls:
        if tc.tool_name == "done":
            args = tc.arguments or {}
            return args.get("summary", tc.result)
    return None
