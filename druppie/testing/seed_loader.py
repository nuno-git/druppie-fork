"""YAML fixture loader \u2014 creates DB records and optionally real Gitea repos.

Reads validated YAML fixtures and inserts DB records via SQLAlchemy.
When a ``gitea_url`` is provided, actual repos are created in Gitea so that
project links in the frontend point to working URLs.
"""

from __future__ import annotations

import base64
import logging
import uuid
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

from druppie.testing.seed_ids import fixture_uuid
from druppie.testing.seed_schema import AgentRunFixture, SessionFixture, ToolCallFixture, ToolCallOutcome

logger = logging.getLogger(__name__)

# HITL tool names that create Question records
_HITL_TOOLS = {"hitl_ask_question", "hitl_ask_multiple_choice_question"}


# ---------------------------------------------------------------------------
# Gitea helper
# ---------------------------------------------------------------------------


def _create_gitea_repo(project_name: str, gitea_url: str) -> dict | None:
    """Create a Gitea repo via REST API.

    Returns a dict with ``repo_name``, ``repo_owner``, ``repo_url``, and
    ``clone_url`` on success, or *None* if the request fails.
    """
    import httpx

    try:
        client = httpx.Client(
            base_url=gitea_url,
            auth=("gitea_admin", "GiteaAdmin123"),
            timeout=15,
        )

        # Ensure druppie_admin user exists
        r = client.get("/api/v1/users/druppie_admin")
        if r.status_code == 404:
            r2 = client.post("/api/v1/admin/users", json={
                "username": "druppie_admin",
                "email": "druppie_admin@druppie.local",
                "password": "DruppieAdmin123!",
                "must_change_password": False,
                "login_name": "druppie_admin",
                "source_id": 0,
            })
            if r2.status_code not in (201, 422):
                logger.warning(
                    "Could not create druppie_admin user: %s", r2.status_code
                )
            else:
                logger.info("Created Gitea user druppie_admin")

        # Create repo with a unique suffix
        short = uuid.uuid4().hex[:8]
        repo_name = f"{project_name}-{short}"
        r = client.post("/api/v1/admin/users/druppie_admin/repos", json={
            "name": repo_name,
            "description": f"{project_name} \u2014 seeded test data",
            "private": False,
            "auto_init": True,
            "readme": "Default",
        })
        if r.status_code == 201:
            logger.info("Created Gitea repo: druppie_admin/%s", repo_name)
        elif r.status_code in (409, 422):
            logger.info("Gitea repo already exists: druppie_admin/%s", repo_name)
        else:
            logger.warning(
                "Failed to create Gitea repo %s: HTTP %s", repo_name, r.status_code
            )
            return None

        return {
            "repo_name": repo_name,
            "repo_owner": "druppie_admin",
            "repo_url": f"{gitea_url}/druppie_admin/{repo_name}",
            "clone_url": f"{gitea_url}/druppie_admin/{repo_name}.git",
        }

    except Exception:
        logger.warning(
            "Gitea not reachable at %s \u2014 falling back to placeholder URLs",
            gitea_url,
            exc_info=True,
        )
        return None


# ---------------------------------------------------------------------------
# Outcome replay — create files in repo for execute_coding_task outcomes
# ---------------------------------------------------------------------------


