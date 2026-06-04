---
name: making-archimate-diagrams
description: >
  Use this skill when creating or updating an ArchiMate view inside a
  technical-design document. Covers when to pick ArchiMate over Mermaid,
  the embed syntax for ```archimate code blocks, element and relationship
  vocabulary per ArchiMate layer, WILMA reference reuse, and the
  incremental write workflow that preserves existing layout on revision.
---

# Making ArchiMate Diagrams

ArchiMate is the right tool for **structural enterprise-architecture
views** — components, the layers they live on, and how they relate.
Mermaid stays the right tool for **behavioral diagrams** ArchiMate
cannot express. The two are complementary; this skill teaches when
ArchiMate wins and how to author a view correctly.

## Choose: ArchiMate or Mermaid?

| Visualisation goal | Pick |
|--------------------|------|
| High-level architecture across Business/App/Technology layers | **ArchiMate** |
| Reuse of WILMA reference elements | **ArchiMate** |
| Cross-layer blueprint that an architect will peer-review | **ArchiMate** |
| Components + relationships with formal semantics (Realization, Serving, Flow, ...) | **ArchiMate** |
| Sequence of messages / API calls over time | **Mermaid** (`sequenceDiagram`) |
| State machine / lifecycle | **Mermaid** (`stateDiagram-v2`) |
| Decision tree / flowchart logic | **Mermaid** (`flowchart`) |
| Entity-relationship data model | **Mermaid** (`erDiagram`) |
| Gantt / timeline | **Mermaid** (`gantt`) |
| Class hierarchy | **Mermaid** (`classDiagram`) |

If a diagram needs both — for example, an Application-Cooperation view
plus an interaction sequence — write two code-blocks, one of each type.
Do not try to express behavior in ArchiMate.

## The Embed Syntax

ArchiMate diagrams live in `docs/architecture.archimate` (Open Exchange
XML). Inside `docs/technical-design.md`, a view is referenced by id:

````
```archimate
view-id: <uuid>
file: docs/architecture.archimate
```
````

Both keys are required. The TD viewer fetches the .archimate file from
the project's Gitea repo and renders the named view interactively
(pan/zoom). Nothing else goes between the backticks — no XML, no
positional data.

## Authoring Workflow

**The plate visualises what the TD describes — it does not come
first.** Design the architecture in your head based on the chosen
approach in `docs/technical-research.md` and the components +
integrations the TD is going to discuss. Only once you know what
the plate needs to show do you start calling archimate write tools.
If you find yourself making elements that are not mentioned anywhere
in the TD draft, you are getting ahead of the design.

After the plate is materialised, write the TD with a
\`\`\`archimate view-id=... \`\`\` block referencing the saved view.
That single `coding_make_design` call is the approval gate; the
reviewer sees the TD narrative and the rendered plate side by side.

**Build the whole plate in ONE call.** Assemble every element and
relationship into a single spec and hand it to a composite-view builder.
This is the default and by far the fastest path: a plate that the
primitive tools would build in 30–50 separate `create_*` / `add_*` calls
— each its own LLM turn, the reason a plate used to take ~13 minutes —
becomes **one** tool call. Drop to the primitive tools *only* to edit an
existing view (see "Updating an Existing View" below).

1. **Always check WILMA first — but reuse selectively.** Call
   `archimate_search_model(query=<keyword>, layer=<layer>)` to see which
   reference elements exist for the concepts you're about to model. The
   search is cheap and improves naming or surfaces a missing relationship.

   Reuse a WILMA element only when **both** apply:
   - the project sits in the waterschap context that WILMA models
     (the FD references waterschappen, bronsystemen, zaaksysteem, DMS,
     archiefsysteem, drinkwater/waterkeringen/heffingen, etc.), AND
   - the WILMA element genuinely matches the role you need.

   When reuse is right you do **not** import it as a separate step — put
   `{name: "<label>", wilma_id: "<wilma element id>"}` straight in the
   builder's element spec (step 2); the identifier is preserved. When reuse
   is wrong (non-waterschap project, element too coarse/fine, misleading
   name), model a project-specific element and note in the TD which WILMA
   concept you considered.

2. **Build the view in one call.** Assemble the spec and call:
   - `archimate_add_layered_view(name, business=[…], application=[…],
     technology=[…], motivation=[…], relationships=[…])` for the standard
     cross-layer stack (Business top → Application → Technology), or
   - `archimate_add_cooperation_view(name, peers=[…], shared_services=[…],
     relationships=[…])` for an application-cooperation plate.

   Element specs are `{name, type, documentation?, stereotype?}` — or
   `{name, wilma_id}` to reuse a WILMA reference. Relationship specs are
   `{source, target, type, access_type?}` and reference elements by
   **name** (no IDs to track). Composition / Aggregation relationships
   automatically become visual nesting (e.g. systems inside a
   `Beveiligingsdomein` Grouping). Name a security zone with its NORA/IEC
   trust level (`Beveiligingsdomein - niet-vertrouwd`) so it colours
   correctly. The builder creates the view, every element, every
   relationship, places them and wires the connections in one shot, and
   returns the `view_id` plus name→id maps.

3. **Persist** via `archimate_save_model()` — writes the
   `architecture.archimate` XML AND a rendered SVG per view to
   `docs/diagrams/` in the workspace; no approval gate fires (the
   architect builds the plate freely; the review point is the TD
   itself, not each MCP call). The SVGs are what Gitea-browsing
   reviewers actually see — the raw XML is source-of-truth but Gitea
   flags its invisible Unicode and humans don't read XML.

4. **Embed the view id** in the TD as the ```archimate code block
   shown above, then call `coding_make_design(path, content)` for
   `docs/technical-design.md`. **This is the architect-approval gate.**
   The reviewer sees the markdown + the embedded plate (rendered from
   the just-saved view-id) in one place and approves the TD as a
   whole — including the diagram. Feedback on either the text or the
   plate flows back through this gate.

