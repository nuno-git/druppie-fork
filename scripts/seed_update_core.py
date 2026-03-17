#!/usr/bin/env python3
"""
Seed script: populate DB + Gitea with a realistic update_core session.

Creates a session that has completed through BA → Architect (DESIGN_APPROVED_CORE_UPDATE),
so the update_core_builder agent is ready to run next.

The session simulates a user asking to add a smiley.md file to the Druppie codebase.
The BA gathered requirements and wrote the FD, the Architect reviewed and wrote the TD
with DESIGN_APPROVED_CORE_UPDATE signal, and the Planner has routed to update_core_builder.

Usage:
    docker compose --profile reset-db run --rm reset-db       # reset DB first
    python scripts/seed_update_core.py                        # then seed

Connects to localhost ports (DB, Gitea). Run from host, not Docker.
"""

import json
import os
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import psycopg2

# ---------------------------------------------------------------------------
# Configuration — auto-detect from .env or use defaults
# ---------------------------------------------------------------------------
DB_PORT = os.environ.get("DRUPPIE_DB_PORT", "5634")
DB_DSN = f"postgresql://druppie:druppie_secret@localhost:{DB_PORT}/druppie"
GITEA_PORT = os.environ.get("GITEA_PORT", "3200")
GITEA_URL = f"http://localhost:{GITEA_PORT}"
GITEA_USER = "gitea_admin"
GITEA_PASS = "GiteaAdmin123"
FRONTEND_PORT = os.environ.get("FRONTEND_PORT", "5374")
FRONTEND_URL = f"http://localhost:{FRONTEND_PORT}"

NOW = datetime.now(timezone.utc)

# Namespace for deterministic UUIDs
NS_CORE = 0xC000


def _ts(minutes_ago: float = 0) -> datetime:
    return NOW - timedelta(minutes=minutes_ago)


def _uid(namespace: int, index: int) -> str:
    return str(uuid.UUID(f"{namespace:04x}0000-{index:04x}-4000-8000-{index:012x}"))


# ---------------------------------------------------------------------------
# Realistic content — FD and TD that would have been written
# ---------------------------------------------------------------------------

FUNCTIONAL_DESIGN = """\
# Functioneel Ontwerp — Druppie Smiley

## 1. Huidige vs Gewenste Situatie

| Aspect | Huidige Situatie | Gewenste Situatie |
|--------|-----------------|-------------------|
| Repository inhoud | Druppie codebase zonder visueel element | Repository bevat een smiley.md bestand |
| Bestandslocatie | N.v.t. | Root directory van de repository |

## 2. Probleemsamenvatting

- **Wie is betrokken:** De eigenaar van de repository
- **Welk probleem:** Persoonlijke voorkeur — een vriendelijk element toevoegen
- **Wat succes betekent:** Een smiley.md bestand in de root met een kleine ASCII smiley

## 3. Functionele Eisen

| ID | Bron | Eis | Verificatiemethode |
|----|------|-----|-------------------|
| FR-01 | BA | Het systeem moet een smiley.md bestand toevoegen aan de repository root | Bestand bestaat in root |
| FR-02 | BA | Het bestand bevat een kleine, eenvoudige ASCII-kunst smiley | Visuele inspectie |
| FR-03 | BA | Het bestand bevat alleen de ASCII-kunst, geen extra tekst | Bestandsinhoud controleren |

## 4. Niet-Functionele Eisen

| ID | Bron | Eis | Verificatiemethode |
|----|------|-----|-------------------|
| NFR-01 | BA | Het bestand moet kleiner zijn dan 1 KB | Bestandsgrootte controleren |

## 5. Buiten Scope

- Extra documentatie of metadata
- Complexe ASCII-kunst ontwerpen
- Integratie met andere componenten
"""