def _replay_outcome(
    outcome: ToolCallOutcome,
    gitea_url: str | None,
    repo_owner: str,
    repo_name: str,
) -> None:
    """Replay an execute_coding_task outcome: create files in the target repo."""
    import httpx

    if outcome.target == "github":
        # GitHub support is future work — skip for now, log warning
        logger.warning("GitHub target not yet supported for outcome replay, skipping")
        return

    if not gitea_url:
        return  # Record-only mode, skip

    client = httpx.Client(
        base_url=gitea_url,
        auth=("gitea_admin", "GiteaAdmin123"),
        timeout=30,
    )

    try:
        for f in outcome.files:
            content = f.content
            if content is None and f.from_file:
                # Load from local file
                file_path = Path(f.from_file)
                if file_path.exists():
                    content = file_path.read_text()
                else:
                    logger.warning("from_file not found: %s", f.from_file)
                    continue

            if content is None:
                continue

            encoded = base64.b64encode(content.encode()).decode()

            # Check if file exists (need SHA for update)
            r = client.get(f"/api/v1/repos/{repo_owner}/{repo_name}/contents/{f.path}")

            body: dict = {
                "content": encoded,
                "message": outcome.commit_message or f"Add {f.path}",
            }
            if outcome.branch:
                body["branch"] = outcome.branch

            if r.status_code == 200:
                body["sha"] = r.json()["sha"]
                r = client.put(
                    f"/api/v1/repos/{repo_owner}/{repo_name}/contents/{f.path}",
                    json=body,
                )
            else:
                r = client.post(
                    f"/api/v1/repos/{repo_owner}/{repo_name}/contents/{f.path}",
                    json=body,
                )

            if r.status_code in (200, 201):
                logger.info("Created file %s in %s/%s", f.path, repo_owner, repo_name)
            else:
                logger.warning(
                    "Failed to create %s: %s %s",
                    f.path, r.status_code, r.text[:200],
                )
    finally:
        client.close()


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


def seed_fixture(
    db: DbSession,
    fixture: SessionFixture,
    gitea_url: str | None = None,
) -> None:
    """Insert DB records for a single fixture (idempotent).

    When *gitea_url* is provided, a real Gitea repo is created for the
    project so that links in the frontend resolve correctly.
    """
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
    base_ts = utcnow()  # Always use current time for seeded data

    # -- 4. Project --
    project_db_id = None
    _repo_owner: str | None = None
    _repo_name: str | None = None
    if meta.project_name:
        # Check if a project with this name already exists (e.g. update_project
        # sessions reference the same project created by a create_project session)
        existing_project = (
            db.query(Project)
            .filter(
                Project.name == meta.project_name,
                Project.owner_id == user.id,
            )
            .first()
        )

        if existing_project:
            # Re-use the existing project — don't create a new one or repo
            project_db_id = existing_project.id
            _repo_owner = existing_project.repo_owner
            _repo_name = existing_project.repo_name
            logger.info(
                "Linking session %s to existing project %s (%s/%s)",
                meta.id, meta.project_name, _repo_owner, _repo_name,
            )
        else:
            # Try to create a real Gitea repo when gitea_url is provided
            repo_info = None
            if gitea_url:
                repo_info = _create_gitea_repo(meta.project_name, gitea_url)

            if repo_info:
                repo_name = repo_info["repo_name"]
                repo_owner = repo_info["repo_owner"]
                repo_url = repo_info["repo_url"]
                clone_url = repo_info["clone_url"]
                _repo_owner = repo_owner
                _repo_name = repo_name
            else:
                # Placeholder URLs (record-only mode)
                repo_name = meta.project_name
                repo_owner = "druppie_admin"
                repo_url = f"http://gitea:3000/druppie_admin/{meta.project_name}"
                clone_url = f"http://gitea:3000/druppie_admin/{meta.project_name}.git"

            project = Project(
                id=project_id,
                name=meta.project_name,
                description=f"Fixture: {meta.title}",
                repo_name=repo_name,
                repo_owner=repo_owner,
                repo_url=repo_url,
                clone_url=clone_url,
                owner_id=user.id,
                status="active",
                created_at=base_ts,
                updated_at=base_ts,
            )
            db.add(project)
            db.flush()
            project_db_id = project_id

        # NOTE: repo files are now seeded via outcome blocks on
        # execute_coding_task tool calls (see _seed_tool_calls).

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
    db.flush()

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
    db.flush()

    # -- 8. Agent runs --
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
        db.flush()

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
            db.flush()

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
            gitea_url=gitea_url,
            repo_owner=_repo_owner,
            repo_name=_repo_name,
        )


    db.flush()