5. **Commit + push** via `coding_run_git(command="add ...")`,
   `coding_run_git(command="commit ...")`, `coding_run_git(command="push")`.
   Stage three things together: `docs/architecture.archimate`,
   `docs/diagrams/` (the SVG per-view exports written by save_model —
   these are the human-readable view in Gitea), and
   `docs/technical-design.md`. Omitting `docs/diagrams/` leaves
   reviewers staring at raw XML with an invisible-Unicode warning.

## Updating an Existing View (Feedback Iteration)

This is the home of the primitive `create_*` / `add_*` / `update_*` tools:
small, surgical deltas on a view that already exists. (For the *initial*
plate, use the one-shot builder above — don't hand-assemble it element by
element.)

**Change ONLY what the feedback asks for.** Add, modify or remove exactly
the elements and relationships the reviewer named — and **nothing else**. Do
not silently add elements the feedback didn't mention, do not drop existing
ones, and never regenerate the plate from scratch. The reviewer asked for a
delta, not a redraw: any surprise addition or deletion is a defect, even if
the result still looks tidy. When in doubt about whether something is in
scope, leave it as it is.

When the architect gives feedback on an existing TD, **never call
`archimate_delete_view` + `archimate_create_view` on a view that
already exists**, and don't rebuild it with the composite builder either —
both throw away the existing model. Instead:

1. **Read the current state**: `archimate_get_view(view_id)` and
   `archimate_get_element(element_id)` for the elements you may touch.
   `archimate_assess_layout(view_id)` is useful for crowded views — it
   reports element count and density.
2. **Apply only the requested delta**: add new elements with
   `archimate_create_element` + `archimate_add_to_view`. Add new
   relationships with `archimate_create_relationship` +
   `archimate_add_connection_to_view`. Update labels with
   `archimate_update_element` / `archimate_update_relationship`.
3. **The rest of the model is left untouched.** Adding an element re-flows
   the layout on save (the layout engine recomputes positions and edge
   routing) — that is fine: colours, layers, shapes and the Rijnland
   tekenafspraken are derived fresh on every render, so the plate stays
   correct after the change. What must stay the same is the *content* — only
   the requested delta differs; everything you didn't touch is still there.
