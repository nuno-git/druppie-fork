"""Seed the database with sample data for development/testing.

Usage:
    python -m druppie.db.seed          # from project root
    docker compose exec druppie-new-backend python -m druppie.db.seed
"""

import uuid
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from druppie.db.database import SessionLocal, init_db
from druppie.db.models import (
    AgentRun,
    Approval,
    LlmCall,
    Message,
    Project,
    Question,
    Session as SessionModel,
    ToolCall,
    User,
    UserRole,
)

# Fixed UUIDs for reproducibility
USER_IDS = {
    "admin": uuid.UUID("00000000-0000-0000-0000-000000000001"),
    "architect": uuid.UUID("00000000-0000-0000-0000-000000000002"),
    "developer": uuid.UUID("00000000-0000-0000-0000-000000000003"),
    "analyst": uuid.UUID("00000000-0000-0000-0000-000000000004"),
    "normal_user": uuid.UUID("00000000-0000-0000-0000-000000000005"),
}

PROJECT_IDS = {
    "todo_app": uuid.UUID("10000000-0000-0000-0000-000000000001"),
    "file_search": uuid.UUID("10000000-0000-0000-0000-000000000002"),
    "dashboard": uuid.UUID("10000000-0000-0000-0000-000000000003"),
}

SESSION_IDS = {
    "todo_completed": uuid.UUID("20000000-0000-0000-0000-000000000001"),
    "file_search_active": uuid.UUID("20000000-0000-0000-0000-000000000002"),
    "dashboard_paused": uuid.UUID("20000000-0000-0000-0000-000000000003"),
    "chat_session": uuid.UUID("20000000-0000-0000-0000-000000000004"),
}

now = datetime.utcnow()


def seed_users(db: Session) -> None:
    """Create test users matching Keycloak accounts, or reuse existing ones."""
    users_data = [
        {"key": "admin", "username": "admin", "email": "admin@druppie.local", "display_name": "Admin User", "roles": ["admin"]},
        {"key": "architect", "username": "architect", "email": "architect@druppie.local", "display_name": "Alice Architect", "roles": ["architect"]},
        {"key": "developer", "username": "developer", "email": "developer@druppie.local", "display_name": "Dave Developer", "roles": ["developer"]},
        {"key": "analyst", "username": "analyst", "email": "analyst@druppie.local", "display_name": "Bob Analyst", "roles": []},
        {"key": "normal_user", "username": "normal_user", "email": "user@druppie.local", "display_name": "Normal User", "roles": []},
    ]

    for u in users_data:
        existing = db.query(User).filter_by(username=u["username"]).first()
        if existing:
            # Reuse existing user ID (synced from Keycloak)
            USER_IDS[u["key"]] = existing.id
        else:
            user_id = USER_IDS[u["key"]]
            user = User(id=user_id, username=u["username"], email=u["email"], display_name=u["display_name"])
            db.add(user)
            for role in u["roles"]:
                db.add(UserRole(user_id=user_id, role=role))


def seed_projects(db: Session) -> None:
    """Create sample projects."""
    projects = [
        {
            "id": PROJECT_IDS["todo_app"],
            "name": "Todo App",
            "description": "A simple task management application with REST API",
            "repo_name": "todo-app-a1b2c3d4",
            "repo_owner": "gitea_admin",
            "repo_url": "http://gitea:3000/gitea_admin/todo-app-a1b2c3d4",
            "clone_url": "http://gitea:3000/gitea_admin/todo-app-a1b2c3d4.git",
            "owner_id": USER_IDS["admin"],
            "status": "active",
            "created_at": now - timedelta(days=7),
        },
        {
            "id": PROJECT_IDS["file_search"],
            "name": "File Search App",
            "description": "Python file search application with full-text indexing",
            "repo_name": "file-search-app-e5f6g7h8",
            "repo_owner": "gitea_admin",
            "repo_url": "http://gitea:3000/gitea_admin/file-search-app-e5f6g7h8",
            "clone_url": "http://gitea:3000/gitea_admin/file-search-app-e5f6g7h8.git",
            "owner_id": USER_IDS["developer"],
            "status": "active",
            "created_at": now - timedelta(days=3),
        },
        {
            "id": PROJECT_IDS["dashboard"],
            "name": "Analytics Dashboard",
            "description": "React dashboard for visualizing project metrics",
            "repo_name": "analytics-dashboard-i9j0k1l2",
            "repo_owner": "gitea_admin",
            "repo_url": "http://gitea:3000/gitea_admin/analytics-dashboard-i9j0k1l2",
            "clone_url": "http://gitea:3000/gitea_admin/analytics-dashboard-i9j0k1l2.git",
            "owner_id": USER_IDS["architect"],
            "status": "active",
            "created_at": now - timedelta(days=1),
        },
    ]

    for p in projects:
        db.add(Project(**p))


