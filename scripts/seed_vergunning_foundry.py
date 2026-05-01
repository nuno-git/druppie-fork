#!/usr/bin/env python3
"""
Seed script: create a "vergunning vinder" Foundry agent session.

Creates ONE session with the full Foundry agent pipeline:
  router → planner → BA (FD) → planner → architect (TD, FOUNDRY_AGENT)
  → planner → build_classifier → foundry_agent_builder (AGENT_CREATED)

Also creates the custom_agent record so it shows on the Agents page.

Usage:
    docker compose --profile reset-db run --rm reset-db   # optional
    # Then run inside backend container (see bottom of file)
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
# Configuration
# ---------------------------------------------------------------------------
DB_DSN = os.environ.get(
    "DB_DSN", "postgresql://druppie:druppie_secret@localhost:5634/druppie"
)
GITEA_URL = os.environ.get("GITEA_URL", "http://localhost:3200")
GITEA_USER = os.environ.get("GITEA_USER", "gitea_admin")
GITEA_PASS = os.environ.get("GITEA_PASSWORD", "GiteaAdmin123")
FRONTEND_URL = "http://localhost:5273"

NOW = datetime.now(timezone.utc)
NS = 0xB001  # Namespace for vergunning vinder session


def _ts(hours_ago: float = 0) -> datetime:
    return NOW - timedelta(hours=hours_ago)


def _uid(namespace: int, index: int) -> str:
    return str(uuid.UUID(f"{namespace:04x}0000-{index:04x}-4000-8000-{index:012x}"))


# ---------------------------------------------------------------------------
# Gitea helpers
# ---------------------------------------------------------------------------
def ensure_gitea_user(client: httpx.Client):
    r = client.get("/api/v1/users/druppie_admin")
    if r.status_code == 404:
        r = client.post("/api/v1/admin/users", json={
            "username": "druppie_admin",
            "email": "druppie_admin@druppie.local",
            "password": os.environ.get("DRUPPIE_ADMIN_PASSWORD", "DruppieAdmin123!"),
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
    short = uuid.uuid4().hex[:8]
    repo_name = f"{name}-{short}"
    r = client.post("/api/v1/admin/users/druppie_admin/repos", json={
        "name": repo_name,
        "description": f"{name} — Foundry agent project",
        "private": False,
        "auto_init": True,
        "readme": "Default",
    })
    if r.status_code == 201:
        data = r.json()
        print(f"  [OK] Created repo: druppie_admin/{repo_name}")
    elif r.status_code in (409, 422):
        data = client.get(f"/api/v1/repos/druppie_admin/{repo_name}").json()
        print(f"  [OK] Repo already exists: druppie_admin/{repo_name}")
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
# Content
# ---------------------------------------------------------------------------
FUNCTIONAL_DESIGN = """\
Platform standards applied: [docs/platform-functional-standards.md](./platform-functional-standards.md) rev 1.0.

# Functioneel Ontwerp — Vergunning Vinder Agent

## 1. Huidige vs Gewenste Situatie

**Huidig:** Medewerkers van de gemeente moeten handmatig zoeken in het
vergunningenregister, het Omgevingsloket en diverse andere bronnen om te
bepalen welke vergunning(en) nodig zijn voor een bouw- of verbouwproject.
Dit kost veel tijd en leidt regelmatig tot onvolledige adviezen.

**Gewenst:** Een AI-agent die op basis van een beschrijving van het
bouwproject automatisch de relevante vergunningen identificeert, de
vereisten samenvat en verwijst naar de juiste aanvraagprocedures.

## 2. Functionele Eisen

### FR-1: Projectbeschrijving Intake
De agent vraagt de gebruiker om een beschrijving van het bouwproject:
- Type bouw (nieuwbouw, verbouw, aanbouw, sloop)
- Locatie (gemeente, wijk, beschermd stadsgezicht)
- Omvang (oppervlakte, hoogte, aantal verdiepingen)
- Bestemming (wonen, bedrijf, horeca, maatschappelijk)