4. **Save** with `archimate_save_model()` — re-renders all SVGs in
   `docs/diagrams/` too, so the committed SVG matches the new state.
   Don't forget to `git add docs/diagrams/` alongside the .archimate
   file when you push the revision.
5. **Full relayout** is an explicit, approval-gated action via
   `archimate_request_full_relayout(view_id)`. Only use it if the
   architect explicitly asks for a fresh layout — it destroys their
   manual position tweaks.

## TD ↔ Plate Cascade Decisions

A change to the TD does not automatically mean a change to the plate,
and vice versa. Classify the feedback before acting:

| Feedback example | TD edit? | Plate edit? |
|------------------|----------|-------------|
| "Typo in the introduction" | yes | no |
| "Rewrite the trade-off paragraph" | yes | no |
| "Sequence between A and B is wrong" | yes (update mermaid) | no |
| "The message bus is missing from the Application view" | maybe | **yes** (add_to_view) |
| "Relation between Portal and Customer should be Serving, not Flow" | maybe | **yes** (delete_relationship + create_relationship) |
| "Add a Trust Boundary group around Portal and Auth" | yes (note it) | yes (create_view group or add_to_view of a Grouping) |
| "Section X mentions a new component Y" | yes | yes (also add Y to the relevant ArchiMate view) |

If you are unsure whether the cascade applies, ask the architect via
`hitl_ask_question(question="...")` rather than guessing.

## Picking the right type for external systems

Before reaching for the vocabulary tables, three questions in this
order — they almost always pick the right type:

1. **Do WE build / deploy / control it?** (it lives in our repo, on
   our infra, the team can change it) → `ApplicationComponent`.
2. **Is it infrastructure we consume but don't build?** (database
   engines, message queues, IAM platforms, object stores) →
   `SystemSoftware` for the engine itself, `TechnologyService` for
   the service it offers. Examples: Postgres, Redis, Kafka, MinIO,
   Keycloak, ELK stack.
3. **Does it belong to a different organisation that exposes an
   API/service?** (government registers, partner systems, public
   services) → `BusinessActor` for the organisation + `TechnologyService`
   or `ApplicationInterface` for the API surface. Examples: PDOK, KvK,
   BAG, BRP, partner zaaksystemen, Belastingdienst, third-party
   payment providers.

Common mis-typings to avoid:
- PDOK / KvK / BAG / BRP / external SaaS modelled as
  `ApplicationComponent` — they are not your component, you don't
  deploy them. Model the organisation + the service they offer.
- Postgres / S3 / Redis modelled as `ApplicationComponent` — they are
  infrastructure (`SystemSoftware`), not application logic.
- WILMA-imported elements: keep the type WILMA gives them. Most are
  `ApplicationComponent` because they represent waterschap-shared
  building blocks (Zaakbeheercomponent, Notificatierouteringcomponent),
  which is intentional — the waterschap *does* build those.

## ArchiMate Element Vocabulary (v1 supported types)

ArchiMate has many element types; this skill ships with the four
layers we support in v1 — Business, Application, Technology,
Motivation — plus the cross-layer "Grouping" / "Junction" /
"Location". Pick the most specific type that fits.

### Business Layer (yellow `#FFFFB5`)

| Element | When to use |
|---------|-------------|
| BusinessActor | External party or organisation unit (a person, team, company) |
| BusinessRole | A role someone plays in a process |
| BusinessProcess | A sequence of business activities producing a service |
| BusinessFunction | A coherent grouping of business activities (capability-style) |
| BusinessService | An externally-visible service delivered to a consumer |
| BusinessObject | A unit of information at the business level (Customer, Invoice) |
| BusinessEvent | Something that triggers behavior (Application Received) |
| BusinessInterface | Channel through which a service is offered (counter, website) |
| Contract | Formal agreement specifying rights and obligations |
| Product | Bundle of services + contract offered to customers |

### Application Layer (cyan `#B5FFFF`)

