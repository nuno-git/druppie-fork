"""Seed an end-to-end test project for the ArchiMate flow.

Creates a Gitea repository with a ready-to-design functional design and
inserts a Project row in the Druppie DB so an architect can pick the
project up in the frontend, run the architect agent, and produce an
ArchiMate plate.

Run inside the backend container so it picks up DB + Gitea config from
the environment::

    docker exec druppie-new-backend python -m druppie.scripts.seed_archimate_test_project

The script is idempotent within a single test run — repeated invocations
create new projects with a timestamp suffix.
"""

from __future__ import annotations

import asyncio
import os
import random
import string
import sys
from datetime import datetime, timezone

from druppie.core.gitea import GiteaClient
from druppie.db.database import SessionLocal
from druppie.db.models import Project, User


FD_TEMPLATE = """# Functional Design — Burger Overlast-meldportaal

## Subject

Een waterschap wil burgers een online portaal bieden waar zij overlast
kunnen melden (stankoverlast, wateroverlast, dode vis, vervuiling) op
locaties die het waterschap beheert. Meldingen moeten landen in het
bestaande zaaksysteem (DSP) en het juiste behandelteam moet automatisch
worden genotificeerd.

## Problem Summary

Op dit moment komen meldingen via telefoon, e-mail en social media bij
verschillende afdelingen binnen. Daardoor:

- Er is geen centraal overzicht van openstaande meldingen.
- Burgers krijgen geen statusterugkoppeling.
- Behandelteams missen meldingen die buiten kantooruren binnenkomen.
- Het waterschap kan niet rapporteren op trends per type overlast.

## Functional Question

Hoe kunnen wij burgers één digitaal kanaal bieden om overlast te
melden, zó dat (a) de melding direct in het zaaksysteem wordt
geregistreerd, (b) het juiste behandelteam automatisch op de hoogte
wordt gesteld, en (c) de burger zelf de status van zijn melding kan
volgen?

## Stakeholders

| Rol                  | Belang |
|----------------------|--------|
| Burger               | Eenvoudig melden en status volgen |
| Behandelteam         | Volledige, tijdige meldingen met juiste classificatie |
| Zaakcoördinator      | Centraal overzicht en rapportage |
| Waterschap-bestuur   | Inzicht in trends voor beleid |

## Functional Requirements

- **FR-01**: Burger kan zonder account een melding indienen met
  locatie (kaartprik), type overlast, beschrijving en optioneel foto.
- **FR-02**: Bij indienen krijgt de burger een meldingsnummer en kan
  hij — via dezelfde browser of via e-maillink — de status opvragen.
- **FR-03**: Iedere melding wordt automatisch geregistreerd als zaak
  in het zaaksysteem (DSP) met de juiste zaaktype-classificatie.
- **FR-04**: Het verantwoordelijke behandelteam ontvangt direct na
  registratie een notificatie (e-mail of push).
- **FR-05**: Statusupdates die het behandelteam in het zaaksysteem
  zet, zijn binnen 1 minuut zichtbaar voor de burger.
- **FR-06**: De zaakcoördinator kan een dashboard raadplegen met
  meldingen per type, locatie en doorlooptijd.

## Non-Functional Requirements

- **NFR-01**: 95% van indien-acties verwerkt binnen 2 seconden.
- **NFR-02**: Beschikbaarheid 99.5% kantooruren, 99% overige tijden.
- **NFR-03**: Persoonsgegevens (e-mailadres) AVG-conform — alleen
  bewaard zolang melding open is, daarna gepseudonimiseerd.
- **NFR-04**: Conformeer aan BIO-baseline voor publieke webapplicaties.

## External Integrations

| Externe koppeling | Type           | Toelichting |
|-------------------|----------------|-------------|
| Zaaksysteem (DSP) | organizational | Zaakregistratie, status-update, zaaktype-mapping |
| Notificatieservice | organizational | E-mail + push naar behandelteams |
| Kaartservice (PDOK BAG/BGT) | other | Locatie-validatie en adres-resolutie |
| Object-opslag | other | Foto's van de burger |

## Constraints

- Geen account voor de burger; meldingsnummer + e-maillink volstaan.
- Hosting binnen Nederland (data-residency-eis).
- Geen vendor-lock-in op het zaaksysteem — koppeling via standaard
  ZGW-API zodat het waterschap zaaksysteem-leveranciers kan wisselen.

## Out of Scope

- Beheer van zaaktypes (gebeurt in het zaaksysteem zelf).
- Mobiele app — alleen responsive webapp in deze fase.
- Geavanceerde analytics (alleen basis-dashboard).
"""


