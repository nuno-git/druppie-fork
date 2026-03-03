#!/usr/bin/env python3
"""
Seed script: populate DB + Gitea with realistic session data.

Creates ~10 sessions in various states so the sidebar and dashboard look
realistic, plus a specific "builder failed" session for retry testing.

Usage:
    docker compose --profile reset-db run --rm reset-db       # reset DB first
    source venv/bin/activate                                   # activate venv (has psycopg2)
    python scripts/seed_builder_retry.py                       # then seed

Connects to localhost ports (DB: 5533, Gitea: 3100). Run from host, not Docker.
"""

import json
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import psycopg2

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DB_DSN = "postgresql://druppie:druppie_secret@localhost:5533/druppie"
GITEA_URL = "http://localhost:3100"
GITEA_USER = "gitea_admin"
GITEA_PASS = "GiteaAdmin123"
FRONTEND_URL = "http://localhost:5273"

NOW = datetime.now(timezone.utc)


def _ts(hours_ago: float = 0) -> datetime:
    """Return a timestamp `hours_ago` before NOW."""
    return NOW - timedelta(hours=hours_ago)


def _uid(namespace: int, index: int) -> str:
    """Deterministic UUID from namespace + index (idempotent)."""
    return str(uuid.UUID(f"{namespace:04x}0000-{index:04x}-4000-8000-{index:012x}"))


# ---------------------------------------------------------------------------
# Gitea helpers
# ---------------------------------------------------------------------------
def ensure_gitea_user(client: httpx.Client):
    """Ensure druppie_admin user exists in Gitea."""
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


def create_gitea_repo(client: httpx.Client, name: str) -> dict:
    """Create a Gitea repo, return repo info dict."""
    short = uuid.uuid4().hex[:8]
    repo_name = f"{name}-{short}"
    r = client.post("/api/v1/admin/users/druppie_admin/repos", json={
        "name": repo_name,
        "description": f"{name} — seeded test data",
        "private": False,
        "auto_init": True,
        "readme": "Default",
    })
    if r.status_code == 201:
        data = r.json()
        print(f"  [OK] Created repo: druppie_admin/{repo_name}")
    elif r.status_code in (409, 422):
        data = client.get(f"/api/v1/repos/druppie_admin/{repo_name}").json()
    else:
        print(f"  [ERROR] Failed to create repo {repo_name}: {r.status_code}")
        sys.exit(1)
    return {
        "repo_name": repo_name,
        "repo_owner": "druppie_admin",
        "repo_url": f"{GITEA_URL}/druppie_admin/{repo_name}",
        "clone_url": data.get("clone_url", f"{GITEA_URL}/druppie_admin/{repo_name}.git"),
    }