| Element | When to use |
|---------|-------------|
| ApplicationComponent | A modular, replaceable software unit (Customer Portal) |
| ApplicationService | Behavior exposed by a component to consumers |
| ApplicationInterface | A point of access to an application service |
| ApplicationFunction | Internal behavior of a component |
| ApplicationProcess | Application-level sequence of behaviors |
| ApplicationEvent | Event affecting application behavior |
| DataObject | A unit of data manipulated by the application (User, Order) |
| ApplicationCollaboration | Aggregation of two or more components acting together |
| ApplicationInteraction | Behavior of an ApplicationCollaboration |

### Technology Layer (green `#C9E7B7`)

| Element | When to use |
|---------|-------------|
| Node | Computational or physical resource that hosts software (Server) |
| Device | Physical IT resource (Database Server, Load Balancer) |
| SystemSoftware | Software environment hosting components (PostgreSQL, Linux) |
| TechnologyService | Service offered by tech nodes (DNS, Storage) |
| TechnologyInterface | Access point to a TechnologyService |
| Artifact | Physical piece of data (deployable file, container image) |
| CommunicationNetwork | Communication links between nodes |
| Path | Logical path that connects two nodes |

### Motivation (purple `#CCCCFF`)

| Element | When to use |
|---------|-------------|
| Stakeholder | Someone with an interest in the outcome |
| Driver | External or internal condition motivating change |
| Goal | High-level statement of intent |
| Outcome | An end result that has been achieved |
| Requirement | Statement of need that must be realized |
| Constraint | Restriction on how requirements may be realized |
| Principle | Generally-applicable property of the architecture |
| Assessment | Result of analysis of a driver |
| Value | Relative worth or importance |
| Meaning | Knowledge/expertise associated with a concept |

### Cross-layer

| Element | When to use |
|---------|-------------|
| Grouping | Aggregation of elements that belong together but lack a stronger relationship (often for trust-boundaries / domains) |
| Location | A conceptual or physical place where elements reside |
| Junction | A connector that joins or splits relationships of the same type |

## ArchiMate Relationship Vocabulary

ArchiMate relationships have precise semantics. Pick the right one —
the renderer draws each with a distinctive arrow.

| Relationship | Semantics | Visual |
|--------------|-----------|--------|
| Composition | Strong "consists of" — child cannot exist without parent | filled diamond at source |
| Aggregation | Weak "groups" — child may exist independently | open diamond at source |
| Assignment | An active element performs / is responsible for a behavior | line, filled circles at endpoints |
| Realization | An element produces or realizes the behavior of another | dashed line, open triangle at target |
| Serving | Source provides functionality to target (used-by) | solid line, open arrow at target |
| Access | Behavior accesses a data object; `access_type` = Read / Write / ReadWrite / Access | dashed line, filled arrow at target |
| Triggering | Source triggers target (temporal / causal) | solid line, filled arrow at target |
| Flow | Data or information flows from source to target | dashed line, filled arrow at target |
| Influence | Source affects achievement of target (motivation layer) | dashed line, open arrow at target |
| Specialization | Source is a kind of target | solid line, open triangle at target |
| Association | Generic catch-all when no other relationship fits | solid line, no arrowhead |

Reach for **Association** only when no other type genuinely fits.
Vague Associations weaken the model. The most-used types for software
designs are Serving, Access, Composition, Realization, and Triggering
or Flow.

## WILMA Reuse — How and Why

WILMA is the waterschappen reference architecture. **Always search
it** when starting a view (cheap, informs design), but reuse
selectively — only when the project is in the waterschap context AND
the WILMA element fits cleanly. For a generic SaaS, an internal
tooling project, or any non-waterschap domain, WILMA reuse is
usually inappropriate; create project-specific elements instead.

When reuse is the right call:

1. `archimate_search_model(query="<keyword>", layer="Business")` →
   find candidates in WILMA.
2. `archimate_get_element(element_name=...)` → confirm the right one.
3. `archimate_get_or_create_wilma_reference(wilma_element_id=...)` →
   imports the element into `architecture.archimate` with the original
   WILMA identifier preserved and a `wilma-source=true` property.
4. Use the returned `element_id` in `add_to_view` and
   `create_relationship` calls as you would any project element.

Do **not** call `archimate_update_element` on a WILMA-sourced element
— they are read-only. If WILMA's definition is wrong for your context,
create a project-specific element with a more accurate name and link
it to the WILMA element via a Realization or Specialization
relationship.