### FR-2: Vergunningcheck
Op basis van de intake bepaalt de agent:
- Of een omgevingsvergunning nodig is
- Of er aanvullende vergunningen nodig zijn (monumenten, kap, uitweg)
- Of het project vergunningsvrij is (en waarom)

### FR-3: Bronverwijzing
De agent onderbouwt elk advies met verwijzingen naar:
- Relevante wet- en regelgeving (Omgevingswet, Bbl, Bal)
- Gemeentelijke bestemmingsplanregels
- Actuele informatie via web search

### FR-4: Taalondersteuning
De agent communiceert in het Nederlands en gebruikt juridisch correcte
maar begrijpelijke taal.

### FR-5: Disclaimers
De agent geeft altijd aan dat het advies informatief is en geen
juridische zekerheid biedt. Verwijs door naar het Omgevingsloket
voor een definitieve check.

## 3. Niet-Functionele Eisen

### NFR-1: Nauwkeurigheid
De agent moet actuele informatie gebruiken via web search en mag geen
verouderde regelgeving citeren.

### NFR-2: Responstijd
Antwoord binnen 30 seconden inclusief web search.

## 4. Gebruikersrollen
- Gemeentemedewerker (primair)
- Burger (secundair)
- Aannemer / adviseur (secundair)

## 14. Afwijkingen van platformstandaarden
N.v.t. — geen afwijkingen.
"""

TECHNICAL_DESIGN = """\
# Technisch Ontwerp — Vergunning Vinder Agent

## Classificatie
**BUILD_PATH: FOUNDRY_AGENT**

Dit project maakt een standalone AI-agent die wordt gedeployed naar
Azure AI Foundry. Er is geen eigen applicatiecode nodig — de agent
wordt volledig gedefinieerd door een system prompt en Foundry-native tools.

## Agent Specificatie

### Model
- LLM profiel: standard (gpt-4.1-mini in Foundry)
- Geen temperature override (niet ondersteund door Foundry)

### Foundry Tools
1. **bing_grounding** — voor het zoeken naar actuele vergunninginformatie,
   wet- en regelgeving, en gemeentelijke bestemmingsplannen. Vereist een
   Bing-verbinding in de Foundry portal.
2. **code_interpreter** — voor het structureren en vergelijken van
   vergunningseisen, het genereren van checklists.

### Instructies (samenvatting)
De system prompt definieert:
- Rol: vergunningadviseur voor de gemeente
- Welkomstbericht in het Nederlands
- Stapsgewijze intake van projectgegevens
- Vergunningcheck workflow met bronverwijzing
- Gebruik van bing_grounding voor actuele informatie
- Gebruik van code_interpreter voor checklists
- Disclaimers over informatief karakter
- Taal: Nederlands

### Wat NIET naar Foundry gaat
- temperature, max_tokens, max_iterations (DB-only)
- MCP tools (niet beschikbaar in Foundry)
- Skills (niet beschikbaar in Foundry)

## Architectuurbeslissingen
1. Foundry agent i.p.v. standalone app: geen eigen backend nodig,
   snellere time-to-market, beheer via Azure portal
2. bing_grounding i.p.v. file_search: vergunninginformatie verandert
   regelmatig, web search geeft altijd actuele resultaten
3. code_interpreter voor gestructureerde output: checklists en
   vergelijkingstabellen
"""

AGENT_INSTRUCTIONS = """\
Je bent de Vergunning Vinder, een AI-assistent van de gemeente die helpt
bij het bepalen welke vergunningen nodig zijn voor bouw- en verbouwprojecten.

## Welkomstbericht
Begin elk gesprek met:
"Welkom bij de Vergunning Vinder! Ik help u bepalen welke vergunningen
u nodig heeft voor uw bouw- of verbouwproject. Beschrijf uw project en
ik zoek uit welke vergunningen van toepassing zijn.

Let op: mijn advies is informatief en vervangt geen officiële
vergunningcheck via het Omgevingsloket."

## Werkwijze

