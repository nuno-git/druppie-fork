#!/usr/bin/env python3
"""
Seed script: create a deployer-retryable session with a real template repo.

Adds ONE session to the existing DB (does NOT reset). The session has:
- All agents through builder completed
- Deployer agent FAILED (retryable)
- A real Gitea repo with the project template + fake builder code pushed

Usage:
    source venv/bin/activate
    python scripts/seed_deployer_test.py

Connects to localhost ports (DB: 5533, Gitea: 3100). Run from host, not Docker.
"""

import base64
import json
import os
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import psycopg2

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DB_DSN = os.environ.get(
    "DB_DSN", "postgresql://druppie:druppie_secret@localhost:5634/druppie"
)
GITEA_URL = os.environ.get("GITEA_URL", "http://localhost:3200")
GITEA_USER = "gitea_admin"
GITEA_PASS = "GiteaAdmin123"
FRONTEND_URL = "http://localhost:5273"

# Template directory (relative to this script)
TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "druppie" / "templates" / "project"

NOW = datetime.now(timezone.utc)
NS = 0xD001  # Namespace for deployer test session


def _ts(hours_ago: float = 0) -> datetime:
    return NOW - timedelta(hours=hours_ago)


def _uid(namespace: int, index: int) -> str:
    return str(uuid.UUID(f"{namespace:04x}0000-{index:04x}-4000-8000-{index:012x}"))


# ---------------------------------------------------------------------------
# Gitea helpers
# ---------------------------------------------------------------------------
def ensure_gitea_user(client: httpx.Client):
    """Ensure druppie_admin user exists."""
    r = client.get("/api/v1/users/druppie_admin")
    if r.status_code == 404:
        r = client.post("/api/v1/admin/users", json={
            "username": "druppie_admin",
            "email": "druppie_admin@druppie.local",
            "password": "DruppieAdmin123!",
            "must_change_password": False,
            "login_name": "druppie_admin",
            "source_id": 0,
        })
        if r.status_code not in (201, 422):
            print(f"  [WARN] Could not create druppie_admin: {r.status_code}")
        else:
            print("  [OK] Created Gitea user druppie_admin")
    else:
        print("  [OK] Gitea user druppie_admin already exists")


def create_repo(client: httpx.Client, name: str) -> dict:
    """Create a Gitea repo under druppie_admin, return repo info."""
    r = client.post("/api/v1/admin/users/druppie_admin/repos", json={
        "name": name,
        "description": "Deployer test — seeded with project template",
        "private": False,
        "auto_init": True,
        "readme": "Default",
        "default_branch": "main",
    })
    if r.status_code == 201:
        data = r.json()
        print(f"  [OK] Created repo: druppie_admin/{name}")
    elif r.status_code in (409, 422):
        # Already exists — fetch it
        data = client.get(f"/api/v1/repos/druppie_admin/{name}").json()
        print(f"  [OK] Repo already exists: druppie_admin/{name}")
    else:
        print(f"  [ERROR] Failed to create repo {name}: {r.status_code} {r.text}")
        sys.exit(1)
    return {
        "repo_name": name,
        "repo_owner": "druppie_admin",
        "repo_url": f"{GITEA_URL}/druppie_admin/{name}",
        "clone_url": data.get("clone_url", f"{GITEA_URL}/druppie_admin/{name}.git"),
    }


def push_file(client: httpx.Client, repo_name: str, path: str, content: str, message: str):
    """Push a single file to the repo via Gitea API."""
    encoded = base64.b64encode(content.encode()).decode()
    r = client.post(
        f"/api/v1/repos/druppie_admin/{repo_name}/contents/{path}",
        json={"content": encoded, "message": message},
    )
    if r.status_code in (200, 201):
        return True
    elif r.status_code == 422:
        # File already exists — update it
        # First get the SHA
        gr = client.get(f"/api/v1/repos/druppie_admin/{repo_name}/contents/{path}")
        if gr.status_code == 200:
            sha = gr.json().get("sha")
            r2 = client.put(
                f"/api/v1/repos/druppie_admin/{repo_name}/contents/{path}",
                json={"content": encoded, "message": message, "sha": sha},
            )
            return r2.status_code in (200, 201)
    print(f"    [WARN] Failed to push {path}: {r.status_code}")
    return False


