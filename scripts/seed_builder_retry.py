#!/usr/bin/env python3
"""
Seed script: populate DB + Gitea for builder-agent retry testing.

After a DB reset, run this to instantly get a session where the builder agent
has FAILED so you can test the retry flow without running the full pipeline.

Usage:
    docker compose --profile reset-db run --rm reset-db       # reset DB first
    source venv/bin/activate                                   # activate venv (has psycopg2)
    python scripts/seed_builder_retry.py                       # then seed

Connects to localhost ports (DB: 5432, Gitea: 3100). Run from host, not Docker.
"""

import json
import sys
import uuid
from datetime import datetime, timezone

import httpx
import psycopg2
import psycopg2.extras

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DB_DSN = "postgresql://druppie:druppie_secret@localhost:5533/druppie"
GITEA_URL = "http://localhost:3100"
GITEA_USER = "gitea_admin"
GITEA_PASS = "GiteaAdmin123"
FRONTEND_URL = "http://localhost:5273"

# Fixed UUIDs so the script is idempotent (delete-then-insert)
ADMIN_USER_ID = uuid.UUID("0ff7a3d5-c8a8-4621-bb68-40d9ae2a508f")
PROJECT_ID = uuid.UUID("aaaa0001-0001-0001-0001-000000000001")
SESSION_ID = uuid.UUID("aaaa0002-0002-0002-0002-000000000002")

# Agent run UUIDs (seq 1-9)
RUN_IDS = {
    "router":    uuid.UUID("bbbb0001-0001-0001-0001-000000000001"),
    "planner1":  uuid.UUID("bbbb0002-0002-0002-0002-000000000002"),
    "ba":        uuid.UUID("bbbb0003-0003-0003-0003-000000000003"),
    "planner2":  uuid.UUID("bbbb0004-0004-0004-0004-000000000004"),
    "architect": uuid.UUID("bbbb0005-0005-0005-0005-000000000005"),
    "planner3":  uuid.UUID("bbbb0006-0006-0006-0006-000000000006"),
    "tester":    uuid.UUID("bbbb0007-0007-0007-0007-000000000007"),
    "planner4":  uuid.UUID("bbbb0008-0008-0008-0008-000000000008"),
    "builder":   uuid.UUID("bbbb0009-0009-0009-0009-000000000009"),
}

# LLM call UUIDs (one per agent run)
LLM_IDS = {k: uuid.UUID(f"cccc{i:04d}-{i:04d}-{i:04d}-{i:04d}-{i:012d}")
           for i, k in enumerate(RUN_IDS, start=1)}

# Tool call UUIDs
TC_IDS = {k: uuid.UUID(f"dddd{i:04d}-{i:04d}-{i:04d}-{i:04d}-{i:012d}")
          for i, k in enumerate([
              "set_intent",
              "done_router",
              "make_plan1",
              "done_planner1",
              "done_ba",
              "make_plan2",
              "done_planner2",
              "done_architect",
              "make_plan3",
              "done_planner3",
              "done_tester",
              "make_plan4",
              "done_planner4",
              "execute_coding_task",
          ], start=1)}

# Message UUIDs
MSG_IDS = {k: uuid.UUID(f"eeee{i:04d}-{i:04d}-{i:04d}-{i:04d}-{i:012d}")
           for i, k in enumerate([
               "user_msg",
               "router_summary",
               "planner1_summary",
               "ba_summary",
               "planner2_summary",
               "architect_summary",
               "planner3_summary",
               "tester_summary",
               "planner4_summary",
               "builder_error",
           ], start=1)}