### Stap 1: Intake
Vraag de gebruiker om de volgende gegevens:
- **Type project**: nieuwbouw, verbouw, aanbouw, sloop, renovatie
- **Locatie**: gemeente, adres of wijk (is het een beschermd stadsgezicht?)
- **Omvang**: oppervlakte in m², hoogte, aantal verdiepingen
- **Bestemming**: wonen, bedrijf, horeca, maatschappelijk, gemengd

Als de gebruiker niet alle gegevens in één keer geeft, vraag dan gericht
door. Accepteer ook onvolledige informatie en geef aan welke gegevens
nog ontbreken voor een compleet advies.

### Stap 2: Vergunningcheck
Op basis van de intake, bepaal:

1. **Omgevingsvergunning voor bouwen** — check of het project valt onder:
   - Vergunningsvrij bouwen (Besluit bouwwerken leefomgeving, Bbl)
   - Meldingsplichtig
   - Vergunningsplichtig

2. **Aanvullende vergunningen** — check of er ook nodig is:
   - Monumentenvergunning (bij rijks- of gemeentelijk monument)
   - Kapvergunning (bij het kappen van bomen)
   - Uitwegvergunning (bij een nieuwe oprit)
   - Sloopmelding (bij asbest of in beschermd stadsgezicht)
   - Bestemmingsplanwijziging (bij strijdig gebruik)

3. **Vergunningsvrij** — als het project vergunningsvrij is, leg uit
   waarom met verwijzing naar de specifieke regels.

### Stap 3: Bronverwijzing
Gebruik **bing_grounding** om te zoeken naar:
- Actuele tekst van relevante wetsartikelen
- Gemeentelijke bestemmingsplanregels voor de opgegeven locatie
- Recente wijzigingen in de Omgevingswet

Wanneer je bing_grounding gebruikt:
- Zoek op: "[gemeente] bestemmingsplan [adres/wijk]"
- Zoek op: "Omgevingswet vergunning [type bouw]"
- Zoek op: "Bbl vergunningsvrij bouwen [type project]"

Citeer altijd de bron (wet, artikel, gemeentelijke regelgeving) bij
elk onderdeel van je advies.

### Stap 4: Gestructureerd Advies
Gebruik **code_interpreter** om een overzichtelijke checklist te
genereren met:
- ✅ Vergunningsvrij / ❌ Vergunning nodig per categorie
- Benodigde documenten per vergunning
- Geschatte doorlooptijd per aanvraag
- Link naar het Omgevingsloket voor de aanvraag

## Foutafhandeling

- Als bing_grounding geen resultaten geeft voor de specifieke gemeente:
  geef algemeen advies op basis van landelijke regelgeving en adviseer
  de gebruiker om contact op te nemen met de gemeente.
- Als de gebruiker onvoldoende informatie geeft: geef een voorlopig
  advies en markeer duidelijk welke onderdelen onzeker zijn.
- Als het project complex is (meerdere bestemmingen, monument +
  nieuwbouw): adviseer altijd om een vooroverleg aan te vragen bij
  de gemeente.

## Beperkingen en Disclaimers

- Geef ALTIJD aan dat je advies informatief is
- Verwijs ALTIJD naar het Omgevingsloket (omgevingsloket.nl) voor
  de officiële check en aanvraag
- Doe GEEN uitspraken over de kans op goedkeuring
- Geef GEEN juridisch advies over bezwaarprocedures
- Als je het antwoord niet zeker weet, zeg dat eerlijk

