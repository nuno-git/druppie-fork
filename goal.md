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
│  e) Architect user approves → continues                │
└─────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────┐
│  2. DEVELOPER AGENT                                     │
│                                                         │
│  a) Reads architecture.md                               │
│  b) Implements code (write_file, batch_write_files)    │
│  c) ALL MCP tools need "developer" role approval       │
│  d) Builds Docker container                             │
│  e) APPROVAL GATE: needs "developer" role to approve   │
│  f) Developer user approves → deployment complete      │
└─────────────────────────────────────────────────────────┘
    │
    ▼
Done - App Running
```

---

## MCP Permission Gateway (Clean Architecture)

### Agent-Level Config (`agents/definitions/*.yaml`)
Agents specify which MCP tools they can use, but NOT approval rules:
```yaml
# architect.yaml
name: architect
mcps:
  - coding
  - hitl
```

### MCP-Level Config (`core/mcp_config.yaml`)
**All approval rules live here.** Simple structure:
```yaml
mcps:
  coding:
    url: ${MCP_CODING_URL}
    tools:
      - name: write_file
        requires_approval: true
        required_role: architect  # Single role, not array
      - name: batch_write_files
        requires_approval: true
        required_role: developer
      - name: run_command
        requires_approval: true
        required_role: developer
  docker:
    url: ${MCP_DOCKER_URL}
    tools:
      - name: build
        requires_approval: true
        required_role: developer
      - name: run
        requires_approval: true
        required_role: developer
```

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
4. Architect writes architecture.md → **approval needed from architect role**
5. Login as `architect`, approve
6. Developer implements → **approval needed from developer role**
7. Login as `developer`, approve
8. App is built and running

---

## Summary

| Principle | Implementation |
|-----------|----------------|
| Simple users | 4 users: normal_user, architect, developer, admin |
| Simple roles | 4 roles checked via Keycloak |
| Simple approval | One role per tool, configured in mcp_config.yaml |
| Simple agents | Architect designs, Developer builds |
| Full traceability | Debug panel shows everything |
| Clean architecture | Approval rules in MCP config, not agent files |

**This is it.** Nothing more until this works perfectly.