def push_template_files(client: httpx.Client, repo_name: str):
    """Push all project template files to the repo."""
    if not TEMPLATE_DIR.is_dir():
        print(f"  [ERROR] Template dir not found: {TEMPLATE_DIR}")
        sys.exit(1)

    count = 0
    for file_path in sorted(TEMPLATE_DIR.rglob("*")):
        if not file_path.is_file():
            continue
        if "__pycache__" in str(file_path) or file_path.suffix == ".pyc":
            continue

        relative = str(file_path.relative_to(TEMPLATE_DIR))
        try:
            content = file_path.read_text()
        except UnicodeDecodeError:
            continue

        if push_file(client, repo_name, relative, content,
                      f"feat: scaffold project template ({relative})"):
            count += 1

    print(f"  [OK] Pushed {count} template files")
    return count


# ---------------------------------------------------------------------------
# Deployer planned prompt — references compose_up workflow
# ---------------------------------------------------------------------------
DEPLOYER_PLANNED_PROMPT = """\
Build and deploy the FAQ web application using Docker Compose. \
Ask user if it looks good via hitl_ask_question. \
Include feedback in done() as 'USER FEEDBACK: <response>'.

## Context
The builder agent has implemented a FAQ app with categories and questions.
The repo contains a working Dockerfile and docker-compose.yaml from the
project template, plus the builder's implementation code.

## Previous Agent Summaries
Agent router: Classified intent as create_project, created project "faq-webapp".
Agent planner: Created plan: business_analyst → architect → tester → builder → deployer.
Agent business_analyst: Defined requirements for FAQ app with categories and questions.
Agent architect: Designed Flask app with PostgreSQL, SQLAlchemy models, React + shadcn frontend.
Agent tester: Generated test suite for FAQ models and API routes.
Agent builder: Implemented FAQ app — 2 models, 3 API routes, React frontend. All tests pass. \
Build verification passed (docker compose up + health check OK). Pushed to main.

## Your Task
1. Check for existing containers (docker_list_containers)
2. Deploy with docker_compose_up (branch: main)
3. Verify health check passes
4. Ask user for feedback via hitl_ask_question
5. Report deployment URL with USER FEEDBACK in done()"""

BUILDER_PLANNED_PROMPT = """\
Implement the FAQ web application based on the architecture and test specifications.

## Context
The architect designed a Flask app with:
- app/models.py — Category and Question SQLAlchemy models
- app/routes.py — Flask API routes returning JSON
- frontend/src/ — React + shadcn/ui components
- PostgreSQL database via docker-compose.yaml

The tester wrote tests for model creation and route responses.

## Your Task
1. Read test files and architecture docs
2. Implement models, routes, and React components
3. Run tests: pip install -r requirements.txt && pytest -v
4. If Docker available: docker compose up -d --build && verify /health
5. git add, commit, push"""


# ---------------------------------------------------------------------------
# Session definition
# ---------------------------------------------------------------------------
SESSION = {
    "ns": NS,
    "title": "build me a FAQ page for my woonboten company",
    "project_name": "faq-webapp",
    "repo_name": "faq-webapp-deployer-test",
    "status": "failed",
    "intent": "create_project",
    "hours_ago": 0.3,
    "agents": [
        ("router",           "completed", None, None),
        ("planner",          "completed", None, None),
        ("business_analyst", "completed", None,
         "Analyze requirements for an FAQ page: categories, questions, search."),
        ("planner",          "completed", None, None),
        ("architect",        "completed", None,
         "Design Flask app with Category/Question models, React + shadcn frontend."),
        ("planner",          "completed", None, None),
        ("tester",           "completed", None,
         "Generate test suite for FAQ models and route responses."),
        ("planner",          "completed", None, None),
        ("builder",          "completed", None, BUILDER_PLANNED_PROMPT),
        ("planner",          "completed", None, None),
        ("deployer",         "failed",
         "Sandbox execution failed: MCP tool docker:build not found in agent tool list",
         DEPLOYER_PLANNED_PROMPT),
        ("planner",          "pending",  None, None),
    ],
}