def _suffix() -> str:
    """Short timestamped suffix so repeated seeds don't collide."""
    ts = datetime.now(timezone.utc).strftime("%y%m%d-%H%M")
    rand = "".join(random.choices(string.ascii_lowercase, k=3))
    return f"{ts}-{rand}"


async def _ensure_gitea_repo(client: GiteaClient, repo_name: str) -> dict:
    if await client.repo_exists(repo_name):
        print(f"  [SKIP] Gitea repo '{repo_name}' already exists")
        return await client.get_repo(repo_name)

    result = await client.create_repo(
        name=repo_name,
        description="ArchiMate end-to-end test project (overlast-meldportaal).",
        private=False,
        auto_init=True,
    )
    if not result.get("success"):
        raise RuntimeError(f"Gitea repo create failed: {result.get('error')}")
    print(f"  [OK] Created Gitea repo '{repo_name}'")
    return result


async def _push_fd(client: GiteaClient, repo_name: str) -> None:
    existing = await client.get_file(repo_name, "docs/functional-design.md")
    if existing.get("success"):
        print("  [SKIP] docs/functional-design.md already present")
        return

    result = await client.create_file(
        repo=repo_name,
        path="docs/functional-design.md",
        content=FD_TEMPLATE,
        message="feat(fd): seed functional design for ArchiMate e2e test",
        branch="main",
    )
    if not result.get("success"):
        raise RuntimeError(f"FD push failed: {result.get('error')}")
    print("  [OK] Pushed docs/functional-design.md")


def _insert_project(session, name: str, repo: dict, owner: User) -> Project:
    project = Project(
        name=name,
        description="ArchiMate end-to-end test — Burger overlast-meldportaal.",
        owner_id=owner.id,
        repo_name=name,
        repo_owner=repo.get("data", {}).get("owner", {}).get("login")
            or repo.get("repo_owner")
            or "druppie_admin",
        repo_url=repo.get("data", {}).get("html_url")
            or repo.get("html_url")
            or f"http://gitea:3000/druppie_admin/{name}",
        clone_url=repo.get("data", {}).get("clone_url")
            or repo.get("clone_url"),
        status="active",
    )
    session.add(project)
    session.flush()
    return project


async def _async_main() -> int:
    name = f"archimate-demo-{_suffix()}"
    print(f"\nSeeding ArchiMate e2e test project '{name}'")
    print("=" * 60)

    print("\n[1/3] Creating Gitea repo + pushing FD...")
    client = GiteaClient()
    try:
        repo = await _ensure_gitea_repo(client, name)
        await _push_fd(client, name)
    finally:
        await client.close()

    print("\n[2/3] Inserting Project row in Druppie DB...")
    session = SessionLocal()
    try:
        owner = session.query(User).filter_by(username="admin").one_or_none()
        if owner is None:
            print("  [FAIL] No 'admin' user found in Druppie DB.")
            print("  Log in to the frontend as admin once, then re-run this script.")
            return 1
        project = _insert_project(session, name, repo, owner)
        session.commit()
        project_id = str(project.id)
        repo_url = project.repo_url
        print(f"  [OK] Inserted project {project_id}")
    finally:
        session.close()

    print("\n[3/3] Ready for end-to-end test.")
    print("=" * 60)
    frontend = os.getenv("FRONTEND_URL", "http://localhost:5273")
    print(f"\nProject id : {project_id}")
    print(f"Repo URL   : {repo_url}")
    print(f"\nNext steps:")
    print(f"  1. Open {frontend} and log in as 'architect' (password: Architect123!).")
    print(f"  2. Pick the project '{name}' from the project list.")
    print(f"  3. Open a chat in the project and ask: ")
    print(f'        "Run the architect on docs/functional-design.md and produce')
    print(f'         a technical design with an ArchiMate context view."')
    print(f"  4. Approve the submit_design_for_review + archimate_* tool calls as the architect.")
    print(f"  5. When save_model is approved, check Gitea for:")
    print(f"        docs/technical-design.md")
    print(f"        docs/architecture.archimate")
    print(f"        docs/diagrams/*.svg")
    print(f"  6. Reopen the TD in the session viewer and confirm the ArchiMate")
    print(f"     block renders inline (pan/zoom + layer colors + delta-highlight).")
    return 0


def main() -> None:
    sys.exit(asyncio.run(_async_main()))


if __name__ == "__main__":
    main()
