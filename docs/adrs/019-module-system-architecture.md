---
id: "019"
title: Adopt the Druppie Module System architecture (SDK + MCP hybrid with direct module access)
status: accepted
date: 2026-03-11
deciders:
  - Druppie team
  - Nuno
supersedes: null
superseded_by: null
linked_prd: docs/prds/008-module-system.md
linked_research: docs/research/003-module-convention.md
---

## Context

The platform must support capabilities beyond its core agent pipeline — OCR,
document classification, ArchiMate generation, data access, translation, and
the like. Without a module system, every such capability would be tightly
coupled to the backend: adding a tool means modifying core code, deployment is
monolithic, and versioning is all-or-nothing. Generated applications also need
access to the same tools at runtime, but with a different auth context than the
agents that build them.

PRD 008 (`docs/prds/008-module-system.md`) states the goal: containerized MCP
servers ("modules") that expose tools via the standard MCP protocol, are
independently versioned (multiple major versions coexist via path-based
routing), independently deployable, and callable by both Druppie agents
(build-time, session context) and generated applications (runtime, app
context). Each module manages its own storage, authenticates its own requests,
and reports usage back to the caller.

Research 003 (`docs/research/003-module-convention.md`) explored five
architectures (built-in MCP server, library/import, SDK+MCP hybrid,
template-based code generation, composable MCP with shared DB + gateway) and
arrived at a layered recommendation. **This ADR records only the resulting
architectural decisions.** The full technical contract — MODULE.yaml field
reference, file layout, DB schemas, SDK interface, auth flow, code templates,
and the OCR v1.0→v2.0 worked example — lives in Research 003, **Part III —
Resulting Technical Specification**.

## Decision

Adopt the **SDK + MCP Hybrid with direct module access** architecture
(Approach C from Research 003, **without** the shared database and **without**
the gateway proxy from Approach E). The eight commitments below fix the
architecture; bracketed references (e.g., `[R003 §31]`) point to the full
rationale and technical contract in Research 003.

1. **SDK + MCP Hybrid (Approach C, without shared DB or gateway proxy).** The
   system has three layers: Layer 0 = MCP module servers (one container per
   capability, own DB or stateless); Layer 1 = Druppie SDK (a pip-installable
   MCP client included in every generated application); Layer 2 = project
   template (build-time, ships as a working app with auth, RBAC, landing page,
   SDK, and Dockerfile pre-wired). Apps connect **directly** to module MCP
   servers — no gateway proxy. Approach E's shared database (Druppie
   PostgreSQL with schema isolation) is explicitly rejected for the coupling,
   portability, and reset-fragility reasons documented in Research 003 §9 and
   §11.

2. **MODULE.yaml as source of truth for module identity and active versions.**
   Each module has exactly one YAML manifest at its root, containing only
   three fields: `id`, `latest_version`, and `versions` (the active major
   versions). Everything else — server name, description, tool schemas, agent
   guidance, resource-metric definitions — is defined once in the FastMCP
   server code and discovered at runtime via MCP `initialize` and
   `tools/list`. No duplication between YAML and code; no per-version manifest
   files. `[R003 §14, §29]`

3. **Versioned directory pattern (`server.py` root router + `vN/module.py`
   per major version).** Each major version is an independent, self-contained
   codebase in its own directory. The root `server.py` mounts each version's
   MCP app at its path (`/v1/mcp`, `/v2/mcp`, `/mcp` → latest). Minor and
   patch bumps update code in-place inside the version directory; major bumps
   create a new sibling directory. No translation layer, no transformer chain
   between versions. `[R003 §10, §28, §31]`

4. **MCP protocol (JSON-RPC over HTTP) with three categories: core, module,
   both.** All module and core MCP servers use FastMCP (official Python MCP
   SDK). The `type` field in `mcp_config.yaml` bounds reachability: `core`
   (agents only — coding, docker, filesearch, archimate), `module` (apps only
   — app-specific modules), `both` (agents + apps — OCR, classifier). Core
   MCPs are invisible to the SDK; module and both MCPs are discoverable by
   apps. `[R003 §20, §33]`

5. **Authentication via injected MCP parameters — modules never query
   Druppie's DB directly.** Druppie context (`user_id`, `session_id` for
   agents, `app_id` for apps, `project_id`) is passed as standard MCP tool
   arguments; `user_id` is always required and exactly one of `session_id` /
   `app_id` must be set. Keycloak is the sole identity provider; modules
   validate Keycloak JWTs themselves against the JWKS endpoint (no gateway
   proxy). For sandboxes, Druppie core mints short-lived OBO tokens (TTL 15
   min) so agent-run code never holds long-lived credentials. `[R003 §15, §34,
   §35]`