When reuse is **not** the right call: still mention in the TD which
WILMA concepts you considered and why you chose project-specific
modeling. This keeps the rationale visible for peer review without
forcing inappropriate reuse.

## Rijnland / Waterschap Tekenafspraken

When the project sits in the **waterschap context** (the same gate as
WILMA reuse — the FD references waterschappen, bronsystemen,
zaaksysteem, DMS, etc.), the plate must follow the HHR/Rijnland
*tekenafspraken*. These pin each domain concept to a specific ArchiMate
type and a `«stereotype»` label so the plate is peer-review-conform with
the EA-toolchain (Bizzdesign/HoriZZon). Outside the waterschap context,
ignore this section and use plain ArchiMate.

Carry the concept on the element via the `stereotype` parameter of
`archimate_create_element` — e.g. `create_element(element_type=
"BusinessRole", name="Watersysteembeheer", stereotype="Account")`. The
write-MCP rejects a stereotype on the wrong type, and `validate_view`
re-checks it.

**Be consistent.** If an element maps to a concept in the table below,
stereotype it — do not tag only some. A plate where one
`ApplicationComponent` is `«Applicatie»` and three others are bare reads
as half-finished. Every component the waterschap builds/maintains is
`«Applicatie»`; only tag something `«Applicatiefunctie»` instead when it
is genuinely a demarcated building block (bouwblok) in a doel-architectuur,
not a deployable app. Elements that map to no concept (e.g. a generic
`DataObject`, `SystemSoftware`) carry no stereotype — that is fine, but the
choice should be deliberate, not accidental.

### Concept vocabulary (concept → type + stereotype)

| Concept | ArchiMate type | `stereotype` | When |
|---------|----------------|--------------|------|
| Account | BusinessRole | `Account` | Internal collaboration coordinating the info provision of WILMA business (sub)functions |
| Bedrijfsfunctie | BusinessFunction | — | Capability ("what the org can do"), taken from WILMA |
| Applicatie | ApplicationComponent | `Applicatie` | App we **maintain** that does CRUD on business data (incl. web app) |
| 'Eigen' Portaal | ApplicationCollaboration | `'Eigen' Portaal` | Portal for third parties; **we own** the content |
| Website | ApplicationCollaboration | `Website` | A public website we run |
| 'Extern' Portaal | ApplicationInteraction | `'Extern' Portaal` | Third-party portal/app we only **use** |
| 'Externe' informatiebron | ApplicationInteraction | `'Externe' informatiebron` | External data source we read; no waterschap data stored |
| Applicatie als service | ApplicationService | `Applicatie als service` | SaaS consumed from a supplier |
| Applicatiefunctie (bouwblok) | ApplicationFunction | `Applicatiefunctie` | Demarcated functionality, mainly in doel-architectuur; links to WILMA referentiecomponenten |
| Dataobject | DataObject | — | Organised dataset, CRUD-used by ≥1 app/portal |
| Systeem software | SystemSoftware | — | Platform to run apps; no business-data processing (OS, DBMS, middleware) |
| Programmeeromgeving | SystemSoftware | `Programmeeromgeving` | Tool to make reusable scripts; a specialisation of Systeem software |
| Deployed Resource | TechnologyService | `Deployed Resource` | A configured/activated MS Azure resource; specialisation of an Azure ResourceType |
| Account Applicatie Groep | Grouping | `Account Applicatie Groep` | Aggregates the apps/services/portals of one Account; realises a Bedrijfsfunctie |
| Hostingdienst | TechnologyService | `Hostingdienst` | Hosting service that serves a Website |
| Domein registratie | TechnologyService | `Domein registratie` | Domain-registration service; a specialisation of Hostingdienst |
| Hosting partij | BusinessActor | `Hosting partij` | The party that provides a Hostingdienst |
| Registrar | BusinessActor | `Registrar` | The party behind a Domein registratie |
| Artefact | Artifact | `Artefact` | CMDB installset/licentie; realises the app/system software it deploys |
| Locatie | Location | `Locatie` | Exploitation environment grouping (on-prem / cloud / DMZ) — generic, not an exact address |
| Beveiligingsdomein | Grouping | `Beveiligingsdomein` | Security zone — a group of systems with the same trust level |
| Plateau | Plateau | `Plateau` | A future (SOLL) situation; carries the i-aanvraag/wijziging number |
| Programma/Project | WorkPackage | `Programma/Project` | A change initiative; realises a Plateau |

