# Auth, Governance & MCP Upgrade — Design Document

> **Status**: Design (approved via brainstorming)
> **Date**: 2026-03-11
> **Prerequisite**: Read `docs/modules.md` and `docs/module-specification.md`

---

## Table of Contents

1. [Overview](#1-overview)
2. [MCP Protocol Upgrade](#2-mcp-protocol-upgrade)
3. [MCP Server Categories](#3-mcp-server-categories)
4. [Standard Module Arguments](#4-standard-module-arguments)
5. [Authentication](#5-authentication)
6. [Usage Tracking & Analytics](#6-usage-tracking--analytics)
7. [Application Access Control](#7-application-access-control)
8. [Database Tables](#8-database-tables)
9. [Impact on Existing Code](#9-impact-on-existing-code)

---

## 1. Overview

This design covers three interconnected concerns:

1. **MCP protocol upgrade** — migrate all MCP servers to the official FastMCP SDK, make Druppie core a proper MCP client
2. **Unified auth** — Keycloak as the single identity provider for core, apps, and modules, with short-lived tokens for sandbox security
3. **Usage tracking & governance** — every module call is recorded with cost, resource usage, and full context (who, from where, how much)

### Architecture

```
App (SDK = MCP client) ──── MCP protocol ───► Module (MCP server)
                                                │
Agent (Core = MCP client) ── MCP protocol ──►  Module (MCP server)
                                                │
                                                ▼
                                          Usage reporting
                                          (caller records it)
```

**Key decisions:**
- Apps connect directly to modules (SDK is an MCP client). No proxy through Druppie core.
- Druppie core is also an MCP client (for agent workflows).
- Modules report usage via MCP response `_meta`. The caller (core or SDK) records it.
- Auth is token-based (Keycloak JWT). Modules validate tokens themselves.
- Argument injection is core-only. The SDK passes arguments explicitly.

---

## 2. MCP Protocol Upgrade

### Current state

- MCP servers are custom HTTP servers with hand-rolled JSON-RPC
- `MCPClient`/`MCPHttp` in `druppie/core/` makes raw HTTP calls
- Tools are defined in `mcp_config.yaml`, not in the servers themselves

### New state

All MCP servers use **FastMCP** (official Python MCP SDK). Both Druppie core and the Druppie SDK use the official MCP client library.

### Server side

Every MCP server becomes a proper FastMCP server:

```python
from fastmcp import FastMCP

mcp = FastMCP("coding")

@mcp.tool()
async def read_file(path: str, session_id: str, project_id: str) -> str:
    """Read a file from the workspace."""
    ...
```

Modules follow the versioned pattern from the module specification (`server.py` routing to `vN/tools.py`).

### Client side — Druppie Core

Replace `MCPHttp` with the official MCP client, wrapped with Druppie-specific features:

```python
class DruppieToolExecutor:
    """Wraps official MCP client with Druppie-specific features.

    1. Argument injection (core-only: session_id, project_id, etc.)
    2. Approval checking (existing flow, unchanged)
    3. Usage recording (reads _meta.usage, writes to module_usage table)
    """
```

### Client side — Druppie SDK (for apps)

The SDK is also an MCP client, but without injection — apps pass arguments explicitly:

```python
from druppie_sdk import DruppieClient

druppie = DruppieClient()
result = await druppie.modules.call("ocr", "extract_text", {
    "source": "invoice.png",
    "language": "nl",
    # Standard args passed explicitly by SDK:
    # user_id, project_id, app_id (from SDK config + token)
})
```

### What stays in `mcp_config.yaml`

```yaml
mcps:
  coding:
    url: http://coding-mcp:9001
    type: core                    # Core-only, not available to apps
    inject:
      session_id:
        from: session.id
        hidden: true
    tools:
      - name: read_file
        requires_approval: false

  ocr:
    url: http://module-ocr:9010
    type: both                    # Available to agents AND apps
    tools:
      - name: extract_text
        requires_approval: false
```

---

## 3. MCP Server Categories

| Type | Used by | Argument handling | Examples |
|------|---------|-------------------|----------|
| `core` | Agents only | Druppie core injects session_id, project_id, repo_name, etc. from session context | coding, docker, filesearch, archimate |
| `module` | Apps only | SDK passes standard args explicitly | App-specific modules with no agent use case |
| `both` | Agents + Apps | **Core**: injects standard args for agents. **SDK**: passes standard args explicitly for apps | OCR, classifier |

### How to decide

- If the MCP only makes sense during an agent session (needs repo access, workspace, session state) → `core`
- If the MCP is only used by generated apps, not by agents → `module`
- If the MCP is used by both agents and apps → `both`

Core MCPs are invisible to the SDK. Module and both MCPs are discoverable by apps via the SDK.

---

## 4. Standard Module Arguments

Every `module`-type MCP call includes these standard arguments. They enable usage tracking, cost attribution, and analytics without modules needing to know about Druppie's internal database.

### Argument definitions

| Argument | Type | Core (agent) | App (SDK) | Purpose |
|----------|------|-------------|-----------|---------|
| `user_id` | UUID | **REQUIRED** — injected by core from session | **REQUIRED** — extracted from Keycloak token by SDK | Identifies who made the call |
| `project_id` | UUID or null | **OPTIONAL** — injected by core, null for `general_chat` sessions | **REQUIRED** — from SDK config (`DRUPPIE_PROJECT_ID` env var) | Links usage to a project |
| `session_id` | UUID or null | **REQUIRED** — injected by core from session | **MUST be null** | Identifies the agent session |
| `app_id` | UUID or null | **MUST be null** | **REQUIRED** — from SDK config (`DRUPPIE_APP_ID` env var) | Identifies the calling application |

### Validation rules

1. `user_id` is always required
2. Exactly one of `session_id` or `app_id` must be set (never both, never neither)
3. `project_id` is required for apps, optional for core (null when agent has no project, e.g., `general_chat` intent)

### How each caller provides them

**Core (agents):** Arguments are injected by `DruppieToolExecutor` before the MCP call, using the existing injection mechanism. The agent and module never see the injection — it happens transparently.

**SDK (apps):** The SDK reads `user_id` from the Keycloak token and `project_id`/`app_id` from environment variables set at deploy time. It passes them as regular MCP tool arguments on every call.

### Context detection

Modules don't need a separate `context` field. The presence of `session_id` vs `app_id` tells you the calling context:

| `session_id` | `app_id` | Context |
|-------------|---------|---------|
| set | null | Core / agent call |
| null | set | App call |
| set | set | **Invalid** — module should reject |
| null | null | **Invalid** — module should reject |

---

## 5. Authentication

### Single identity provider

Keycloak is the sole identity provider for everything: Druppie core, apps built by Druppie, and module MCP servers. All users exist in the `druppie` realm.

### How each component authenticates

| Component | How it gets a token | Token audience |
|-----------|-------------------|----------------|
| Druppie core (agents) | User logs into frontend → Keycloak JWT. For sandbox: short-lived OBO token | `druppie-backend` |
| Druppie-built app | User logs into app → Keycloak JWT (same realm, app-specific client) | `druppie-modules` |
| Module MCP server | Receives token in request → validates against Keycloak JWKS endpoint | Validates `druppie-modules` or `druppie-backend` |

### Module-side token validation

Every module validates the Keycloak JWT on incoming requests:

```python
# In the module's auth middleware
from jose import jwt

async def validate_token(token: str) -> dict:
    """Validate Keycloak JWT and extract claims."""
    jwks = await fetch_jwks(KEYCLOAK_JWKS_URL)
    claims = jwt.decode(
        token,
        jwks,
        algorithms=["RS256"],
        issuer=f"{KEYCLOAK_URL}/realms/druppie",
    )
    return {
        "user_id": claims["sub"],
        "username": claims.get("preferred_username"),
        "roles": claims.get("realm_access", {}).get("roles", []),
    }
```

### Sandbox security — short-lived tokens

Agents run in sandboxes that must not have long-lived credentials. The same pattern used for GitHub and LLM proxies applies here:

1. Before sandbox launch, Druppie core requests a **short-lived OBO token** from Keycloak:
   - `grant_type=urn:ietf:params:oauth:grant-type:token-exchange`
   - `subject_token={user's token}`
   - `audience=druppie-modules`
   - TTL: 15 minutes
2. Token is stored in the **credential store** (existing infrastructure)
3. Token is injected into the sandbox as `DRUPPIE_MODULE_TOKEN` env var
4. SDK inside the sandbox uses this token for module calls
5. Modules validate it as a normal Keycloak JWT — no special handling

The token carries the original user's identity (`sub` = user_id), so usage is attributed to the correct user even though it's an agent acting on their behalf.

**Token for identity, arguments for context.** The token proves who the user is. The standard arguments (`session_id`, `project_id`, etc.) provide the calling context. These are separate concerns — the token doesn't carry Druppie-specific context.

---

## 6. Usage Tracking & Analytics

### How it works end-to-end

```
Module MCP Server                    Caller (Core or SDK)              Druppie DB
       │                                      │                           │
       │  MCP response with _meta.usage       │                           │
       │─────────────────────────────────────►│                           │
       │                                      │  INSERT module_usage      │
       │                                      │──────────────────────────►│
       │                                      │                           │
       │                                      │  (SDK: POST /api/usage)   │
       │                                      │──────────────────────────►│
```

### Step 1: Module reports usage in MCP response `_meta`

Every module includes usage information in the MCP response `_meta` field (part of the MCP specification):

```json
{
  "result": {
    "text": "Invoice #1234...",
    "confidence": 0.95
  },
  "_meta": {
    "module_id": "ocr",
    "module_version": "2.0.0",
    "usage": {
      "cost_cents": 0.5,
      "resources": {
        "bytes_processed": 204800,
        "pages_scanned": 3,
        "processing_ms": 340
      }
    }
  }
}
```

**Required `_meta` fields:**
- `module_id` — the module's identifier from `MODULE.yaml` (e.g., `"ocr"`)
- `module_version` — the version string from `tools.py` (e.g., `"2.0.0"`)
- `usage.cost_cents` — the cost of this call in cents (required, `0.0` if free)

**Optional `_meta` fields:**
- `usage.resources` — module-specific resource usage (object with arbitrary keys). The keys and their meaning are defined in the tool's `meta.resource_metrics` (see "Resource metric definitions" below).

### Step 2: Caller records usage

The **caller** writes the usage record — not the module:

- **Core** (`DruppieToolExecutor`): reads `_meta` from the MCP response, inserts a `module_usage` record directly into the Druppie database
- **SDK** (`DruppieClient`): reads `_meta` from the MCP response, sends it to the Druppie backend via `POST /api/usage`

This way modules don't need to know about the Druppie database. They just report usage in `_meta` and the caller handles storage.

### Step 3: Analytics queries

Usage can be sliced any way you need:

```sql
-- Per user, per module, this month
SELECT user_id, module_id, SUM(cost_cents) as total_cost, COUNT(*) as calls
FROM module_usage
WHERE created_at >= date_trunc('month', NOW())
GROUP BY user_id, module_id;

-- Per app usage
SELECT app_id, module_id, SUM(cost_cents) as total_cost, COUNT(*) as calls
FROM module_usage
WHERE app_id IS NOT NULL
GROUP BY app_id, module_id;

-- Core (agent) vs app usage
SELECT
    CASE WHEN app_id IS NOT NULL THEN 'app' ELSE 'core' END as context,
    module_id, SUM(cost_cents) as total_cost, COUNT(*) as calls
FROM module_usage
GROUP BY context, module_id;

-- Specific app: usage per user
SELECT u.username, mu.module_id, SUM(mu.cost_cents) as total_cost, COUNT(*) as calls
FROM module_usage mu
JOIN users u ON u.id = mu.user_id
WHERE mu.app_id = 'some-app-uuid'
GROUP BY u.username, mu.module_id;
```

### Resource metric definitions in FastMCP `meta`

Modules declare what resource metrics they report in the `meta` field of their `@mcp.tool()` decorator. This allows the analytics UI to correctly label, format, and display module-specific resource data. The definitions are discoverable via MCP `tools/list`.

```python
# v1/tools.py
@mcp.tool(
    name="extract_text",
    description="Extract text from document images",
    meta={
        "module_id": MODULE_ID,
        "version": MODULE_VERSION,
        "resource_metrics": {
            "bytes_processed": {"type": "integer", "unit": "bytes"},
            "processing_ms": {"type": "integer", "unit": "milliseconds"},
        },
    },
)
async def extract_text(...): ...
```

```python
# v2/tools.py — adds a new metric
@mcp.tool(
    name="extract_text",
    description="Extract text from document images with page detection",
    meta={
        "module_id": MODULE_ID,
        "version": MODULE_VERSION,
        "resource_metrics": {
            "bytes_processed": {"type": "integer", "unit": "bytes"},
            "pages_scanned": {"type": "integer", "unit": "count"},
            "processing_ms": {"type": "integer", "unit": "milliseconds"},
        },
    },
)
async def extract_text(...): ...
```

### The full chain: module response → analytics display

1. **Module** returns `_meta` with `module_id`, `module_version`, and `usage` (including `resources`)
2. **Caller** (core or SDK) copies `module_id`, `module_version`, `cost_cents`, and `resources` (as JSON string) into a `module_usage` record
3. **Analytics layer** reads a `module_usage` record, calls MCP `tools/list` on the module to get `resource_metrics` definitions for that version
4. **Analytics UI** uses the metric definitions (name, type, unit) to correctly label and format the resource data

This means:
- The `resources` field in `module_usage` is a plain JSON string — never queried by sub-field (follows Druppie's NO JSONB rule)
- The MCP server provides the schema for interpreting it via `tools/list` `meta.resource_metrics`
- If v2 adds `pages_scanned`, the MCP server reports that metric, and the analytics UI renders it correctly

---

## 7. Application Access Control

### Model

Every Druppie-built app has its own role-based access control. Roles and user assignments live in the **app's own database**, not in Druppie's core DB. The project template provides RBAC tables, helpers, and an admin page out of the box.

### Why roles live in the app, not in Druppie

Access control is application-specific. Different apps need different roles, different permissions, and may need to extend with resource-level access later. Keeping it in the app:

- App is self-contained — works even if Druppie is down
- Role checks are local (no network call to Druppie backend)
- Apps can extend with custom permissions without touching Druppie
- No coupling between Druppie's DB and app-specific data

### How it works

1. Druppie builds an app → project template includes RBAC tables and admin page
2. App admin defines roles (e.g., "viewer", "editor", "admin") via the app's built-in admin page
3. App admin assigns Keycloak users to roles (same Keycloak realm, same users)
4. User logs into the app → gets a Keycloak JWT (standard flow, same realm)
5. App checks roles locally against its own DB
6. App uses roles to gate access to features

### What the project template provides

The RBAC system is part of the project template (`druppie/templates/project/`). Apps get it for free:

- `roles` and `user_roles` tables (created by template migrations)
- Admin page for managing roles and user assignments
- Auth helpers for role checking in routes
- Keycloak login/logout already wired up

### SDK usage in apps

```python
from druppie_sdk import DruppieClient

druppie = DruppieClient()

# Check roles against the app's own database (local, no network call)
user_roles = druppie.auth.get_user_roles(user_id)
# Returns: ["editor"] or [] if no access

# Guard a route
if "editor" not in user_roles:
    raise HTTPException(403, "No access")
```

### Future: central management

If we need Druppie to manage access across apps centrally, each app can expose a `/druppie/access` endpoint (added to the project template) that Druppie calls to list/modify roles. This keeps apps self-contained while enabling central oversight when needed.

---

## 8. Database Tables

### New tables (all in Druppie core database)

#### module_usage

Records every module call with full context:

```sql
CREATE TABLE module_usage (
    id UUID PRIMARY KEY,

    -- Who
    user_id UUID NOT NULL REFERENCES users(id),

    -- Context (session XOR app)
    session_id UUID REFERENCES sessions(id),
    app_id UUID REFERENCES applications(id),
    project_id UUID REFERENCES projects(id),

    -- What
    module_id VARCHAR(100) NOT NULL,
    tool_name VARCHAR(100) NOT NULL,
    module_version VARCHAR(20),

    -- Result
    success BOOLEAN NOT NULL,
    error_message TEXT,

    -- Cost & resources
    cost_cents FLOAT NOT NULL DEFAULT 0.0,
    resources TEXT,              -- JSON string of module-reported resources (NOT JSONB)

    -- When
    started_at TIMESTAMPTZ NOT NULL,
    duration_ms INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

> `resources` is stored as Text (JSON string), not JSONB — following Druppie's "NO JSON/JSONB columns" rule. It's never queried by sub-field, only displayed. The schema for interpreting it comes from the module's MCP `tools/list` `meta.resource_metrics`.

#### applications

```sql
CREATE TABLE applications (
    id UUID PRIMARY KEY,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    owner_id UUID NOT NULL REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

> `application_roles` and `application_user_roles` live in each app's own database (provided by the project template), not in Druppie's core DB. See Section 7.

---

## 9. Impact on Existing Code

### What changes

| Component | Change | Effort |
|-----------|--------|--------|
| `druppie/core/mcp_client.py` | Replace with official MCP client library, keep injection wrapper | High — core rewrite |
| `druppie/execution/tool_executor.py` | Add usage recording after MCP calls, read `_meta` | Medium |
| `druppie/core/mcp_config.yaml` | Add `type: core\|module\|both` to each MCP entry | Low |
| `druppie/mcp-servers/coding/` | Migrate to FastMCP server | High |
| `druppie/mcp-servers/docker/` | Migrate to FastMCP server | High |
| `druppie/mcp-servers/filesearch/` | Migrate to FastMCP server | Medium |
| `druppie/mcp-servers/archimate/` | Migrate to FastMCP server | Medium |
| `druppie/db/models/` | Add module_usage, applications tables | Medium |
| `druppie/services/` | Add UsageTrackingService | Medium |
| `druppie/api/routes/` | Add usage endpoints | Medium |
| `druppie-sdk/` | New package: MCP client + auth + usage reporting | High — new code |
| `druppie/agents/builtin_tools.py` | Update sandbox launch to include short-lived module token | Low |
| `iac/realm.yaml` | Add `druppie-modules` audience, configure token exchange | Low |
| Module `tools.py` | Add `resource_metrics` to `@mcp.tool(meta={...})` | Low per module |

### What does NOT change

- Keycloak realm structure (users, roles) — unchanged, just adding a client/audience
- Frontend auth flow — unchanged
- Agent YAML definitions — unchanged
- Approval system — unchanged (still works through the tool executor)
- Database schema for existing core tables — unchanged