def seed_all(
    db: DbSession,
    fixtures_dir: Path,
    gitea_url: str | None = None,
) -> int:
    """Load and seed all fixtures. Return the count of fixtures seeded.

    When *gitea_url* is provided it is passed through to each fixture so
    that real Gitea repos are created for projects.
    """
    fixtures = load_fixtures(fixtures_dir)
    for fix in fixtures:
        seed_fixture(db, fix, gitea_url=gitea_url)
    return len(fixtures)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _replay_tool_call(
    tool_call: ToolCallFixture,
    gitea_url: str,
    repo_owner: str,
    repo_name: str,
) -> None:
    """Execute a tool call against Gitea if applicable.

    Only coding:write_file, coding:make_design, and coding:batch_write_files
    are replayed. Other tool calls are just recorded in the DB.
    """
    import httpx

    if tool_call.mcp_server != "coding":
        return

    client = httpx.Client(
        base_url=gitea_url,
        auth=("gitea_admin", "GiteaAdmin123"),
        timeout=30,
    )

    try:
        if tool_call.tool_name in ("write_file", "make_design"):
            path = tool_call.arguments.get("path", "")
            content = tool_call.arguments.get("content", "")
            if path and content:
                _gitea_create_file(client, repo_owner, repo_name, path, content)

        elif tool_call.tool_name == "batch_write_files":
            files = tool_call.arguments.get("files", [])
            for f in files:
                path = f.get("path", "")
                content = f.get("content", "")
                if path and content:
                    _gitea_create_file(client, repo_owner, repo_name, path, content)
    finally:
        client.close()


def _gitea_create_file(
    client,
    owner: str,
    repo: str,
    path: str,
    content: str,
) -> None:
    """Create or update a file in a Gitea repo."""

    # Check if file exists (need SHA for update)
    r = client.get(f"/api/v1/repos/{owner}/{repo}/contents/{path}")

    body = {
        "content": base64.b64encode(content.encode()).decode(),
        "message": f"Add {path}",
    }

    if r.status_code == 200:
        # File exists, update it
        body["sha"] = r.json()["sha"]
        r = client.put(f"/api/v1/repos/{owner}/{repo}/contents/{path}", json=body)
    else:
        # File doesn't exist, create it
        r = client.post(f"/api/v1/repos/{owner}/{repo}/contents/{path}", json=body)

    if r.status_code in (200, 201):
        logger.info("  Replayed file %s in %s/%s", path, owner, repo)
    else:
        logger.warning(
            "  Failed to create file %s in %s/%s: %s", path, owner, repo, r.status_code
        )


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
    gitea_url: str | None = None,
    repo_owner: str | None = None,
    repo_name: str | None = None,
) -> None:
    """Create ToolCall (and optional Approval / Question) records."""
    meta = fixture.metadata

    for tc_idx, tc in enumerate(agent.tool_calls):
        tc_id = fixture_uuid(meta.id, "run", agent_idx, "tc", tc_idx)

        # For HITL tool calls, use answer as result if no explicit result
        tc_result = tc.result
        if tc.answer and not tc_result:
            tc_result = tc.answer

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
            result=tc_result,
            error_message=tc.error_message,
            created_at=run_ts,
            executed_at=run_ts if tc.status in ("completed", "failed") else None,
        )
        db.add(tool_call)
        db.flush()

        # Replay tool call against Gitea (create real files)
        if gitea_url and repo_owner and repo_name:
            _replay_tool_call(tc, gitea_url, repo_owner, repo_name)

        # Replay outcome if this is an execute_coding_task with an outcome block
        if (
            tc.tool_name == "execute_coding_task"
            and tc.outcome is not None
            and repo_owner
            and repo_name
        ):
            _replay_outcome(tc.outcome, gitea_url, repo_owner, repo_name)

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