TECHNICAL_DESIGN = """\
# Technisch Ontwerp — Druppie Smiley

## Introductie

### Onderwerp
Toevoegen van een smiley.md bestand aan de Druppie codebase.

### Probleemsamenvatting
De gebruiker wil een klein, decoratief ASCII-kunst bestand toevoegen aan de root
van de Druppie repository.

### Functionele Vraag
Hoe kan een eenvoudig markdown-bestand met ASCII-kunst worden toegevoegd aan de
repository zonder impact op bestaande functionaliteit?

## Oplossing

### Toegepaste Principes (per NORA-laag)
* **Grondslagen:** Geen wet- of regelgeving van toepassing (decoratief bestand)
* **Organisatie:** Waterschapscontext niet relevant voor dit decoratief element
* **Informatie:** Geen gegevensstromen — statisch bestand
* **Applicatie:** Geen nieuwe componenten — alleen een bestand
* **Netwerk:** Geen netwerkimpact
* **Beveiliging & Privacy:** Geen beveiligingsrisico's — publiek bestand zonder gegevens

### Eisen

| ID | Bron | Eis | Verificatiemethode |
|----|------|-----|-------------------|
| FR-01 | BA | smiley.md in repository root | Bestand bestaat |
| FR-02 | BA | Kleine, eenvoudige ASCII smiley | Visuele inspectie |
| FR-03 | BA | Alleen ASCII-kunst, geen extra tekst | Inhoudsinspectie |
| NFR-01 | BA | Bestand < 1 KB | Grootte controleren |
| TR-01 | AR | Bestand moet valid markdown zijn | Markdown parser check |
| TR-02 | AR | Geen impact op bestaande CI/CD | Build verificatie |

### Architectuuroplossing

#### 1. Componentstructuur
* Nieuw: `smiley.md` in repository root
* Hergebruik: Geen
* Impact: Geen — bestand staat los van alle systeemcomponenten

#### 2. Data-architectuur
* Geen datastromen
* Geen API's of interfaces

#### 3. Infrastructuur
* Geen wijzigingen aan hosting, netwerk of opslag

### Beveiliging by Design

| Aspect | Maatregel | Toelichting |
|--------|-----------|-------------|
| Authenticatie | Niet van toepassing | Statisch bestand |
| Autorisatie | Repository-niveau | Standaard git-toegang |

### Compliance by Design

| Eis | Implementatie | Status |
|-----|--------------|--------|
| AVG | Niet van toepassing | ✓ |
| BIO | Geen classificatie nodig | ✓ |
"""

# ---------------------------------------------------------------------------
# Agent summaries — what each agent "said" when it completed
# ---------------------------------------------------------------------------

ROUTER_SUMMARY = (
    "Agent router: Classified intent as create_project, project 'druppie-smiley'. "
    "User wants to add a smiley.md file to the Druppie codebase."
)

BA_SUMMARY = (
    "Agent business_analyst: DESIGN_APPROVED. Analyzed requirements for adding smiley.md "
    "to the Druppie codebase. Created functional_design.md with 3 functional requirements "
    "and 1 non-functional requirement. User confirmed the design."
)

ARCHITECT_SUMMARY = (
    "Agent architect: DESIGN_APPROVED_CORE_UPDATE. Reviewed functional_design.md — "
    "passes all architecture checks. Wrote technical_design.md with 3 functional requirements, "
    "1 non-functional requirement, and 2 technical requirements. "
    "This project requires changes to Druppie's core codebase (adding smiley.md to repository root)."
)

PLANNER_1_SUMMARY = (
    "Agent planner: Created plan. Next agent: business_analyst to gather requirements "
    "for adding smiley.md to the Druppie codebase."
)

PLANNER_2_SUMMARY = (
    "Agent planner: BA completed with DESIGN_APPROVED. Next agent: architect to design "
    "the architecture and check compliance."
)

PLANNER_3_SUMMARY = (
    "Agent planner: Architect completed with DESIGN_APPROVED_CORE_UPDATE. "
    "This is a core update — routing to update_core_builder agent."
)

UPDATE_CORE_BUILDER_PROMPT = """\
CORE CHANGE: Implement the approved design. Read functional_design.md and \
technical_design.md from /workspace/project/. Create a PR targeting colab-dev.

The architect has determined this project requires changes to Druppie's own codebase. \
Add a smiley.md file to the root of the Druppie repository containing a small, \
simple ASCII art smiley face. The file should contain only the ASCII art, no extra text.

## Previous Agent Summaries
{router_summary}
{planner1_summary}
{ba_summary}
{planner2_summary}
{architect_summary}
{planner3_summary}
""".format(
    router_summary=ROUTER_SUMMARY,
    planner1_summary=PLANNER_1_SUMMARY,
    ba_summary=BA_SUMMARY,
    planner2_summary=PLANNER_2_SUMMARY,
    architect_summary=ARCHITECT_SUMMARY,
    planner3_summary=PLANNER_3_SUMMARY,
)

