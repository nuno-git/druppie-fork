# iac/

Infrastructure-as-code for identity. Two YAML files that `setup_keycloak.py` reads.

## `iac/realm.yaml`

Defines the Keycloak realm configuration:

- **Realm-level settings** — registration disabled, password reset allowed, email login, token lifespans.
- **Password policy** — length, case, digits.
- **Brute force protection** — maxFailureWaitSeconds, failureFactor.
- **Realm roles** — baseline list (user, developer, architect, business_analyst, infra-engineer, product-owner, compliance-officer, viewer) + composite `admin`.
- **Client scopes**:
  - `druppie-roles` — includes realm_access.roles in tokens.
  - `mcp-permissions` — for future per-tool permission claims.
- **Clients**:
  - `druppie-frontend` — public, standard flow, PKCE, redirect URIs.
  - `druppie-backend` — confidential, service accounts enabled.
  - `gitea` — confidential, for OAuth2 login to Gitea.

Values like `${EXTERNAL_HOST}`, `${FRONTEND_PORT}` are templated at init time using env.

## `iac/users.yaml`

Two functions:

### 1. Users + roles

```yaml
users:
  - username: admin
    email: admin@druppie.local
    password: Admin123!
    roles: [admin]
  - username: architect
    email: architect@druppie.local
    password: Architect123!
    roles: [architect]
  # ...
```

Each user gets a Keycloak account; roles are assigned as realm roles.

Default password is `ChangeMe123!` if omitted (but all seed users have explicit ones).

### 2. Approval workflows + MCP permission levels (future use)

```yaml
approval_workflows:
  deployment:
    required_roles: [infra-engineer, product-owner]
  code_change:
    required_roles: [developer, architect]
  compliance_change:
    required_roles: [compliance-officer]

mcp_permission_levels:
  auto:        [filesystem.read, git.status, git.log, git.diff, docker.ps, docker.logs]
  userApprove: [filesystem.write, shell.run, git.commit]
  roleApprove: [git.push, git.merge, docker.build, docker.run, docker.deploy]
```

These sections are NOT consumed by Druppie's current code — the live approval logic lives in `druppie/core/mcp_config.yaml` + agent YAML `approval_overrides`. They're declarative documentation for where approval governance is heading.

## Why YAML

- Version-controllable.
- Editable without Keycloak admin UI clicking.
- Diffable in PRs.
- Re-applicable idempotently.

A team member's new role grant goes:
1. Edit `iac/users.yaml`.
2. `docker compose --profile init up -d` → setup_keycloak.py re-runs → role applied.

Or manually via Keycloak admin UI for one-off changes (which don't survive a reset-hard).

## Env var substitution

Inside YAML values, `${VAR:-default}` works because `setup_keycloak.py` pre-processes the file through a small templating pass:

```yaml
rootUrl: "http://${EXTERNAL_HOST}:${FRONTEND_PORT}/"
redirectUris:
  - "http://${EXTERNAL_HOST}:${FRONTEND_PORT}/*"
```

## Seed user cleanup

Test users created during evaluation runs are NOT in `iac/users.yaml`. They're created programmatically by `EvaluationService` / `TestRunner` and cleaned up via:
- `DELETE /api/evaluations/test-users` — API call.
- Batch end — automatic cleanup.
- `docker compose --profile reset-hard` — full wipe.

The users defined in `iac/users.yaml` are permanent fixtures that survive resets.