# ---------------------------------------------------------------------------
# Session definitions — each dict drives one session + project + agents
# ---------------------------------------------------------------------------
# Agent run tuples: (agent_id, status, error_message, planned_prompt_snippet)
# "completed" agents get a done tool call + summary message automatically.
# "failed" agents get an error tool call.
# "pending" agents get no tool calls / LLM calls.
# "running" agents get one LLM call but no tool calls yet.

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
Agent planner: Updated plan after tester completion. Next: builder."""

SESSIONS = [
    # ── 0: The main builder-retry session ──────────────────────────
    {
        "ns": 0xA000,
        "title": "hi build me a to do app",
        "project_name": "todo-app",
        "status": "failed",
        "intent": "create_project",
        "hours_ago": 0.5,
        "agents": [
            ("router",           "completed", None, None),
            ("planner",          "completed", None, None),
            ("business_analyst", "completed", None, "Analyze the user request and create SPEC.md."),
            ("planner",          "completed", None, None),
            ("architect",        "completed", None, "Design architecture for the todo app. Create architecture.md."),
            ("planner",          "completed", None, None),
            ("tester",           "completed", None, "Generate test files for TDD red phase."),
            ("planner",          "completed", None, None),
            ("builder",          "failed",
             "Sandbox execution failed: connection timeout after 120s",
             BUILDER_PLANNED_PROMPT),
            ("planner",          "pending",  None, None),
        ],
    },
    # ── 1: Completed weather app ───────────────────────────────────
    {
        "ns": 0xA001,
        "title": "build me a weather dashboard",
        "project_name": "weather-dashboard",
        "status": "completed",
        "intent": "create_project",
        "hours_ago": 26,
        "agents": [
            ("router",           "completed", None, None),
            ("planner",          "completed", None, None),
            ("business_analyst", "completed", None, "Write SPEC.md for weather dashboard with 5-day forecast."),
            ("planner",          "completed", None, None),
            ("architect",        "completed", None, "Design React SPA with OpenWeatherMap API integration."),
            ("planner",          "completed", None, None),
            ("tester",           "completed", None, "Create tests for API service, forecast components."),
            ("planner",          "completed", None, None),
            ("builder",          "completed", None, "Implement weather dashboard to pass all 18 tests."),
            ("planner",          "completed", None, None),
            ("deployer",         "completed", None, "Deploy weather dashboard container on port 3001."),
        ],
    },
    # ── 2: Calculator — stuck at architect approval ────────────────
    {
        "ns": 0xA002,
        "title": "create a scientific calculator",
        "project_name": "calculator",
        "status": "paused_approval",
        "intent": "create_project",
        "hours_ago": 3,
        "agents": [
            ("router",           "completed", None, None),
            ("planner",          "completed", None, None),
            ("business_analyst", "completed", None, "Define calculator requirements: basic + scientific modes."),
            ("planner",          "completed", None, None),
            ("architect",        "running",   None, "Design the calculator architecture with expression parser."),
        ],
    },
    # ── 3: Blog platform — tester running ──────────────────────────
    {
        "ns": 0xA003,
        "title": "make a blog platform with markdown support",
        "project_name": "blog-platform",
        "status": "active",
        "intent": "create_project",
        "hours_ago": 1.5,
        "agents": [
            ("router",           "completed", None, None),
            ("planner",          "completed", None, None),
            ("business_analyst", "completed", None, "Write SPEC for blog with markdown rendering and tags."),
            ("planner",          "completed", None, None),
            ("architect",        "completed", None, "Design Next.js blog with MDX and SQLite storage."),
            ("planner",          "completed", None, None),
            ("tester",           "running",   None, "Generate tests for markdown renderer and post CRUD."),
        ],
    },
    # ── 4: Chat app — failed at router ─────────────────────────────
    {
        "ns": 0xA004,
        "title": "asdfghjkl",
        "project_name": None,  # no project — router failed
        "status": "failed",
        "intent": None,
        "hours_ago": 48,
        "agents": [
            ("router", "failed", "LLM returned empty response after 3 retries", None),
        ],
    },
    # ── 5: General chat — completed quickly ────────────────────────
    {
        "ns": 0xA005,
        "title": "what agents do you have?",
        "project_name": None,
        "status": "completed",
        "intent": "general_chat",
        "hours_ago": 72,
        "agents": [
            ("router", "completed", None, None),
        ],
    },
    # ── 6: E-commerce — completed through builder ──────────────────
    {
        "ns": 0xA006,
        "title": "build an e-commerce product page",
        "project_name": "ecommerce-page",
        "status": "completed",
        "intent": "create_project",
        "hours_ago": 50,
        "agents": [
            ("router",           "completed", None, None),
            ("planner",          "completed", None, None),
            ("architect",        "completed", None, "Design product page with cart and Stripe checkout."),
            ("planner",          "completed", None, None),
            ("tester",           "completed", None, "Write tests for product display, cart, checkout flow."),
            ("planner",          "completed", None, None),
            ("builder",          "completed", None, "Implement e-commerce page, all 14 tests passing."),
            ("planner",          "completed", None, None),
            ("deployer",         "completed", None, "Deployed e-commerce container on port 3002."),
        ],
    },
    # ── 7: Kanban board — BA running ───────────────────────────────
    {
        "ns": 0xA007,
        "title": "create a kanban board with drag and drop",
        "project_name": "kanban-board",
        "status": "active",
        "intent": "create_project",
        "hours_ago": 0.1,
        "agents": [
            ("router",           "completed", None, None),
            ("planner",          "completed", None, None),
            ("business_analyst", "running",   None, "Analyze kanban requirements: columns, cards, drag-drop."),
        ],
    },
    # ── 8: Portfolio site — completed, short pipeline ──────────────
    {
        "ns": 0xA008,
        "title": "build a portfolio website for me",
        "project_name": "portfolio-site",
        "status": "completed",
        "intent": "create_project",
        "hours_ago": 120,
        "agents": [
            ("router",           "completed", None, None),
            ("planner",          "completed", None, None),
            ("business_analyst", "completed", None, "Define portfolio requirements: about, projects, contact."),
            ("planner",          "completed", None, None),
            ("architect",        "completed", None, "Design static HTML/CSS portfolio with responsive layout."),
            ("planner",          "completed", None, None),
            ("builder",          "completed", None, "Built portfolio with 3 pages, responsive CSS grid."),
            ("planner",          "completed", None, None),
            ("deployer",         "completed", None, "Deployed portfolio on port 3003."),
        ],
    },
    # ── 9: Recipe app — failed at builder (different error) ────────
    {
        "ns": 0xA009,
        "title": "make a recipe sharing app",
        "project_name": "recipe-app",
        "status": "failed",
        "intent": "create_project",
        "hours_ago": 6,
        "agents": [
            ("router",           "completed", None, None),
            ("planner",          "completed", None, None),
            ("business_analyst", "completed", None, "Spec for recipe app: search, favorites, ingredients list."),
            ("planner",          "completed", None, None),
            ("architect",        "completed", None, "Design React app with recipe API and local storage."),
            ("planner",          "completed", None, None),
            ("tester",           "completed", None, "Tests for recipe CRUD, search, favorites."),
            ("planner",          "completed", None, None),
            ("builder",          "failed",
             "RateLimitError: Rate limit exceeded, retried 3 times",
             "Implement recipe app to pass all tests."),
            ("planner",          "pending",  None, None),
        ],
    },
    # ── 10: Update project — shorter flow ──────────────────────────
    {
        "ns": 0xA00A,
        "title": "add dark mode to the weather dashboard",
        "project_name": "weather-dashboard-update",
        "status": "completed",
        "intent": "update_project",
        "hours_ago": 18,
        "agents": [
            ("router",    "completed", None, None),
            ("planner",   "completed", None, None),
            ("architect", "completed", None, "Add CSS variables for dark/light theme toggle."),
            ("planner",   "completed", None, None),
            ("tester",    "completed", None, "Tests for theme toggle and CSS variable application."),
            ("planner",   "completed", None, None),
            ("builder",   "completed", None, "Implemented dark mode toggle, all 6 tests pass."),
            ("planner",   "completed", None, None),
            ("deployer",  "completed", None, "Redeployed weather dashboard with dark mode."),
        ],
    },
]

# The primary session for builder retry testing
PRIMARY_SESSION_NS = 0xA000


# ---------------------------------------------------------------------------
# Database population
# ---------------------------------------------------------------------------
def populate_db(repos: dict[int, dict]):
    """Insert all seed sessions into PostgreSQL."""
    conn = psycopg2.connect(DB_DSN)
    conn.autocommit = False
    cur = conn.cursor()

    try:
        # -- Clean previous seed data --
        print("  Cleaning previous seed data...")
        for s in SESSIONS:
            ns = s["ns"]
            session_id = _uid(ns, 0)
            project_id = _uid(ns, 9999)
            cur.execute("DELETE FROM sessions WHERE id = %s", (session_id,))
            cur.execute("DELETE FROM projects WHERE id = %s", (project_id,))

        # -- Look up or create admin user --
        cur.execute("SELECT id FROM users WHERE username = 'admin'")
        row = cur.fetchone()
        if row:
            admin_id = str(row[0])
            print(f"  [OK] Found admin user: {admin_id}")
        else:
            admin_id = _uid(0xFFFF, 1)
            cur.execute(
                """INSERT INTO users (id, username, email, display_name, created_at, updated_at)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (admin_id, "admin", "admin@druppie.local", "Admin User", NOW, NOW),
            )
            cur.execute("INSERT INTO user_roles (user_id, role) VALUES (%s, %s)", (admin_id, "admin"))
            print(f"  [OK] Created admin user: {admin_id}")

        total_sessions = 0
        total_runs = 0
        total_llm = 0
        total_tc = 0
        total_msg = 0

        for s in SESSIONS:
            ns = s["ns"]
            session_id = _uid(ns, 0)
            project_id = _uid(ns, 9999)
            base_ts = _ts(s["hours_ago"])
            agents = s["agents"]

            # -- Project (if session has one) --
            repo_info = repos.get(ns)
            if repo_info:
                cur.execute(
                    """INSERT INTO projects
                       (id, name, description, repo_name, repo_owner, repo_url, clone_url,
                        owner_id, status, created_at, updated_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (project_id, s["project_name"], f"Seeded: {s['title']}",
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
                (session_id, admin_id,
                 project_id if repo_info else None,
                 s["title"], s["status"], s["intent"], "en",
                 tok_p, tok_c, tok_p + tok_c, base_ts, base_ts),
            )
            total_sessions += 1

            # -- Agent runs, LLM calls, tool calls, messages --
            # User message (seq 0)
            cur.execute(
                """INSERT INTO messages
                   (id, session_id, agent_run_id, role, content,
                    agent_id, sequence_number, created_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                (_uid(ns, 5000), session_id, None, "user", s["title"], None, 0, base_ts),
            )
            total_msg += 1

            planner_count = 0
            for seq_idx, (agent_id, status, error_msg, planned_prompt) in enumerate(agents):
                seq = seq_idx + 1
                run_id = _uid(ns, seq)
                run_ts = base_ts + timedelta(minutes=seq * 2)

                # Track planner numbering for summary text
                if agent_id == "planner":
                    planner_count += 1

                completed_at = run_ts if status == "completed" else None
                is_active = status in ("completed", "failed", "running")
                tok_p_run = 3000 if status == "completed" else (1500 if status == "running" else 0)
                tok_c_run = 1000 if status == "completed" else (0 if status != "running" else 0)

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

                # LLM call (not for pending agents)
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
                    total_llm += 1

                # Tool calls
                if status == "completed":
                    tc_idx = 0
                    # Router gets set_intent
                    if agent_id == "router" and s["intent"]:
                        cur.execute(
                            """INSERT INTO tool_calls
                               (id, session_id, agent_run_id, llm_call_id,
                                mcp_server, tool_name, tool_call_index,
                                arguments, status, result, created_at, executed_at)
                               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                            (_uid(ns, 3000 + seq * 10), session_id, run_id, llm_id,
                             "builtin", "set_intent", 0,
                             json.dumps({"intent": s["intent"],
                                         "project_name": s.get("project_name")}),
                             "completed", f"Intent set to {s['intent']}",
                             run_ts, run_ts),
                        )
                        total_tc += 1
                        tc_idx = 1

                    # Planner gets make_plan
                    if agent_id == "planner":
                        # Build remaining steps from current position
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

                    # Every completed agent gets done
                    summary = _agent_summary(agent_id, s, planner_count)
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
                    total_msg += 1

                elif status == "failed":
                    # Failed tool call (execute_coding_task for builder, generic for others)
                    tool_name = "execute_coding_task" if agent_id == "builder" else "done"
                    cur.execute(
                        """INSERT INTO tool_calls
                           (id, session_id, agent_run_id, llm_call_id,
                            mcp_server, tool_name, tool_call_index,
                            arguments, status, result, error_message,
                            created_at, executed_at)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                        (_uid(ns, 3000 + seq * 10), session_id, run_id, llm_id,
                         "builtin", tool_name, 0,
                         json.dumps({"prompt": planned_prompt[:200]} if planned_prompt else {}),
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
                    total_msg += 1

                # running / pending agents: no tool calls or messages

        conn.commit()
        print(f"  [OK] Inserted {total_sessions} sessions, {total_runs} agent runs, "
              f"{total_llm} LLM calls, {total_tc} tool calls, {total_msg} messages")

    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


def _agent_summary(agent_id: str, session: dict, planner_count: int) -> str:
    """Generate a realistic done() summary for a completed agent."""
    title = session["title"]
    name = session.get("project_name") or "project"
    summaries = {
        "router": f"Agent router: Classified intent as {session.get('intent', 'general_chat')}, project '{name}'.",
        "planner": f"Agent planner: Updated execution plan (iteration {planner_count}). Proceeding to next agent.",
        "business_analyst": f"Agent business_analyst: Analyzed requirements for '{title}'. Created SPEC.md with user stories and acceptance criteria.",
        "architect": f"Agent architect: Designed architecture for {name}. Created architecture.md and technical_design.md.",
        "tester": f"Agent tester: Generated test suite for {name}. All tests initially fail (TDD red phase).",
        "builder": f"Agent builder: Implemented {name}, all tests passing. Code committed and pushed.",
        "deployer": f"Agent deployer: Deployed {name} container. Application is running.",
        "developer": f"Agent developer: Applied code changes to {name}.",
        "reviewer": f"Agent reviewer: Code review complete for {name}.",
    }
    return summaries.get(agent_id, f"Agent {agent_id}: Completed task for {name}.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    print("=" * 60)
    print("Druppie — Seed: Multi-Session Test Data")
    print("=" * 60)

    # Step 1: Gitea repos (only for sessions that have projects)
    print(f"\n[STEP 1] Creating {sum(1 for s in SESSIONS if s['project_name'])} Gitea repos...")
    repos: dict[int, dict] = {}
    with httpx.Client(base_url=GITEA_URL, auth=(GITEA_USER, GITEA_PASS), timeout=15) as c:
        ensure_gitea_user(c)
        for s in SESSIONS:
            if s["project_name"]:
                repos[s["ns"]] = create_gitea_repo(c, s["project_name"])

    # Step 2: Database
    print(f"\n[STEP 2] Populating database ({len(SESSIONS)} sessions)...")
    populate_db(repos)

    # Step 3: Summary
    primary_id = _uid(PRIMARY_SESSION_NS, 0)
    session_url = f"{FRONTEND_URL}/chat?session={primary_id}&mode=inspect"
    print("\n" + "=" * 60)
    print("[DONE] Seed data created successfully!")
    print("=" * 60)
    print()
    print(f"  Sessions created: {len(SESSIONS)}")
    print(f"  Builder-retry:   {session_url}")
    if PRIMARY_SESSION_NS in repos:
        print(f"  Gitea repo:      {repos[PRIMARY_SESSION_NS]['repo_url']}")
    print()
    print("  Session states:")
    for s in SESSIONS:
        sid = _uid(s["ns"], 0)[:8]
        n_agents = len(s["agents"])
        last = s["agents"][-1]
        print(f"    {sid}.. {s['status']:18s} {n_agents:2d} agents  {s['title'][:50]}")
    print()
    print("  To test builder retry:")
    print("    1. Login as admin / Admin123!")
    print(f"    2. Open {session_url}")
    print("    3. Click retry on the failed builder agent run")
    print()
    print("=" * 60)


if __name__ == "__main__":
    main()
