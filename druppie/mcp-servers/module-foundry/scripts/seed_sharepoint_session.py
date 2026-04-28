"""Seed a test session mirroring the SharePoint Beleid Zoeker chat flow.

Creates: 1 project, 1 session, 6 agent runs (router -> BA -> architect ->
foundry_agent_builder -> deployer -> summarizer), the corresponding
user/assistant messages, and the foundry MCP tool calls the deployer
made. Uses the existing 'admin' user as session owner.

Idempotent: if a session with title 'Beleid Zoeker (SharePoint) — seeded'
already exists, it is deleted first (CASCADE removes child rows).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from uuid import UUID, uuid4

from druppie.db import SessionLocal, User, Project, Session, AgentRun, Message, ToolCall

SEED_TITLE = "Beleid Zoeker (SharePoint) — seeded"


def _iso(seconds_offset: int) -> datetime:
    """Timestamps spaced so the UI shows a clean ordered trace."""
    return datetime.now(timezone.utc) + timedelta(seconds=seconds_offset)


def seed() -> dict:
    with SessionLocal() as db:
        admin = db.query(User).filter_by(username="admin").one()

        # Wipe any prior seeded session (FK cascade removes children)
        existing = db.query(Session).filter_by(title=SEED_TITLE).all()
        for s in existing:
            db.delete(s)
        db.flush()

        project = Project(
            id=uuid4(),
            name="Beleid Zoeker (SharePoint)",
            description="Foundry agent for SharePoint-grounded policy Q&A.",
            owner_id=admin.id,
            status="active",
        )
        db.add(project)

        session = Session(
            id=uuid4(),
            user_id=admin.id,
            project_id=project.id,
            title=SEED_TITLE,
            status="completed",
            intent="create_project",
            language="nl",
            created_at=_iso(0),
            updated_at=_iso(720),
        )
        db.add(session)
        db.flush()

        msg_seq = 0

        def add_msg(agent_run, role, content, t_offset, agent_id=None,
                    tool_name=None, tool_call_id=None):
            nonlocal msg_seq
            msg_seq += 1
            db.add(
                Message(
                    id=uuid4(),
                    session_id=session.id,
                    agent_run_id=agent_run.id,
                    role=role,
                    content=content,
                    agent_id=agent_id,
                    tool_name=tool_name,
                    tool_call_id=tool_call_id,
                    sequence_number=msg_seq,
                    created_at=_iso(t_offset),
                )
            )

        def add_run(agent_id, t_start, t_end, sequence_number):
            run = AgentRun(
                id=uuid4(),
                session_id=session.id,
                agent_id=agent_id,
                status="completed",
                iteration_count=1,
                sequence_number=sequence_number,
                started_at=_iso(t_start),
                completed_at=_iso(t_end),
                created_at=_iso(t_start),
            )
            db.add(run)
            db.flush()
            return run

        def add_tool_call(agent_run, server, tool_name, args, result,
                          t_created, t_executed, index=0):
            db.add(
                ToolCall(
                    id=uuid4(),
                    session_id=session.id,
                    agent_run_id=agent_run.id,
                    mcp_server=server,
                    tool_name=tool_name,
                    tool_call_index=index,
                    arguments=args,
                    status="completed",
                    result=json.dumps(result, ensure_ascii=False),
                    created_at=_iso(t_created),
                    executed_at=_iso(t_executed),
                )
            )

        # ---------------- Router ----------------
        router = add_run("router", 0, 30, sequence_number=0)
        add_msg(
            router,
            "user",
            "We hebben een heleboel interne beleidsdocumenten in SharePoint "
            "staan (HR, inkoop, informatiebeveiliging). Ik wil een Foundry "
            "agent die vragen van medewerkers beantwoordt op basis van die "
            "documenten, met bronverwijzing. Deployen naar Azure AI Foundry.",
            0,
        )
        add_msg(
            router,
            "assistant",
            "Agent router: intent=create_project. Dit is een agent-creatie "
            "verzoek — routering via Business Analyst -> Architect.",
            25,
            agent_id="router",
        )

        # ---------------- Business Analyst ----------------
        ba = add_run("business_analyst", 35, 150, sequence_number=1)
        add_msg(
            ba,
            "assistant",
            "Agent business_analyst: DESIGN_APPROVED. Functional design:\n"
            "- Doel: beleidsvragen beantwoorden op basis van SharePoint.\n"
            "- Tools: SharePoint Grounding + Code Interpreter.\n"
            "- Scope: interne documenten; stateless; bronverwijzing verplicht.\n"
            "- Buiten scope: juridisch advies, documenten bewerken, externe web.",
            140,
            agent_id="business_analyst",
        )

        # ---------------- Architect ----------------
        arch = add_run("architect", 155, 400, sequence_number=2)
        architect_yaml = (
            "name: beleid-zoeker-sharepoint\n"
            "model: gpt-5-mini\n"
            "instructions: |\n"
            "  Je bent de Beleid Zoeker. Beantwoord vragen van gemeente-\n"
            "  medewerkers uitsluitend op basis van de SharePoint-documenten.\n"
            "  Voeg altijd een bronverwijzing toe.\n"
            "tools:\n"
            "  - type: sharepoint_grounding\n"
            "    connection_id: /subscriptions/<SUB>/.../connections/<SP_CONN>\n"
            "  - type: code_interpreter\n"
            "metadata:\n"
            "  druppie_project_id: beleid-zoeker\n"
            "  druppie_version: \"1\"\n"
        )
        add_msg(
            arch,
            "assistant",
            "Agent architect: DESIGN_APPROVED, BUILD_PATH=FOUNDRY_AGENT. "
            "Technical design: gpt-5-mini, sharepoint_grounding als "
            "primaire kennisbron, code_interpreter voor berekeningen, geen "
            "dataretentie. YAML:\n\n" + architect_yaml +
            "\nnext_agent=foundry_agent_builder",
            390,
            agent_id="architect",
        )

        # ---------------- Foundry Agent Builder (pre-flight) ----------------
        fab = add_run("foundry_agent_builder", 405, 450, sequence_number=3)
        add_tool_call(
            fab, "foundry", "validate_agent_yaml",
            args={"yaml_content": architect_yaml},
            result={"ok": True, "valid": True, "errors": [], "warnings": []},
            t_created=410, t_executed=412, index=0,
        )
        list_result = {
            "ok": True,
            "endpoint": "https://druppie-resource.services.ai.azure.com/api/projects/druppie",
            "always_available": [
                "browser_automation", "code_interpreter",
                "deep_research", "file_search",
            ],
            "connection_backed": [
                {"type": "azure_ai_search", "available": False, "connections": []},
                {"type": "bing_custom_search", "available": False, "connections": []},
                {"type": "bing_grounding", "available": False, "connections": []},
                {"type": "microsoft_fabric", "available": False, "connections": []},
                {"type": "sharepoint_grounding", "available": False, "connections": []},
            ],
            "deployed_models": [
                {"name": "gpt-5-mini", "model": "gpt-5-mini"},
                {"name": "claude-opus-4-6", "model": "claude-opus-4-6"},
                {"name": "text-embedding-3-large", "model": "text-embedding-3-large"},
                {"name": "gpt-4o", "model": "gpt-4o"},
            ],
        }
        add_tool_call(
            fab, "foundry", "list_foundry_tools",
            args={}, result=list_result,
            t_created=415, t_executed=420, index=1,
        )
        add_msg(
            fab,
            "assistant",
            "Agent foundry_agent_builder: AGENT_CREATED. Pre-flight WARN: "
            "geen SharePoint-connection gevonden in het project. YAML is "
            "schema-valide en het model 'gpt-5-mini' is beschikbaar. De "
            "deployer moet connection_id opnieuw controleren.",
            445,
            agent_id="foundry_agent_builder",
        )

        # ---------------- Planner ----------------
        planner = add_run("planner", 455, 470, sequence_number=4)
        add_msg(
            planner,
            "assistant",
            "Agent planner: routes to deployer. intent_context="
            "deploy_foundry_agent.",
            468,
            agent_id="planner",
        )

        # ---------------- Deployer ----------------
        dep = add_run("deployer", 475, 650, sequence_number=5)
        add_tool_call(
            dep, "foundry", "validate_agent_yaml",
            args={"yaml_content": architect_yaml},
            result={"ok": True, "valid": True, "errors": [], "warnings": []},
            t_created=480, t_executed=482, index=0,
        )
        add_tool_call(
            dep, "foundry", "list_foundry_tools",
            args={}, result=list_result,
            t_created=485, t_executed=490, index=1,
        )
        deploy_result = {
            "ok": False,
            "stage": "availability",
            "errors": [
                {
                    "field": "tools.0",
                    "message": "tool 'sharepoint_grounding' is not available in project — no matching connection configured",
                    "code": "tool_unavailable",
                }
            ],
            "warnings": [],
        }
        add_tool_call(
            dep, "foundry", "deploy_agent",
            args={"yaml_content": architect_yaml, "dry_run": False},
            result=deploy_result,
            t_created=500, t_executed=540, index=2,
        )
        add_msg(
            dep,
            "assistant",
            "Agent deployer: DEPLOY_REJECTED — stage=availability: tool "
            "'sharepoint_grounding' is not available in project — no matching "
            "connection configured. Actie: voeg SharePoint-connection toe in "
            "de Foundry portal en deploy opnieuw.",
            640,
            agent_id="deployer",
        )

        # ---------------- Summarizer ----------------
        summ = add_run("summarizer", 655, 715, sequence_number=6)
        add_msg(
            summ,
            "assistant",
            "De deploy is niet voltooid omdat er nog geen SharePoint-"
            "connection bestaat in je Foundry-project. Open Azure Portal → "
            "Foundry-project → Connected resources, voeg een SharePoint-"
            "connection toe die verwijst naar de documentbibliotheken die "
            "de agent mag lezen, werk connection_id in de YAML bij en "
            "deploy opnieuw.",
            710,
            agent_id="summarizer",
        )

        db.commit()

        return {
            "session_id": str(session.id),
            "project_id": str(project.id),
            "admin_user_id": str(admin.id),
            "agent_runs": 6,
            "messages": msg_seq,
            "tool_calls": 5,
            "title": SEED_TITLE,
        }


if __name__ == "__main__":
    result = seed()
    print(json.dumps(result, indent=2))