def seed_sessions(db: Session) -> None:
    """Create sample sessions with agent runs, messages, and tool calls."""

    # --- Session 1: Completed todo app ---
    s1 = SessionModel(
        id=SESSION_IDS["todo_completed"],
        user_id=USER_IDS["admin"],
        project_id=PROJECT_IDS["todo_app"],
        title="Create a todo application with REST API",
        status="completed",
        intent="create_project",
        language="en",
        prompt_tokens=45000,
        completion_tokens=12000,
        total_tokens=57000,
        created_at=now - timedelta(days=7),
        updated_at=now - timedelta(days=6, hours=22),
    )
    db.add(s1)
    db.flush()

    # Agent runs for completed session
    runs_s1 = [
        ("router", "completed", 0, "Agent router: Intent detected as create_project. Project name: todo-app."),
        ("planner", "completed", 1, "Agent planner: Planned business_analyst to gather requirements."),
        ("business_analyst", "completed", 2, "Agent business_analyst: DESIGN_APPROVED. Created functional_design.md with 8 requirements."),
        ("planner", "completed", 3, "Agent planner: BA completed. Routing to architect."),
        ("architect", "completed", 4, "Agent architect: DESIGN_APPROVED. Created technical_design.md. Stack: Python/FastAPI, SQLite."),
        ("planner", "completed", 5, "Agent planner: Architect completed. Routing to builder_planner."),
        ("builder_planner", "completed", 6, "Agent builder_planner: Created builder_plan.md with pytest strategy, 12 test cases."),
        ("planner", "completed", 7, "Agent planner: Builder planner completed. Routing to test_builder."),
        ("test_builder", "completed", 8, "Agent test_builder: Generated 12 tests in tests/. Framework: pytest."),
        ("planner", "completed", 9, "Agent planner: Tests written. Routing to builder."),
        ("builder", "completed", 10, "Agent builder: Implemented src/ with 6 files. All committed and pushed."),
        ("planner", "completed", 11, "Agent planner: Builder completed. Routing to test_executor."),
        ("test_executor", "completed", 12, "Agent test_executor: TEST RESULT: PASS. 12/12 tests passed. Coverage: 87%."),
        ("planner", "completed", 13, "Agent planner: Tests passed. Routing to deployer."),
        ("deployer", "completed", 14, "Agent deployer: Deployed todo-app. USER FEEDBACK: Looks great!"),
        ("planner", "completed", 15, "Agent planner: User approved. Routing to summarizer."),
        ("summarizer", "completed", 16, "Agent summarizer: Project complete."),
    ]

    for agent_id, status, seq, summary in runs_s1:
        ar = AgentRun(
            id=uuid.uuid4(),
            session_id=s1.id,
            agent_id=agent_id,
            status=status,
            sequence_number=seq,
            iteration_count=2,
            prompt_tokens=2500,
            completion_tokens=800,
            total_tokens=3300,
            started_at=now - timedelta(days=7) + timedelta(hours=seq * 0.5),
            completed_at=now - timedelta(days=7) + timedelta(hours=seq * 0.5 + 0.4),
            created_at=now - timedelta(days=7) + timedelta(hours=seq * 0.5),
        )
        db.add(ar)

        # Add a summary message for each agent run
        db.add(Message(
            id=uuid.uuid4(),
            session_id=s1.id,
            agent_run_id=ar.id,
            role="assistant",
            content=summary,
            agent_id=agent_id,
            sequence_number=seq,
            created_at=ar.completed_at,
        ))

    # User message for session 1
    db.add(Message(
        id=uuid.uuid4(),
        session_id=s1.id,
        role="user",
        content="Create a todo application with a REST API. It should support CRUD operations for tasks with title, description, status, and due date.",
        sequence_number=0,
        created_at=now - timedelta(days=7),
    ))

    # --- Session 2: Active file search (in progress) ---
    s2 = SessionModel(
        id=SESSION_IDS["file_search_active"],
        user_id=USER_IDS["developer"],
        project_id=PROJECT_IDS["file_search"],
        title="Build a file search application",
        status="active",
        intent="create_project",
        language="en",
        prompt_tokens=18000,
        completion_tokens=5000,
        total_tokens=23000,
        created_at=now - timedelta(hours=4),
    )
    db.add(s2)
    db.flush()

    ar2 = AgentRun(
        id=uuid.uuid4(),
        session_id=s2.id,
        agent_id="builder",
        status="running",
        sequence_number=10,
        iteration_count=1,
        started_at=now - timedelta(minutes=15),
        created_at=now - timedelta(minutes=15),
    )
    db.add(ar2)

    db.add(Message(
        id=uuid.uuid4(),
        session_id=s2.id,
        role="user",
        content="Build a Python file search app with full-text indexing and a simple web UI.",
        sequence_number=0,
        created_at=now - timedelta(hours=4),
    ))

    # --- Session 3: Paused for HITL ---
    s3 = SessionModel(
        id=SESSION_IDS["dashboard_paused"],
        user_id=USER_IDS["architect"],
        project_id=PROJECT_IDS["dashboard"],
        title="Create an analytics dashboard",
        status="paused_hitl",
        intent="create_project",
        language="en",
        prompt_tokens=8000,
        completion_tokens=2000,
        total_tokens=10000,
        created_at=now - timedelta(hours=2),
    )
    db.add(s3)
    db.flush()

    ar3 = AgentRun(
        id=uuid.uuid4(),
        session_id=s3.id,
        agent_id="business_analyst",
        status="paused_hitl",
        sequence_number=2,
        iteration_count=3,
        started_at=now - timedelta(minutes=30),
        created_at=now - timedelta(minutes=30),
    )
    db.add(ar3)

    # Pending HITL question
    db.add(Question(
        id=uuid.uuid4(),
        session_id=s3.id,
        agent_run_id=ar3.id,
        agent_id="business_analyst",
        question="What metrics would you like to see on the dashboard? For example: page views, active users, error rates, deployment frequency?",
        question_type="text",
        status="pending",
        created_at=now - timedelta(minutes=5),
    ))

    db.add(Message(
        id=uuid.uuid4(),
        session_id=s3.id,
        role="user",
        content="Create a React dashboard to visualize our project metrics and team activity.",
        sequence_number=0,
        created_at=now - timedelta(hours=2),
    ))

    # --- Session 4: General chat (completed) ---
    s4 = SessionModel(
        id=SESSION_IDS["chat_session"],
        user_id=USER_IDS["normal_user"],
        title="How does the approval workflow work?",
        status="completed",
        intent="general_chat",
        language="en",
        prompt_tokens=3000,
        completion_tokens=1500,
        total_tokens=4500,
        created_at=now - timedelta(days=2),
        updated_at=now - timedelta(days=2, hours=-1),
    )
    db.add(s4)
    db.flush()

    db.add(Message(
        id=uuid.uuid4(),
        session_id=s4.id,
        role="user",
        content="How does the approval workflow work in Druppie?",
        sequence_number=0,
        created_at=now - timedelta(days=2),
    ))

    db.add(Message(
        id=uuid.uuid4(),
        session_id=s4.id,
        role="assistant",
        content="The approval workflow in Druppie ensures that sensitive MCP tool calls require human authorization before execution.",
        agent_id="business_analyst",
        sequence_number=1,
        created_at=now - timedelta(days=2) + timedelta(minutes=1),
    ))