> **`«Account»` is NOT a generic role.** An Account is a specific
> governance construct: an internal collaboration (accountmanager + ICO/
> AVIM) that coordinates the information provision of one or more WILMA
> business (sub)functions and aggregates an "Account Applicatie Groep".
> Do **not** stereotype ordinary handling roles, teams or people
> (Behandelteam, Zaakcoördinator, Beheerder, Burger, …) as `«Account»` —
> those are a plain `BusinessRole` / `BusinessActor` **without** a
> stereotype. Only use `«Account»` when the element genuinely *governs* a
> set of WILMA functions + an application group.

### The ownership rule (active vs behavior shape)

The single most-checked rule: **ownership decides the shape.**
- What **we (technically) maintain** → an *active-structure* type
  (`ApplicationComponent` / `ApplicationCollaboration`): Applicatie,
  'Eigen' Portaal, Website.
- What we **consume from a third party / as SaaS** → a *behavior* type
  (`ApplicationService` / `ApplicationInteraction`): 'Extern' Portaal,
  'Externe' informatiebron, Applicatie als service.

A process is typed by whether it touches business data:
`ApplicationProcess` **does** process business data; `TechnologyProcess`
does **not**.

### Relationship conventions (per situation)

| Situation | Relationship |
|-----------|--------------|
| Functional data flow between apps/services or to/from an external Actor | **Flow** |
| Data transfer between DataObjects via a TechnologyProcess | **Access** Read (source) + **Access** Write (target DataObject) |
| A waterschap (Actor/tenant) uses an app/service/portal | **Association** ("gebruikt/wordt gebruikt") |
| Generic ↔ specific application (specific inherits the couplings) | **Specialization** |
| App/diensten/portalen grouped under an Account Applicatie Groep | **Aggregation** |
| Artefact (CMDB installset/licentie) → the app it realises | **Realization** |
| Programma/Project → Plateau, Account Applicatie Groep → Bedrijfsfunctie | **Realization** |
| Account → Bedrijfsfunctie (assignment of a function) | **Assignment** |
| Bedrijfsfunctie → Bedrijfssubfunctie | **Composition** |
| Principe / Wet & regelgeving affecting a function | **Influence** |

**Direction matters — point the arrow the right way.** A relationship is
read source → target; getting it backwards inverts the meaning.
- **Serving** points from the **provider to the consumer**: the
  application serves the user, so the arrow is `app → Burger`, never
  `Burger → app`. A portal serves the citizen; a backend serves the
  frontend; an infra service serves the app that calls it.
- A person/actor **using** an app is a **tenant-style Association**
  (`Burger — Overlast-meldportaal`, no arrowhead), or model it as the app
  Serving the actor — but do not draw Serving *from* the actor *into* the
  app.
- **Realization** points from the **concrete to the abstract**: a module
  realizes a function (`module-notificatie → Notificatieservice`), an
  Artefact realizes the app it deploys. Source is always the more concrete
  element (`validate_view` flags a reversed Realization).
- **Access** read = data flows **out** of the DataObject into the
  behavior (DataObject is the source side semantics-wise but the arrow
  points at the DataObject); write = into the DataObject. When unsure
  which way a data exchange goes, prefer **Flow** with an explicit name.

### Relationship direction — the rules `validate_view` enforces

Getting the *type* right is half the job; the *direction* is the other half.
These are the metamodel rules the validator now hard-gates — follow them up
front so you don't get bounced:

- **An active element performing a behaviour is `Assignment`, never
  `Triggering`.** Burger → "Melding indienen" is Assignment (actor performs
  process). Triggering is strictly behaviour → behaviour (process triggers
  process, event triggers process). `validate_view` →
  `triggering_from_active_structure`.