NOW = datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Step 1 — Gitea repo
# ---------------------------------------------------------------------------
def create_gitea_repo() -> dict:
    """Ensure druppie_admin user exists, create repo, return repo info."""
    auth = (GITEA_USER, GITEA_PASS)
    short = uuid.uuid4().hex[:8]
    repo_name = f"todo-app-{short}"

    with httpx.Client(base_url=GITEA_URL, auth=auth, timeout=15) as c:
        # Ensure druppie_admin user exists (admin is reserved in Gitea)
        r = c.get(f"/api/v1/users/druppie_admin")
        if r.status_code == 404:
            r = c.post("/api/v1/admin/users", json={
                "username": "druppie_admin",
                "email": "druppie_admin@druppie.local",
                "password": "DruppieAdmin123!",
                "must_change_password": False,
                "login_name": "druppie_admin",
                "source_id": 0,
            })
            if r.status_code not in (201, 422):
                print(f"  [WARN] Could not create druppie_admin: {r.status_code} {r.text[:200]}")
            else:
                print("  [OK] Created Gitea user druppie_admin")
        else:
            print("  [OK] Gitea user druppie_admin already exists")

        # Create repo under druppie_admin
        r = c.post(f"/api/v1/admin/users/druppie_admin/repos", json={
            "name": repo_name,
            "description": "Todo App - seeded for builder retry testing",
            "private": False,
            "auto_init": True,
            "readme": "Default",
        })
        if r.status_code == 201:
            data = r.json()
            print(f"  [OK] Created repo: {data['html_url']}")
        elif r.status_code in (409, 422):
            print(f"  [OK] Repo {repo_name} already exists")
            data = c.get(f"/api/v1/repos/druppie_admin/{repo_name}").json()
        else:
            print(f"  [ERROR] Failed to create repo: {r.status_code} {r.text[:200]}")
            sys.exit(1)

    return {
        "repo_name": repo_name,
        "repo_owner": "druppie_admin",
        "repo_url": f"{GITEA_URL}/druppie_admin/{repo_name}",
        "clone_url": data.get("clone_url", f"{GITEA_URL}/druppie_admin/{repo_name}.git"),
    }


# ---------------------------------------------------------------------------
# Step 2 — Database population
# ---------------------------------------------------------------------------

# Builder's planned_prompt — realistic content matching what the planner would
# produce after business_analyst → architect → tester have completed.
BUILDER_PLANNED_PROMPT = """\
Implement the Todo App based on the architecture and test specifications.

## Context
The business analyst defined requirements for a simple todo application.
The architect designed a React + Vite frontend with the following structure:
- src/App.jsx — main component with todo list, add form, toggle, delete
- src/components/TodoItem.jsx — individual todo item component
- src/components/TodoForm.jsx — form for adding new todos
- src/hooks/useTodos.js — custom hook for todo state management

The tester has written tests in:
- tests/App.test.jsx — integration tests for the full app
- tests/TodoItem.test.jsx — unit tests for TodoItem component
- tests/TodoForm.test.jsx — unit tests for TodoForm component

## Your Task
1. Read the test files to understand exact expectations
2. Read architecture.md or SPEC.md if available
3. Implement ALL source files to make the tests pass
4. Create package.json with React, Vite, and testing dependencies
5. Create vite.config.js
6. Create Dockerfile for production deployment
7. Use batch_write_files to create all files at once
8. Run the build to verify compilation
9. Call commit_and_push to push all changes
10. Call done() with a summary of what was implemented

## Previous Agent Summaries
Agent router: Classified intent as create_project, created project "todo-app".
Agent planner: Created plan: business_analyst → architect → tester → builder → deployer.
Agent business_analyst: Defined requirements for todo app with CRUD operations, persistence, and responsive design. Created SPEC.md.
Agent planner: Updated plan after BA completion. Next: architect.
Agent architect: Designed React+Vite architecture with component structure, state management via custom hook, and REST-ready data layer. Created architecture.md and technical_design.md.
Agent planner: Updated plan after architect completion. Next: tester.
Agent tester: Generated 12 test files covering App integration, TodoItem unit tests, and TodoForm unit tests. All tests initially fail (TDD red phase). Created test infrastructure with vitest config.
Agent planner: Updated plan after tester completion. Next: builder.\
"""