# ---------------------------------------------------------------------------
# Agent summary generator
# ---------------------------------------------------------------------------
def _agent_summary(agent_id: str, planner_count: int) -> str:
    s = SESSION
    name = s["project_name"]
    summaries = {
        "router": f"Classified intent as {s['intent']}, created project '{name}'.",
        "planner": f"Updated execution plan (iteration {planner_count}). Proceeding to next agent.",
        "business_analyst": f"Analyzed requirements for '{s['title']}'. Created SPEC.md with user stories.",
        "architect": f"Designed Flask + React architecture for {name} with Category/Question models.",
        "tester": f"Generated test suite for {name}. All tests initially fail (TDD red phase).",
        "builder": (
            f"Implemented {name}: 2 models (Category, Question), 3 API routes, React frontend. "
            "All 8 tests passing. Build verification passed. Code pushed to main."
        ),
        "deployer": f"Deployed {name} via docker compose. Health check passed.",
    }
    return f"Agent {agent_id}: {summaries.get(agent_id, f'Completed task for {name}.')}"


# ---------------------------------------------------------------------------
# Database population
# ---------------------------------------------------------------------------
def populate_db(repo_info: dict):
    conn = psycopg2.connect(DB_DSN)
    conn.autocommit = False
    cur = conn.cursor()

    try:
        ns = SESSION["ns"]
        session_id = _uid(ns, 0)
        project_id = _uid(ns, 9999)
        base_ts = _ts(SESSION["hours_ago"])
        agents = SESSION["agents"]

        # -- Clean previous run of THIS seed only (respect FK order) --
        print("  Cleaning previous deployer-test seed data...")
        cur.execute(
            "DELETE FROM questions WHERE tool_call_id IN "
            "(SELECT id FROM tool_calls WHERE session_id = %s)", (session_id,))
        cur.execute(
            "DELETE FROM approvals WHERE tool_call_id IN "
            "(SELECT id FROM tool_calls WHERE session_id = %s)", (session_id,))
        cur.execute("DELETE FROM tool_calls WHERE session_id = %s", (session_id,))
        cur.execute("DELETE FROM llm_calls WHERE session_id = %s", (session_id,))
        cur.execute("DELETE FROM messages WHERE session_id = %s", (session_id,))
        cur.execute("DELETE FROM agent_runs WHERE session_id = %s", (session_id,))
        cur.execute("DELETE FROM sessions WHERE id = %s", (session_id,))
        cur.execute("DELETE FROM projects WHERE id = %s", (project_id,))

        # -- Find admin user --
        cur.execute("SELECT id FROM users WHERE username = 'admin'")
        row = cur.fetchone()
        if not row:
            print("  [ERROR] Admin user not found. Run the app first to create users.")
            sys.exit(1)
        admin_id = str(row[0])
        print(f"  [OK] Found admin user: {admin_id}")

        # -- Project --
        cur.execute(
            """INSERT INTO projects
               (id, name, description, repo_name, repo_owner, repo_url, clone_url,
                owner_id, status, created_at, updated_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (project_id, SESSION["project_name"],
             f"Seeded: {SESSION['title']}",
             repo_info["repo_name"], repo_info["repo_owner"],
             repo_info["repo_url"], repo_info["clone_url"],
             admin_id, "active", base_ts, base_ts),
        )

        # -- Session --
        completed_agents = [a for a in agents if a[1] == "completed"]
        tok_p = len(completed_agents) * 3000
        tok_c = len(completed_agents) * 1000
        cur.execute(
            """INSERT INTO sessions
               (id, user_id, project_id, title, status, intent, language,
                prompt_tokens, completion_tokens, total_tokens,
                created_at, updated_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (session_id, admin_id, project_id,
             SESSION["title"], SESSION["status"], SESSION["intent"], "en",
             tok_p, tok_c, tok_p + tok_c, base_ts, base_ts),
        )

        # -- User message --
        cur.execute(
            """INSERT INTO messages
               (id, session_id, agent_run_id, role, content,
                agent_id, sequence_number, created_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
            (_uid(ns, 5000), session_id, None, "user", SESSION["title"], None, 0, base_ts),
        )

        # -- Agent runs, LLM calls, tool calls, messages --
        planner_count = 0
        total_runs = 0
        total_tc = 0

        for seq_idx, (agent_id, status, error_msg, planned_prompt) in enumerate(agents):
            seq = seq_idx + 1
            run_id = _uid(ns, seq)
            run_ts = base_ts + timedelta(minutes=seq * 2)

            if agent_id == "planner":
                planner_count += 1

            completed_at = run_ts if status == "completed" else None
            is_active = status in ("completed", "failed", "running")
            tok_p_run = 3000 if status == "completed" else (1500 if status in ("running", "failed") else 0)
            tok_c_run = 1000 if status == "completed" else 0

            cur.execute(
                """INSERT INTO agent_runs
                   (id, session_id, agent_id, status, error_message,
                    planned_prompt, sequence_number, iteration_count,
                    prompt_tokens, completion_tokens, total_tokens,
                    started_at, completed_at, created_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (run_id, session_id, agent_id, status, error_msg,
                 planned_prompt, seq,
                 1 if status in ("completed", "failed") else 0,
                 tok_p_run, tok_c_run, tok_p_run + tok_c_run,
                 run_ts if is_active else None, completed_at, run_ts),
            )
            total_runs += 1

            # LLM call for active agents
            llm_id = _uid(ns, 2000 + seq)
            if is_active:
                cur.execute(
                    """INSERT INTO llm_calls
                       (id, session_id, agent_run_id, provider, model,
                        prompt_tokens, completion_tokens, total_tokens,
                        duration_ms, created_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (llm_id, session_id, run_id,
                     "zai", "glm-4.7",
                     tok_p_run, tok_c_run, tok_p_run + tok_c_run,
                     random.randint(1500, 8000), run_ts),
                )

            # Tool calls
            if status == "completed":
                tc_idx = 0

                # Router: set_intent
                if agent_id == "router":
                    cur.execute(
                        """INSERT INTO tool_calls
                           (id, session_id, agent_run_id, llm_call_id,
                            mcp_server, tool_name, tool_call_index,
                            arguments, status, result, created_at, executed_at)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                        (_uid(ns, 3000 + seq * 10), session_id, run_id, llm_id,
                         "builtin", "set_intent", 0,
                         json.dumps({"intent": SESSION["intent"],
                                     "project_name": SESSION["project_name"]}),
                         "completed", f"Intent set to {SESSION['intent']}",
                         run_ts, run_ts),
                    )
                    total_tc += 1
                    tc_idx = 1

                # Planner: make_plan
                if agent_id == "planner":
                    remaining = [(a, p) for a, st, _, p in agents[seq_idx + 1:]
                                 if a != "planner"]
                    steps = [{"agent_id": a, "prompt": p or f"Execute {a} tasks."}
                             for a, p in remaining[:4]]
                    if steps:
                        cur.execute(
                            """INSERT INTO tool_calls
                               (id, session_id, agent_run_id, llm_call_id,
                                mcp_server, tool_name, tool_call_index,
                                arguments, status, result, created_at, executed_at)
                               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                            (_uid(ns, 3000 + seq * 10), session_id, run_id, llm_id,
                             "builtin", "make_plan", 0,
                             json.dumps({"steps": steps}),
                             "completed", f"Plan created with {len(steps)} steps",
                             run_ts, run_ts),
                        )
                        total_tc += 1
                        tc_idx = 1

                # done() call
                summary = _agent_summary(agent_id, planner_count)
                cur.execute(
                    """INSERT INTO tool_calls
                       (id, session_id, agent_run_id, llm_call_id,
                        mcp_server, tool_name, tool_call_index,
                        arguments, status, result, created_at, executed_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (_uid(ns, 3000 + seq * 10 + 1), session_id, run_id, llm_id,
                     "builtin", "done", tc_idx,
                     json.dumps({"summary": summary}),
                     "completed", "Agent completed",
                     run_ts, run_ts),
                )
                total_tc += 1

                # Assistant message
                cur.execute(
                    """INSERT INTO messages
                       (id, session_id, agent_run_id, role, content,
                        agent_id, sequence_number, created_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (_uid(ns, 5000 + seq), session_id, run_id,
                     "assistant", summary, agent_id, seq, run_ts),
                )

            elif status == "failed":
                # Failed tool call
                tool_name = "execute_coding_task" if agent_id in ("builder", "deployer") else "done"
                cur.execute(
                    """INSERT INTO tool_calls
                       (id, session_id, agent_run_id, llm_call_id,
                        mcp_server, tool_name, tool_call_index,
                        arguments, status, result, error_message,
                        created_at, executed_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (_uid(ns, 3000 + seq * 10), session_id, run_id, llm_id,
                     "builtin", tool_name, 0,
                     json.dumps({"prompt": (planned_prompt or "")[:200]}),
                     "failed", None, error_msg,
                     run_ts, None),
                )
                total_tc += 1

                # Error message
                cur.execute(
                    """INSERT INTO messages
                       (id, session_id, agent_run_id, role, content,
                        agent_id, sequence_number, created_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (_uid(ns, 5000 + seq), session_id, run_id,
                     "assistant",
                     f"Agent {agent_id}: Failed — {error_msg}",
                     agent_id, seq, run_ts),
                )

        conn.commit()
        print(f"  [OK] Inserted 1 session, {total_runs} agent runs, {total_tc} tool calls")

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
    print("Druppie — Seed: Deployer Retry Test")
    print("=" * 60)

    # Step 1: Gitea repo with template files
    print("\n[STEP 1] Creating Gitea repo with project template...")
    with httpx.Client(base_url=GITEA_URL, auth=(GITEA_USER, GITEA_PASS), timeout=15) as c:
        try:
            r = c.get("/api/v1/version")
            r.raise_for_status()
        except (httpx.ConnectError, httpx.ConnectTimeout):
            print(f"  [ERROR] Gitea not reachable at {GITEA_URL}")
            print("  Make sure infra is running: docker compose --profile infra up -d")
            sys.exit(1)
        ensure_gitea_user(c)
        repo_info = create_repo(c, SESSION["repo_name"])

        print("\n  Pushing project template files...")
        push_template_files(c, repo_info["repo_name"])

    # Step 2: Database
    print(f"\n[STEP 2] Populating database (1 session, additive — not resetting DB)...")
    populate_db(repo_info)

    # Step 3: Summary
    session_id = _uid(NS, 0)
    session_url = f"{FRONTEND_URL}/chat?session={session_id}&mode=inspect"
    deployer_run_id = None
    for seq_idx, (agent_id, status, _, _) in enumerate(SESSION["agents"]):
        if agent_id == "deployer":
            deployer_run_id = _uid(NS, seq_idx + 1)
            break

    print("\n" + "=" * 60)
    print("[DONE] Deployer test session created!")
    print("=" * 60)
    print()
    print(f"  Session ID:    {session_id}")
    print(f"  Session URL:   {session_url}")
    print(f"  Deployer run:  {deployer_run_id}")
    print(f"  Gitea repo:    {repo_info['repo_url']}")
    print()
    print("  Session state:")
    for seq_idx, (agent_id, status, err, _) in enumerate(SESSION["agents"]):
        marker = {"completed": "OK", "failed": "FAIL", "pending": "...", "running": ">>"}
        print(f"    [{marker.get(status, '?'):4s}] {agent_id:20s} {status}")
    print()
    print("  The deployer failed with: 'MCP tool docker:build not found'")
    print("  (This simulates the old deployer using build+run before the compose update)")
    print()
    print("  To test:")
    print("    1. Login as admin / Admin123!")
    print(f"    2. Open {session_url}")
    print("    3. Click retry on the failed deployer agent run")
    print("    4. The deployer should now use compose_up instead of build+run")
    print()
    print("=" * 60)


if __name__ == "__main__":
    main()