6. **RBAC in each app's own database, not in Druppie core.** Application
   roles (viewer, editor, admin) and user-role assignments live in the app's
   own database, provided by the project template (`roles`, `user_roles`
   tables + admin page + Keycloak login already wired). Apps stay
   self-contained — they keep working if Druppie is down, and role checks are
   local with no network call. `[R003 §21, §37]`

7. **SDK at `druppie/sdk/` — a thin pip-installable package.** The Druppie
   SDK lives in the monorepo at `druppie/sdk/` and is installed into every
   generated app via the project template. It is an MCP client (no gateway):
   it resolves module URLs from config, injects standard arguments, performs
   retries with backoff, extracts `_meta.usage` from responses, and reports
   usage to the Druppie backend. Typed accessors (e.g.,
   `druppie.ocr.extract(...)`) provide ergonomic per-module APIs. `[R003 §18,
   §39]`

8. **Usage tracking via MCP `_meta`, caller writes to the `module_usage`
   table.** Every module includes `module_id`, `module_version`, and `usage`
   (`cost_cents` + module-specific `resources`) in the MCP response `_meta`.
   The caller — not the module — records the usage: Druppie core inserts
   directly into the Druppie `module_usage` table; the SDK `POST`s to
   `/api/usage` on the Druppie backend. Attribution is by user, project,
   session (agent calls) or app (app calls), enabling cost analytics without
   modules knowing anything about Druppie's schema. `[R003 §22, §36, §38]`

## Consequences

Positive:

- **Independent capability delivery.** A new capability is a new container +
  a YAML block — additive only, no core code changes, no monolithic deploy.
- **Independent versioning.** Multiple major versions coexist via path-based
  routing (`/v1/mcp`, `/v2/mcp`); existing clients keep working when a new
  major version ships.
- **Self-contained modules.** Each module owns its own storage and validates
  its own auth — developable, testable, and runnable without any Druppie
  infrastructure except the MCP protocol.
- **Single source of truth.** `MODULE.yaml` is three fields; everything else
  is defined once in FastMCP code and discovered via MCP. No drift between
  YAML manifests and `@mcp.tool()` decorators.
- **Clean agent and app ergonomics.** Agents discover modules via
  `list_druppie_modules`; apps call modules via the SDK with three lines of
  code. Auth, retries, usage reporting, and version routing are handled once
  in the SDK.
- **Per-user, per-app cost attribution.** Modules report usage in `_meta`;
  the caller writes the `module_usage` record. Slicing by user, module, app,
  or context is a plain SQL query.
- **Token for identity, arguments for context.** Keycloak tokens prove who
  the user is; standard MCP arguments carry the calling context. Sandboxes
  get short-lived OBO tokens, never long-lived credentials.
- **App RBAC is local.** Roles live in each app's own database via the
  project template; apps work even if Druppie is down.

Negative:

- **Network overhead.** Every module call is an HTTP round-trip (~1–10 ms);
  no in-process fast path (Approach B was rejected for its dependency and
  isolation costs).
- **Container cost.** Each module is a running container consuming memory
  when idle; the platform must budget for this.
- **Cross-version code duplication.** Independent version directories mean
  business logic is not shared — a bug in shared business logic must be fixed
  independently in each version. (Shared *infrastructure* — `server.py`,
  `db.py`, `auth.py` — is fixed once at the root.)
- **Additive-only DB discipline.** All major versions share one module
  database; every new column needs a `DEFAULT`, no `DROP`/`RENAME`/`ALTER
  TYPE`, and `SELECT *` is banned.
- **SDK maintenance.** Typed accessors lag behind new module methods until
  the SDK is updated.
- **Python-only first.** The SDK and project template are Python; non-Python
  app support is a future addition.
- **No module registry UI / no hot-reload / no sunset mechanism.** Discovery
  is via `mcp_config.yaml` + live MCP calls; module changes require a
  container restart; all versions run indefinitely (removing one is a manual
  operational step).

## Related

- **Research 003** — `docs/research/003-module-convention.md` — full design
  rationale (Parts I & II) and the resulting technical specification
  (Part III): MODULE.yaml reference, file layout, DB schemas, SDK interface,
  auth flow, code templates, OCR v1.0→v2.0 worked example, and impact on
  existing code.
- **PRD 008** — `docs/prds/008-module-system.md` — product requirements.
- **Spec 020** — `docs/specs/020-module-contract.feature` — executable
  acceptance scenarios for the module contract.