def populate_db(repo_info: dict):
    """Insert seed records into PostgreSQL."""
    conn = psycopg2.connect(DB_DSN)
    conn.autocommit = False
    cur = conn.cursor()

    try:
        # ------------------------------------------------------------------
        # Clean up any previous seed data (idempotent)
        # ------------------------------------------------------------------
        print("  Cleaning previous seed data...")
        cur.execute("DELETE FROM sessions WHERE id = %s", (str(SESSION_ID),))
        cur.execute("DELETE FROM projects WHERE id = %s", (str(PROJECT_ID),))

        # ------------------------------------------------------------------
        # Look up or create admin user
        # ------------------------------------------------------------------
        cur.execute("SELECT id FROM users WHERE username = 'admin'")
        row = cur.fetchone()
        if row:
            admin_id = row[0]
            print(f"  [OK] Found admin user: {admin_id}")
        else:
            admin_id = str(ADMIN_USER_ID)
            cur.execute(
                """INSERT INTO users (id, username, email, display_name, created_at, updated_at)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (admin_id, "admin", "admin@druppie.local", "Admin User", NOW, NOW),
            )
            cur.execute(
                "INSERT INTO user_roles (user_id, role) VALUES (%s, %s)",
                (admin_id, "admin"),
            )
            print(f"  [OK] Created admin user: {admin_id}")

        admin_id = str(admin_id)

        # ------------------------------------------------------------------
        # Project
        # ------------------------------------------------------------------
        cur.execute(
            """INSERT INTO projects
               (id, name, description, repo_name, repo_owner, repo_url, clone_url,
                owner_id, status, created_at, updated_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                str(PROJECT_ID), "todo-app",
                "A simple todo application — seeded for builder retry testing",
                repo_info["repo_name"], repo_info["repo_owner"],
                repo_info["repo_url"], repo_info["clone_url"],
                admin_id, "active", NOW, NOW,
            ),
        )
        print("  [OK] Inserted project")

        # ------------------------------------------------------------------
        # Session
        # ------------------------------------------------------------------
        cur.execute(
            """INSERT INTO sessions
               (id, user_id, project_id, title, status, intent, language,
                prompt_tokens, completion_tokens, total_tokens,
                created_at, updated_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                str(SESSION_ID), admin_id, str(PROJECT_ID),
                "hi build me a to do app", "failed", "create_project", "en",
                25000, 8000, 33000, NOW, NOW,
            ),
        )
        print("  [OK] Inserted session")

        # ------------------------------------------------------------------
        # Agent runs
        # ------------------------------------------------------------------
        agent_runs = [
            # (key, agent_id, seq, status, error_msg, planned_prompt)
            ("router",    "router",            1, "completed", None, None),
            ("planner1",  "planner",           2, "completed", None, None),
            ("ba",        "business_analyst",   3, "completed", None,
             "Analyze the user request 'build me a to do app' and create a detailed specification document (SPEC.md)."),
            ("planner2",  "planner",           4, "completed", None, None),
            ("architect", "architect",         5, "completed", None,
             "Design the architecture for the todo app based on SPEC.md. Create architecture.md and technical_design.md."),
            ("planner3",  "planner",           6, "completed", None, None),
            ("tester",    "tester",            7, "completed", None,
             "Generate test files for the todo app based on architecture.md and SPEC.md. Write tests that define expected behavior (TDD red phase)."),
            ("planner4",  "planner",           8, "completed", None, None),
            ("builder",   "builder",           9, "failed",
             "Sandbox execution failed: connection timeout after 120s",
             BUILDER_PLANNED_PROMPT),
        ]

        for key, agent_id, seq, status, err, prompt in agent_runs:
            completed_at = NOW if status == "completed" else None
            tokens_p = 3000 if status == "completed" else 0
            tokens_c = 1000 if status == "completed" else 0
            cur.execute(
                """INSERT INTO agent_runs
                   (id, session_id, agent_id, status, error_message,
                    planned_prompt, sequence_number, iteration_count,
                    prompt_tokens, completion_tokens, total_tokens,
                    started_at, completed_at, created_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    str(RUN_IDS[key]), str(SESSION_ID), agent_id, status, err,
                    prompt, seq, 1 if status == "completed" else 0,
                    tokens_p, tokens_c, tokens_p + tokens_c,
                    NOW, completed_at, NOW,
                ),
            )
        print("  [OK] Inserted 9 agent runs")

        # ------------------------------------------------------------------
        # LLM calls (one per agent run, minimal)
        # ------------------------------------------------------------------
        for key in RUN_IDS:
            agent_id = next(a for k, a, *_ in agent_runs if k == key)
            cur.execute(
                """INSERT INTO llm_calls
                   (id, session_id, agent_run_id, provider, model,
                    prompt_tokens, completion_tokens, total_tokens,
                    duration_ms, created_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    str(LLM_IDS[key]), str(SESSION_ID), str(RUN_IDS[key]),
                    "zai", "claude-opus-4-6",
                    3000, 1000, 4000, 2500, NOW,
                ),
            )
        print("  [OK] Inserted 9 LLM calls")

        # ------------------------------------------------------------------
        # Tool calls
        # ------------------------------------------------------------------
        tool_calls = [
            # (tc_key, run_key, llm_key, mcp_server, tool_name, status, arguments, result)
            ("set_intent", "router", "router", "builtin", "set_intent", "completed",
             {"intent": "create_project", "project_name": "todo-app"},
             "Intent set to create_project"),
            ("done_router", "router", "router", "builtin", "done", "completed",
             {"summary": "Agent router: Classified intent as create_project, created project 'todo-app'."},
             "Agent completed"),
            ("make_plan1", "planner1", "planner1", "builtin", "make_plan", "completed",
             {"steps": [
                 {"agent_id": "business_analyst", "prompt": "Analyze the user request 'build me a to do app' and create a detailed specification document (SPEC.md)."},
                 {"agent_id": "architect", "prompt": "Design the architecture for the todo app based on SPEC.md."},
                 {"agent_id": "tester", "prompt": "Generate test files for the todo app."},
                 {"agent_id": "builder", "prompt": "Implement the code to pass the tests."},
                 {"agent_id": "deployer", "prompt": "Deploy the todo app."},
             ]},
             "Plan created with 5 steps"),
            ("done_planner1", "planner1", "planner1", "builtin", "done", "completed",
             {"summary": "Agent planner: Created plan: business_analyst → architect → tester → builder → deployer."},
             "Agent completed"),
            ("done_ba", "ba", "ba", "builtin", "done", "completed",
             {"summary": "Agent business_analyst: Defined requirements for todo app with CRUD operations, localStorage persistence, and responsive design. Created SPEC.md with user stories and acceptance criteria."},
             "Agent completed"),
            ("make_plan2", "planner2", "planner2", "builtin", "make_plan", "completed",
             {"steps": [
                 {"agent_id": "architect", "prompt": "Design the architecture for the todo app based on SPEC.md. Create architecture.md and technical_design.md."},
                 {"agent_id": "tester", "prompt": "Generate test files for the todo app based on architecture.md and SPEC.md."},
                 {"agent_id": "builder", "prompt": "Implement the code to pass the tests."},
                 {"agent_id": "deployer", "prompt": "Deploy the todo app."},
             ]},
             "Plan updated after BA completion"),
            ("done_planner2", "planner2", "planner2", "builtin", "done", "completed",
             {"summary": "Agent planner: Updated plan after BA completion. Next: architect."},
             "Agent completed"),
            ("done_architect", "architect", "architect", "builtin", "done", "completed",
             {"summary": "Agent architect: Designed React+Vite architecture with component structure, custom hook state management, and REST-ready data layer. Created architecture.md and technical_design.md."},
             "Agent completed"),
            ("make_plan3", "planner3", "planner3", "builtin", "make_plan", "completed",
             {"steps": [
                 {"agent_id": "tester", "prompt": "Generate test files for the todo app based on architecture.md and SPEC.md. Write tests that define expected behavior (TDD red phase)."},
                 {"agent_id": "builder", "prompt": "Implement the code to pass the tests."},
                 {"agent_id": "deployer", "prompt": "Deploy the todo app."},
             ]},
             "Plan updated after architect completion"),
            ("done_planner3", "planner3", "planner3", "builtin", "done", "completed",
             {"summary": "Agent planner: Updated plan after architect completion. Next: tester."},
             "Agent completed"),
            ("done_tester", "tester", "tester", "builtin", "done", "completed",
             {"summary": "Agent tester: Generated 12 test files covering App integration, TodoItem unit tests, and TodoForm unit tests. All tests initially fail (TDD red phase). Created vitest config and test infrastructure."},
             "Agent completed"),
            ("make_plan4", "planner4", "planner4", "builtin", "make_plan", "completed",
             {"steps": [
                 {"agent_id": "builder", "prompt": BUILDER_PLANNED_PROMPT},
                 {"agent_id": "deployer", "prompt": "Deploy the todo app."},
             ]},
             "Plan updated after tester completion"),
            ("done_planner4", "planner4", "planner4", "builtin", "done", "completed",
             {"summary": "Agent planner: Updated plan after tester completion. Next: builder."},
             "Agent completed"),
            ("execute_coding_task", "builder", "builder", "builtin", "execute_coding_task", "failed",
             {"prompt": "Read test files, implement all source code to make tests pass, create package.json, vite.config.js, and Dockerfile."},
             None),
        ]

        for tc_key, run_key, llm_key, mcp, tool, status, args, result in tool_calls:
            tc_index = 0
            # done calls are typically index 1 (after make_plan or set_intent)
            if tool == "done" and tc_key != "done_ba":
                tc_index = 1
            cur.execute(
                """INSERT INTO tool_calls
                   (id, session_id, agent_run_id, llm_call_id,
                    mcp_server, tool_name, tool_call_index,
                    arguments, status, result, error_message,
                    created_at, executed_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    str(TC_IDS[tc_key]), str(SESSION_ID),
                    str(RUN_IDS[run_key]), str(LLM_IDS[llm_key]),
                    mcp, tool, tc_index,
                    json.dumps(args), status, result,
                    "Sandbox execution failed: connection timeout after 120s" if status == "failed" else None,
                    NOW, NOW if status == "completed" else None,
                ),
            )
        print(f"  [OK] Inserted {len(tool_calls)} tool calls")

        # ------------------------------------------------------------------
        # Messages
        # ------------------------------------------------------------------
        messages = [
            # (msg_key, run_key_or_none, role, content, agent_id, seq)
            ("user_msg", None, "user",
             "hi build me a to do app", None, 0),
            ("router_summary", "router", "assistant",
             "Agent router: Classified intent as create_project, created project 'todo-app'.",
             "router", 1),
            ("planner1_summary", "planner1", "assistant",
             "Agent planner: Created plan: business_analyst → architect → tester → builder → deployer.",
             "planner", 2),
            ("ba_summary", "ba", "assistant",
             "Agent business_analyst: Defined requirements for todo app with CRUD operations, localStorage persistence, and responsive design. Created SPEC.md with user stories and acceptance criteria.",
             "business_analyst", 3),
            ("planner2_summary", "planner2", "assistant",
             "Agent planner: Updated plan after BA completion. Next: architect.",
             "planner", 4),
            ("architect_summary", "architect", "assistant",
             "Agent architect: Designed React+Vite architecture with component structure, custom hook state management, and REST-ready data layer. Created architecture.md and technical_design.md.",
             "architect", 5),
            ("planner3_summary", "planner3", "assistant",
             "Agent planner: Updated plan after architect completion. Next: tester.",
             "planner", 6),
            ("tester_summary", "tester", "assistant",
             "Agent tester: Generated 12 test files covering App integration, TodoItem unit tests, and TodoForm unit tests. All tests initially fail (TDD red phase). Created vitest config and test infrastructure.",
             "tester", 7),
            ("planner4_summary", "planner4", "assistant",
             "Agent planner: Updated plan after tester completion. Next: builder.",
             "planner", 8),
            ("builder_error", "builder", "assistant",
             "Agent builder: Failed — Sandbox execution failed: connection timeout after 120s",
             "builder", 9),
        ]

        for msg_key, run_key, role, content, agent_id, seq in messages:
            run_id = str(RUN_IDS[run_key]) if run_key else None
            cur.execute(
                """INSERT INTO messages
                   (id, session_id, agent_run_id, role, content,
                    agent_id, sequence_number, created_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    str(MSG_IDS[msg_key]), str(SESSION_ID), run_id,
                    role, content, agent_id, seq, NOW,
                ),
            )
        print(f"  [OK] Inserted {len(messages)} messages")

        conn.commit()
        print("  [OK] All records committed")

    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    print("=" * 60)
    print("Druppie — Seed: Builder Retry Test Data")
    print("=" * 60)

    # Step 1: Gitea
    print("\n[STEP 1] Creating Gitea repo...")
    repo_info = create_gitea_repo()

    # Step 2: Database
    print("\n[STEP 2] Populating database...")
    populate_db(repo_info)

    # Step 3: Summary
    session_url = f"{FRONTEND_URL}/chat?session={SESSION_ID}&mode=inspect"
    print("\n" + "=" * 60)
    print("[DONE] Seed data created successfully!")
    print("=" * 60)
    print()
    print(f"  Session ID:  {SESSION_ID}")
    print(f"  Session URL: {session_url}")
    print(f"  Gitea repo:  {repo_info['repo_url']}")
    print(f"  Project:     todo-app")
    print()
    print("  Next steps:")
    print("    1. Login as admin / Admin123!")
    print(f"    2. Open {session_url}")
    print("    3. Click retry on the failed builder agent run")
    print("    4. Verify no 'InFailedSqlTransaction' error")
    print()
    print("=" * 60)


if __name__ == "__main__":
    main()