# ---------------------------------------------------------------------------
# Agent runs for the update_core session
# ---------------------------------------------------------------------------
# (agent_id, status, error_message, planned_prompt, done_summary)
AGENTS = [
    ("router",           "completed", None,
     "Analyze user intent and classify.",
     ROUTER_SUMMARY),

    ("planner",          "completed", None,
     f"INTENT: create_project\nPROJECT_NAME: druppie-smiley",
     PLANNER_1_SUMMARY),

    ("business_analyst", "completed", None,
     "Gather functional requirements for adding smiley.md to the Druppie codebase. "
     "Ask the user clarifying questions. Write functional_design.md.",
     BA_SUMMARY),

    ("planner",          "completed", None,
     "BA completed. Evaluate output and decide next step.",
     PLANNER_2_SUMMARY),

    ("architect",        "completed", None,
     "Design architecture for druppie-smiley. Read functional_design.md. "
     "Create technical_design.md. IMPORTANT: If this project adds, modifies, or removes "
     "anything in the Druppie codebase/repository itself, signal DESIGN_APPROVED_CORE_UPDATE.",
     ARCHITECT_SUMMARY),

    ("planner",          "completed", None,
     "Architect completed. Evaluate output and decide next step.",
     PLANNER_3_SUMMARY),

    # This is the agent that should run next — pending
    ("update_core_builder", "pending", None,
     UPDATE_CORE_BUILDER_PROMPT,
     None),

    ("planner",          "pending", None,
     "Update core builder completed. Evaluate output and decide next step.",
     None),
]


# ---------------------------------------------------------------------------
# Gitea helpers
# ---------------------------------------------------------------------------
def ensure_gitea_user(client: httpx.Client):
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
        print(f"  [{'OK' if r.status_code in (201, 422) else 'WARN'}] Gitea user druppie_admin")
    else:
        print("  [OK] Gitea user druppie_admin exists")


def create_gitea_repo(client: httpx.Client, name: str) -> dict:
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
        print(f"  [ERROR] Failed to create repo {repo_name}: {r.status_code} {r.text}")
        sys.exit(1)
    return {
        "repo_name": repo_name,
        "repo_owner": "druppie_admin",
        "repo_url": f"{GITEA_URL}/druppie_admin/{repo_name}",
        "clone_url": data.get("clone_url", f"{GITEA_URL}/druppie_admin/{repo_name}.git"),
    }


def push_design_docs(client: httpx.Client, repo_name: str):
    """Push functional_design.md and technical_design.md to the project repo."""
    import base64

    for filename, content in [
        ("functional_design.md", FUNCTIONAL_DESIGN),
        ("technical_design.md", TECHNICAL_DESIGN),
    ]:
        encoded = base64.b64encode(content.encode()).decode()
        r = client.post(
            f"/api/v1/repos/druppie_admin/{repo_name}/contents/{filename}",
            json={
                "message": f"Add {filename} (seeded)",
                "content": encoded,
            },
        )
        if r.status_code in (201, 422):
            print(f"  [OK] Pushed {filename} to {repo_name}")
        else:
            print(f"  [WARN] Could not push {filename}: {r.status_code}")