- **`Flow` connects two behaviours, or two active-structure elements — never
  a mix, and never data/motivation.** A process does not "flow" into an
  application component; the component (or its service) **serves** the
  process, or the process **accesses** a DataObject. →
  `flow_invalid_endpoints`.
- **Serving points from concrete to abstract: Technology serves Application
  serves Business.** A database/SystemSoftware serves the app; the app serves
  the business process. Never draw the app "serving" its database. →
  `serving_direction`.
- **`Assignment` goes active-structure → behaviour**, not the reverse. →
  `assignment_from_behavior`.

### Apply stereotypes consistently

In a waterschap plate, if one application component carries «Applicatie», the
*other* application components that are also applications must carry it too —
don't stereotype one and leave its siblings bare. The stereotype is what makes
the plate peer-review-conform in the EA-toolchain; a half-stereotyped plate
reads as half-finished. Likewise, name a service for the behaviour it offers
(not "…component") — `validate_view` flags `name_type_mismatch`.

### View organisation (IST / SOLL / doel)

Mirror the Bizzdesign map structure when deciding what a view shows:
- **Doel-architectuur** (visie): Applicatiefunctie/bouwblokken — how
  building blocks *should* cooperate.
- **IST** (informatiesysteem-architectuur): the application-landscape —
  all used apps + their data flows.
- **SOLL** (kansen & oplossingen): a project model with **Plateau**(s)
  for the change vs the IST. Aggregation links a Plateau to the elements
  it touches; the relation name says new/wijzigt/vervalt.

### Security zones (NORA / IEC-62443)

Model a security zone as a **Grouping** with `stereotype=
"Beveiligingsdomein"`. It **must** carry a trust level — either a NORA
level in the name (`niet-vertrouwd`, `semi-vertrouwd`, `vertrouwd`,
`zeer-vertrouwd`), an IEC-62443 `Level Lx`, or a `trust-level` property.
Systems inside the zone are placed in a nested Grouping linked by
**Composition**. A security zone (and a security `Constraint`) renders
in **NORA colours**, not the standard Motivation purple — the renderer
does this automatically from the trust level. `validate_view` flags a
Beveiligingsdomein with no trust level (`security_domain_missing_trust`).

## View Sizing

Keep individual views under ~20 elements. Bigger views become hard to
read regardless of layout quality. Call
`archimate_assess_layout(view_id)` after big edits — it reports an
`ok` or `consider_relayout` recommendation based on element count and
density. If a view grows past ~30 elements, split it into two views
(e.g., "Customer Portal — Application Cooperation" and "Customer
Portal — Technology Realization").

## Self-Verification (run before save_model)

Walk through this checklist before calling `archimate_save_model`. If
any item fails, fix it first.

1. **Element types** are all from the v1-supported set in this skill
   (Business / Application / Technology / Motivation, plus Grouping /
   Junction / Location).
2. **Layers are consistent** with the view's purpose. A view that
   claims to be Application Cooperation should be ≥80% Application-
   layer elements; cross-layer relationships are fine, mixed soup is
   not.
3. **Relationships use the most specific type** that fits — Association
   only when nothing else does.
4. **Every relationship's source and target exist** as elements in
   the same model (the writer will reject otherwise, but checking
   first saves a round-trip).
5. **WILMA search was performed** (always). If the project sits in
   the waterschap context and a WILMA element fits, it was imported
   via `get_or_create_wilma_reference` (preserving the identifier),
   not duplicated with a fresh id. If WILMA was not applicable, the
   TD names which WILMA concepts were considered and why
   project-specific modeling was chosen.
6. **Embed block** in the TD has both `view-id` and `file` keys.
7. **No regenerate-from-scratch** on a view that already existed in
   the previous TD revision. Mutations only.
8. **Rijnland tekenafspraken** (waterschap context only): domain concepts
   carry the right `stereotype` on the prescribed type (Account →
   BusinessRole, Applicatie als service → ApplicationService, …); the
   ownership rule holds (maintained → active shape, consumed → behavior
   shape); every Beveiligingsdomein has a trust level. Run
   `archimate_validate_view` — it returns `rijnland_stereotype_type` and
   `security_domain_missing_trust` codes when these are off.