## Taal
Communiceer altijd in het Nederlands. Gebruik juridisch correcte
terminologie maar leg vakjargon uit in begrijpelijke taal.
Gebruik "u" als aanspreeksvorm.
"""

# ---------------------------------------------------------------------------
# Session definition
# ---------------------------------------------------------------------------
BA_PLANNED_PROMPT = """\
Analyseer het gebruikersverzoek voor een vergunning vinder agent.
Voer de elicitatiefasen uit en schrijf een functioneel ontwerp."""

ARCHITECT_PLANNED_PROMPT = """\
Beoordeel het functioneel ontwerp voor de vergunning vinder.
Classificeer als FOUNDRY_AGENT — dit is een standalone AI-agent
voor Azure AI Foundry. Schrijf een technisch ontwerp gericht op
Foundry tools (bing_grounding, code_interpreter)."""

BUILD_CLASSIFIER_PLANNED_PROMPT = """\
Lees het functioneel en technisch ontwerp. Classificeer het build path.
Het TD vermeldt BUILD_PATH=FOUNDRY_AGENT. Route naar foundry_agent_builder."""

FOUNDRY_BUILDER_PLANNED_PROMPT = """\
Lees het FD en TD uit de workspace. Maak een Foundry agent definitie
voor de Vergunning Vinder met bing_grounding en code_interpreter."""

SESSION = {
    "ns": NS,
    "title": "ik wil een vergunning vinder agent maken, een azure agent",
    "project_name": "vergunning-vinder",
    "status": "completed",
    "intent": "create_project",
    "hours_ago": 0.5,
    "agents": [
        ("router",                "completed", None, None),
        ("planner",               "completed", None, None),
        ("business_analyst",      "completed", None, BA_PLANNED_PROMPT),
        ("planner",               "completed", None, None),
        ("architect",             "completed", None, ARCHITECT_PLANNED_PROMPT),
        ("planner",               "completed", None, None),
        ("build_classifier",      "completed", None, BUILD_CLASSIFIER_PLANNED_PROMPT),
        ("foundry_agent_builder", "completed", None, FOUNDRY_BUILDER_PLANNED_PROMPT),
        ("planner",               "completed", None, None),
    ],
}


# ---------------------------------------------------------------------------
# Summaries
# ---------------------------------------------------------------------------
SUMMARIES = {
    "router": "Agent router: Classified intent as create_project, created project 'vergunning-vinder'.",
    "planner": "Agent planner: Updated execution plan. Proceeding to next agent.",
    "business_analyst": (
        "Agent business_analyst: DESIGN_APPROVED. Analysed requirements for "
        "vergunning vinder agent. Created docs/functional-design.md with "
        "5 functionele eisen (intake, vergunningcheck, bronverwijzing, "
        "taalondersteuning, disclaimers) and 2 niet-functionele eisen."
    ),
    "architect": (
        "Agent architect: DESIGN_APPROVED_FOUNDRY_AGENT. Classified as "
        "FOUNDRY_AGENT — standalone AI agent for Azure AI Foundry. "
        "Created docs/technical-design.md specifying bing_grounding + "
        "code_interpreter tools. next_agent=build_classifier"
    ),
    "build_classifier": (
        "Agent build_classifier: BUILD_PATH=FOUNDRY_AGENT. Reason: "
        "TD explicitly classifies as FOUNDRY_AGENT, project creates a "
        "standalone AI agent for Azure AI Foundry. next_agent=foundry_agent_builder"
    ),
    "foundry_agent_builder": (
        "Agent foundry_agent_builder: AGENT_CREATED. Created Foundry agent "
        "'vergunning-vinder-agent' with foundry_tools: [bing_grounding, "
        "code_interpreter]. Agent has comprehensive Dutch-language instructions "
        "covering intake, vergunningcheck, bronverwijzing, and disclaimers. "
        "Ready for review and deployment from the Agents page. "
        "Note: bing_grounding requires a Bing connection in the Foundry portal."
    ),
}

# Extra tool calls per agent (beyond the standard done() call)
EXTRA_TOOL_CALLS = {
    "router": [
        ("builtin", "set_intent", {
            "intent": "create_project",
            "project_name": "vergunning-vinder",
        }, "Intent set to create_project, project 'vergunning-vinder'"),
    ],
    "business_analyst": [
        ("coding", "make_design", {
            "design_type": "functional",
            "content": FUNCTIONAL_DESIGN,
        }, "Functional design written to docs/functional-design.md"),
    ],
    "architect": [
        ("coding", "read_file", {
            "path": "docs/functional-design.md",
        }, FUNCTIONAL_DESIGN[:500] + "..."),
        ("web", "search_web", {
            "query": "Azure AI Foundry Agent Service built-in tools site:learn.microsoft.com",
        }, "Found: code_interpreter, file_search, bing_grounding, browser_automation, deep_research..."),
        ("coding", "make_design", {
            "design_type": "technical",
            "content": TECHNICAL_DESIGN,
        }, "Technical design written to docs/technical-design.md"),
    ],
    "build_classifier": [
        ("coding", "read_file", {
            "path": "docs/functional-design.md",
        }, FUNCTIONAL_DESIGN[:300] + "..."),
        ("coding", "read_file", {
            "path": "docs/technical-design.md",
        }, TECHNICAL_DESIGN[:300] + "..."),
    ],
    "foundry_agent_builder": [
        ("coding", "read_file", {
            "path": "docs/functional-design.md",
        }, FUNCTIONAL_DESIGN[:500] + "..."),
        ("coding", "read_file", {
            "path": "docs/technical-design.md",
        }, TECHNICAL_DESIGN[:500] + "..."),
        ("builtin", "list_custom_agents", {}, "No existing custom agents found."),
        ("web", "search_web", {
            "query": "Azure AI Foundry Agent Service available built-in tools site:learn.microsoft.com",
        }, "Found tools: code_interpreter, file_search, bing_grounding, browser_automation, deep_research..."),
        ("builtin", "create_foundry_agent", {
            "agent_id": "vergunning-vinder-agent",
            "name": "Vergunning Vinder",
            "description": "AI-assistent die helpt bepalen welke vergunningen nodig zijn voor bouw- en verbouwprojecten",
            "instructions": AGENT_INSTRUCTIONS,
            "model": "standard",
            "foundry_tools": ["bing_grounding", "code_interpreter"],
        }, "Custom agent 'vergunning-vinder-agent' created successfully."),
    ],
}


# ---------------------------------------------------------------------------
# Database + custom agent population
# ---------------------------------------------------------------------------
def populate_db(repo_info: dict):
    conn = psycopg2.connect(DB_DSN)
    conn.autocommit = False
    cur = conn.cursor()

    try:
        ns = SESSION["ns"]
        session_id = _uid(ns, 0)
        project_id = _uid(ns, 9999)
        agent_db_id = _uid(ns, 8888)
        base_ts = _ts(SESSION["hours_ago"])
        agents = SESSION["agents"]

        # -- Clean previous run --
        print("  Cleaning previous vergunning-vinder seed data...")
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
        # Clean custom agent
        cur.execute(
            "DELETE FROM custom_agent_foundry_tools WHERE custom_agent_id = %s",
            (agent_db_id,))
        cur.execute("DELETE FROM custom_agents WHERE id = %s", (agent_db_id,))
        cur.execute(
            "DELETE FROM custom_agents WHERE agent_id = 'vergunning-vinder-agent'")

        # -- Find admin user --
        cur.execute("SELECT id FROM users WHERE username = 'admin'")
        row = cur.fetchone()
        if not row:
            print("  [ERROR] Admin user not found. Login to the app first.")
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
             "Vergunning Vinder — Foundry AI agent voor vergunningcheck",
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
             SESSION["title"], SESSION["status"], SESSION["intent"], "nl",
             tok_p, tok_c, tok_p + tok_c, base_ts, base_ts),
        )

        # -- User message --
        cur.execute(
            """INSERT INTO messages
               (id, session_id, agent_run_id, role, content,
                agent_id, sequence_number, created_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
            (_uid(ns, 5000), session_id, None, "user",
             SESSION["title"], None, 0, base_ts),
        )

        # -- Agent runs + tool calls + messages --
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
            tok_p_run = 3000 if status == "completed" else 0
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

            # LLM call
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
                     random.randint(2000, 10000), run_ts),
                )

            if status != "completed":
                continue

            tc_idx = 0

            # Extra tool calls for this agent
            extras = EXTRA_TOOL_CALLS.get(agent_id, [])
            for mcp_server, tool_name, args, result_text in extras:
                cur.execute(
                    """INSERT INTO tool_calls
                       (id, session_id, agent_run_id, llm_call_id,
                        mcp_server, tool_name, tool_call_index,
                        arguments, status, result, created_at, executed_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (_uid(ns, 3000 + seq * 100 + tc_idx), session_id, run_id, llm_id,
                     mcp_server, tool_name, tc_idx,
                     json.dumps(args),
                     "completed", result_text,
                     run_ts, run_ts),
                )
                total_tc += 1
                tc_idx += 1

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
                        (_uid(ns, 3000 + seq * 100 + tc_idx), session_id, run_id, llm_id,
                         "builtin", "make_plan", tc_idx,
                         json.dumps({"steps": steps}),
                         "completed", f"Plan created with {len(steps)} steps",
                         run_ts, run_ts),
                    )
                    total_tc += 1
                    tc_idx += 1

            # done() call
            summary = SUMMARIES.get(agent_id, f"Agent {agent_id}: Completed.")
            cur.execute(
                """INSERT INTO tool_calls
                   (id, session_id, agent_run_id, llm_call_id,
                    mcp_server, tool_name, tool_call_index,
                    arguments, status, result, created_at, executed_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (_uid(ns, 3000 + seq * 100 + tc_idx), session_id, run_id, llm_id,
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

        # -- Custom Agent record (so it shows on the Agents page) --
        print("  Creating custom agent record...")
        cur.execute(
            """INSERT INTO custom_agents
               (id, agent_id, name, description, category,
                system_prompt, llm_profile, temperature,
                max_tokens, max_iterations, owner_id, is_active,
                created_at, updated_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (agent_db_id,
             "vergunning-vinder-agent",
             "Vergunning Vinder",
             "AI-assistent die helpt bepalen welke vergunningen nodig zijn voor bouw- en verbouwprojecten",
             "execution",
             AGENT_INSTRUCTIONS,
             "standard", 0.1, 4096, 10,
             admin_id, True,
             base_ts, base_ts),
        )

        # Foundry tools for the custom agent
        for i, tool_type in enumerate(["bing_grounding", "code_interpreter"]):
            cur.execute(
                """INSERT INTO custom_agent_foundry_tools
                   (id, custom_agent_id, tool_type)
                   VALUES (%s, %s, %s)""",
                (_uid(ns, 7000 + i), agent_db_id, tool_type),
            )

        conn.commit()
        print(f"  [OK] Inserted 1 session, {total_runs} agent runs, {total_tc} tool calls")
        print(f"  [OK] Created custom agent 'vergunning-vinder-agent'")

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
    print("Druppie — Seed: Vergunning Vinder Foundry Agent")
    print("=" * 60)

    # Step 1: Gitea repo
    print("\n[STEP 1] Creating Gitea repo...")
    with httpx.Client(base_url=GITEA_URL, auth=(GITEA_USER, GITEA_PASS), timeout=15) as c:
        try:
            r = c.get("/api/v1/version")
            r.raise_for_status()
        except (httpx.ConnectError, httpx.ConnectTimeout):
            print(f"  [ERROR] Gitea not reachable at {GITEA_URL}")
            sys.exit(1)
        ensure_gitea_user(c)
        repo_info = create_gitea_repo(c, "vergunning-vinder")

    # Step 2: Database
    print("\n[STEP 2] Populating database...")
    populate_db(repo_info)

    # Step 3: Summary
    session_id = _uid(NS, 0)
    session_url = f"{FRONTEND_URL}/chat?session={session_id}&mode=inspect"
    agents_url = f"{FRONTEND_URL}/agents"
    print("\n" + "=" * 60)
    print("[DONE] Vergunning Vinder seeded!")
    print("=" * 60)
    print()
    print(f"  Session:  {session_url}")
    print(f"  Agents:   {agents_url}")
    print(f"  Gitea:    {repo_info['repo_url']}")
    print()
    print("  Pipeline: router → planner → BA (FD) → planner")
    print("            → architect (TD, FOUNDRY_AGENT) → planner")
    print("            → build_classifier → foundry_agent_builder")
    print()
    print("  Custom agent 'vergunning-vinder-agent' visible on Agents page")
    print("  Ready to deploy to Azure AI Foundry")
    print()
    print("=" * 60)


if __name__ == "__main__":
    main()