# ---------------------------------------------------------------------------
# Database population
# ---------------------------------------------------------------------------
def populate_db(repo_info: dict):
    conn = psycopg2.connect(DB_DSN)
    conn.autocommit = False
    cur = conn.cursor()

    try:
        session_id = _uid(NS_CORE, 0)
        project_id = _uid(NS_CORE, 9999)

        # Clean previous seed
        print("  Cleaning previous seed data...")
        cur.execute("DELETE FROM sessions WHERE id = %s", (session_id,))
        cur.execute("DELETE FROM projects WHERE id = %s", (project_id,))

        # Find admin user
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

        # Project
        cur.execute(
            """INSERT INTO projects
               (id, name, description, repo_name, repo_owner, repo_url, clone_url,
                owner_id, status, created_at, updated_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (project_id, "druppie-smiley",
             "Add a smiley.md file to the Druppie codebase with ASCII art",
             repo_info["repo_name"], repo_info["repo_owner"],
             repo_info["repo_url"], repo_info["clone_url"],
             admin_id, "active", _ts(30), _ts(30)),
        )

        # Session — intent stays create_project (by design!)
        cur.execute(
            """INSERT INTO sessions
               (id, user_id, project_id, title, status, intent, language,
                prompt_tokens, completion_tokens, total_tokens,
                created_at, updated_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (session_id, admin_id, project_id,
             "I want to add a smiley.md file to the Druppie codebase",
             "active",  # active because update_core_builder is pending
             "create_project",  # NOT update_core — intent never changes
             "en",
             18000, 6000, 24000, _ts(30), _ts(1)),
        )

        # User message
        cur.execute(
            """INSERT INTO messages
               (id, session_id, agent_run_id, role, content,
                agent_id, sequence_number, created_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
            (_uid(NS_CORE, 5000), session_id, None, "user",
             "I want to add a smiley.md file to the Druppie codebase. "
             "It should contain a big smiley face made of ASCII art.",
             None, 0, _ts(30)),
        )

        # Agent runs
        total_runs = 0
        total_tc = 0
        planner_count = 0

        for seq_idx, (agent_id, status, error_msg, planned_prompt, done_summary) in enumerate(AGENTS):
            seq = seq_idx + 1
            run_id = _uid(NS_CORE, seq)
            run_ts = _ts(30 - seq * 3)  # Each agent ~3 minutes apart

            if agent_id == "planner":
                planner_count += 1

            is_active = status in ("completed", "failed", "running")
            completed_at = run_ts if status == "completed" else None
            tok_p = 3000 if status == "completed" else 0
            tok_c = 1000 if status == "completed" else 0

            cur.execute(
                """INSERT INTO agent_runs
                   (id, session_id, agent_id, status, error_message,
                    planned_prompt, sequence_number, iteration_count,
                    prompt_tokens, completion_tokens, total_tokens,
                    started_at, completed_at, created_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (run_id, session_id, agent_id, status, error_msg,
                 planned_prompt, seq,
                 1 if status == "completed" else 0,
                 tok_p, tok_c, tok_p + tok_c,
                 run_ts if is_active else None, completed_at, run_ts),
            )
            total_runs += 1

            # LLM call for active agents
            llm_id = _uid(NS_CORE, 2000 + seq)
            if is_active:
                cur.execute(
                    """INSERT INTO llm_calls
                       (id, session_id, agent_run_id, provider, model,
                        prompt_tokens, completion_tokens, total_tokens,
                        duration_ms, created_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (llm_id, session_id, run_id,
                     "zai", "glm-4.7",
                     tok_p, tok_c, tok_p + tok_c,
                     random.randint(2000, 12000), run_ts),
                )

            # Tool calls for completed agents
            if status == "completed" and done_summary:
                tc_idx = 0

                # Router: set_intent
                if agent_id == "router":
                    cur.execute(
                        """INSERT INTO tool_calls
                           (id, session_id, agent_run_id, llm_call_id,
                            mcp_server, tool_name, tool_call_index,
                            arguments, status, result, created_at, executed_at)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                        (_uid(NS_CORE, 3000 + seq * 10), session_id, run_id, llm_id,
                         "builtin", "set_intent", 0,
                         json.dumps({"intent": "create_project", "project_name": "druppie-smiley"}),
                         "completed", "Intent set to create_project",
                         run_ts, run_ts),
                    )
                    total_tc += 1
                    tc_idx = 1

                # Planner: make_plan
                if agent_id == "planner":
                    remaining = AGENTS[seq_idx + 1:]
                    next_agent = remaining[0] if remaining else None
                    if next_agent:
                        steps = [
                            {"agent_id": next_agent[0], "prompt": next_agent[3] or f"Execute {next_agent[0]}."},
                            {"agent_id": "planner", "prompt": "Evaluate and decide next step."},
                        ]
                        cur.execute(
                            """INSERT INTO tool_calls
                               (id, session_id, agent_run_id, llm_call_id,
                                mcp_server, tool_name, tool_call_index,
                                arguments, status, result, created_at, executed_at)
                               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                            (_uid(NS_CORE, 3000 + seq * 10), session_id, run_id, llm_id,
                             "builtin", "make_plan", 0,
                             json.dumps({"steps": steps}),
                             "completed", f"Plan: next agent = {next_agent[0]}",
                             run_ts, run_ts),
                        )
                        total_tc += 1
                        tc_idx = 1

                # Architect: make_design (for TD)
                if agent_id == "architect":
                    cur.execute(
                        """INSERT INTO tool_calls
                           (id, session_id, agent_run_id, llm_call_id,
                            mcp_server, tool_name, tool_call_index,
                            arguments, status, result, created_at, executed_at)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                        (_uid(NS_CORE, 3000 + seq * 10), session_id, run_id, llm_id,
                         "coding", "make_design", 0,
                         json.dumps({"path": "technical_design.md", "content": TECHNICAL_DESIGN}),
                         "completed", "Wrote technical_design.md",
                         run_ts, run_ts),
                    )
                    total_tc += 1
                    tc_idx = 1

                # Every completed agent: done
                cur.execute(
                    """INSERT INTO tool_calls
                       (id, session_id, agent_run_id, llm_call_id,
                        mcp_server, tool_name, tool_call_index,
                        arguments, status, result, created_at, executed_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (_uid(NS_CORE, 3000 + seq * 10 + 1), session_id, run_id, llm_id,
                     "builtin", "done", tc_idx,
                     json.dumps({"summary": done_summary}),
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
                    (_uid(NS_CORE, 5000 + seq), session_id, run_id,
                     "assistant", done_summary, agent_id, seq, run_ts),
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
    print("Druppie — Seed: Update Core Flow Test Data")
    print("=" * 60)

    # Step 1: Gitea repo (project repo with FD/TD)
    print("\n[STEP 1] Creating Gitea project repo with design docs...")
    with httpx.Client(base_url=GITEA_URL, auth=(GITEA_USER, GITEA_PASS), timeout=15) as c:
        try:
            r = c.get("/api/v1/version")
            r.raise_for_status()
        except (httpx.ConnectError, httpx.ConnectTimeout):
            print(f"  [ERROR] Gitea not reachable at {GITEA_URL}")
            print("  Make sure services are running: docker compose --profile dev up -d")
            sys.exit(1)
        ensure_gitea_user(c)
        repo_info = create_gitea_repo(c, "druppie-smiley")
        push_design_docs(c, repo_info["repo_name"])

    # Step 2: Database
    print("\n[STEP 2] Populating database...")
    populate_db(repo_info)

    # Step 3: Summary
    session_id = _uid(NS_CORE, 0)
    session_url = f"{FRONTEND_URL}/chat?session={session_id}"

    print("\n" + "=" * 60)
    print("[DONE] Update core seed data created!")
    print("=" * 60)
    print()
    print(f"  Session:     {session_url}")
    print(f"  Session ID:  {session_id}")
    print(f"  Project:     druppie-smiley")
    print(f"  Gitea repo:  {repo_info['repo_url']}")
    print()
    print("  Agent pipeline state:")
    for seq_idx, (agent_id, status, _, _, _) in enumerate(AGENTS):
        marker = "→" if status == "pending" and seq_idx > 0 and AGENTS[seq_idx-1][1] == "completed" else " "
        icon = {"completed": "✓", "pending": "○", "running": "⟳", "failed": "✗"}.get(status, "?")
        highlight = " ← NEXT" if agent_id == "update_core_builder" and status == "pending" else ""
        print(f"    {icon} #{seq_idx+1}: {agent_id:25s} {status}{highlight}")
    print()
    print("  To test the update_core flow:")
    print("    1. Login as admin / Admin123!")
    print(f"    2. Open {session_url}")
    print("    3. The update_core_builder should be ready to run")
    print("    4. It will create a sandbox with /workspace/core/ (GitHub) + /workspace/project/ (Gitea)")
    print("    5. The sandbox agent reads FD/TD from /workspace/project/")
    print("    6. It adds smiley.md to /workspace/core/ and creates a PR")
    print("    7. done() will pause for developer approval")
    print()
    print("=" * 60)


if __name__ == "__main__":
    main()
