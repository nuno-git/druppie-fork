# Druppie - Simplified Goal

## The Only Thing That Matters Right Now

A simple, traceable workflow where **architects design** and **developers build**, with clear approval gates using Keycloak roles.

---

## Users & Roles (Keycloak)

Define in `iac/users.yaml`:

| User | Role | Purpose |
|------|------|---------|
| normal_user | user | Can make requests, triggers workflow |
| architect | architect | Approves architecture/design decisions |
| developer | developer | Approves builds and deployments |
| admin | admin | (Reserved for future - does nothing yet) |

**Roles are checked via Keycloak.** No fake roles, real authentication.

---

## The Workflow

```
User Request
    │
    ▼
┌─────────────────────────────────────────────────────────┐
│  1. ARCHITECT AGENT                                     │
│                                                         │
│  a) Ask user via HITL: "Does this plan look good?"     │
│  b) User confirms                                       │
│  c) Architect calls write_file (architecture.md)       │
│  d) APPROVAL GATE: needs "architect" role to approve   │
│     (because architect.yaml overrides write_file)      │
│  e) Architect user approves → continues                │
└─────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────┐
│  2. DEVELOPER AGENT                                     │
│                                                         │
│  a) Reads architecture.md                               │
│  b) Implements code (write_file, batch_write_files)    │
│     → NO approval needed (mcp_config default)          │
│  c) Builds Docker container (docker:build)             │
│  d) APPROVAL GATE: needs "developer" role to approve   │
│     (because mcp_config.yaml requires it globally)     │
│  e) Runs container (docker:run)                        │
│  f) APPROVAL GATE: needs "developer" role to approve   │
│  g) Developer user approves → deployment complete      │
└─────────────────────────────────────────────────────────┘
    │
    ▼
Done - App Running
```

---

## MCP Permission Gateway (Layered Architecture)

### Two Layers of Approval Rules

1. **mcp_config.yaml** = Global defaults for ALL agents
2. **agent.yaml** = Agent-specific overrides

### Layer 1: MCP-Level Config (`core/mcp_config.yaml`)
**Global defaults. Some tools ALWAYS need approval:**

```yaml
mcps:
  coding:
    url: ${MCP_CODING_URL}
    tools:
      - name: write_file
        description: "Write file to workspace"
        requires_approval: false  # DEFAULT: no approval needed
      - name: batch_write_files
        description: "Write multiple files"
        requires_approval: false  # DEFAULT: no approval needed
      - name: read_file
        description: "Read file from workspace"
        requires_approval: false
      - name: run_command
        description: "Execute shell command"
        requires_approval: false

  docker:
    url: ${MCP_DOCKER_URL}
    tools:
      - name: build
        description: "Build Docker image"
        requires_approval: true
        required_role: developer  # ALWAYS needs developer approval
      - name: run
        description: "Run Docker container"
        requires_approval: true
        required_role: developer  # ALWAYS needs developer approval
```

### Layer 2: Agent-Level Overrides (`agents/definitions/*.yaml`)
**Agents can OVERRIDE defaults for specific tools:**

```yaml
# architect.yaml
name: architect
description: Designs system architecture
mcps:
  - coding
  - hitl
approval_overrides:
  coding:write_file:
    requires_approval: true
    required_role: architect  # OVERRIDE: when architect uses write_file, needs architect approval
```

```yaml
# developer.yaml
name: developer
description: Implements code
mcps:
  - coding
  - docker
  - hitl
# NO approval_overrides needed!
# - write_file uses default (no approval)
# - docker:build/run use global config (developer approval)
```

### How It Works

```
Agent calls tool (e.g., coding:write_file)
    │
    ▼
Check agent's approval_overrides for this tool
    │
    ├─► Override exists? → Use override rules
    │
    └─► No override? → Use mcp_config.yaml defaults
```

**Examples:**

| Agent | Tool | Override? | Result |
|-------|------|-----------|--------|
| architect | write_file | YES (architect.yaml) | Needs architect approval |
| developer | write_file | NO | No approval (mcp_config default) |
| developer | docker:build | NO | Needs developer approval (mcp_config global) |
| developer | docker:run | NO | Needs developer approval (mcp_config global) |

### What We Remove
- ❌ `danger_level` - unnecessary complexity
- ❌ `required_roles: [array]` - just use single `required_role: string`
- ❌ Multiple approval requirement - one role approves, done

---

## Role Definition & Checking

### Define Roles (`iac/realm.yaml`)
```yaml
roles:
  - user
  - architect
  - developer
  - admin
```

### Check Roles (Backend)
```python
# Real Keycloak token check, no fake roles
def check_approval_permission(user_token, required_role):
    user_roles = get_roles_from_keycloak_token(user_token)
    return required_role in user_roles
```

---

## Traceability

Every action is visible to the user:
1. Router decides intent → user sees "Routing your request..."
2. Planner creates plan → user sees the plan steps
3. Architect works → user sees "Architect is designing..."
4. Approval needed → user sees approval UI with file preview
5. Developer builds → user sees "Developer is implementing..."
6. Docker builds → user sees build logs
7. Done → user sees the result URL

**The debug panel shows ALL of this** - every LLM call, every tool call, every approval.

---

## Testing

Run the full flow with:

```bash
./setup.sh all
```

### LLM Keys for Testing
- **DeepInfra**: `TO0zZfaHNsmOKEjt53kKtjzvGTuC50jh`
- **GLM (Z.AI)**: `92faa046321b4c8dba81823da6868e5e.8hhV4Tl2Zb1xftYz`

### Test Scenario
1. Login as `normal_user`
2. Request: "Build me a todo app"
3. Architect agent asks user if plan looks good (HITL)
4. Architect writes architecture.md → **approval needed from architect role** (override)
5. Login as `architect`, approve
6. Developer implements (write_file) → **no approval needed** (default)
7. Developer builds Docker → **approval needed from developer role** (global)
8. Login as `developer`, approve
9. App is built and running

---

## Summary

| Principle | Implementation |
|-----------|----------------|
| Simple users | 4 users: normal_user, architect, developer, admin |
| Simple roles | 4 roles checked via Keycloak |
| Layered approval | mcp_config = defaults, agent yaml = overrides |
| Docker always needs approval | Defined globally in mcp_config.yaml |
| Architect write needs approval | Override in architect.yaml |
| Developer write no approval | Uses default from mcp_config.yaml |
| Full traceability | Debug panel shows everything |

**This is it.** Nothing more until this works perfectly.