def seed_approvals(db: Session) -> None:
    """Create sample approval records."""
    # Pending approval for the dashboard session
    db.add(Approval(
        id=uuid.uuid4(),
        session_id=SESSION_IDS["dashboard_paused"],
        mcp_server="coding",
        tool_name="make_design",
        required_role="architect",
        status="pending",
        agent_id="business_analyst",
        created_at=now - timedelta(minutes=10),
    ))

    # Approved approval for the todo session
    db.add(Approval(
        id=uuid.uuid4(),
        session_id=SESSION_IDS["todo_completed"],
        mcp_server="coding",
        tool_name="make_design",
        required_role="architect",
        status="approved",
        resolved_by=USER_IDS["architect"],
        resolved_at=now - timedelta(days=6, hours=23),
        agent_id="architect",
        created_at=now - timedelta(days=7),
    ))


def seed(db: Session) -> None:
    """Run all seed functions."""
    # Check if seed data already exists (users are preserved across resets)
    existing = db.query(SessionModel).first()
    if existing:
        print("Database already has session data. Skipping seed.")
        print("Run 'docker compose --profile reset-db run --rm reset-db' first to clear.")
        return

    seed_users(db)
    db.flush()
    seed_projects(db)
    db.flush()
    seed_sessions(db)
    db.flush()
    seed_approvals(db)

    db.commit()
    print("Seed complete:")
    print(f"  - {len(USER_IDS)} users")
    print(f"  - {len(PROJECT_IDS)} projects")
    print(f"  - {len(SESSION_IDS)} sessions (1 completed, 1 active, 1 paused, 1 chat)")
    print(f"  - 2 approvals (1 pending, 1 approved)")
    print(f"  - 1 pending HITL question")


if __name__ == "__main__":
    init_db()
    db = SessionLocal()
    try:
        seed(db)
    finally:
        db.close()
