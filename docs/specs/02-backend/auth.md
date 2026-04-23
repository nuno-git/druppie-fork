# Auth

Two parallel auth modes:

1. **User auth** — Keycloak JWT (RS256) decoded on every request. Used by all user-facing endpoints.
2. **Internal auth** — HMAC-SHA256 shared secret (`INTERNAL_API_KEY`). Used by MCP servers calling Druppie back (e.g. sandbox register) and by the sandbox control plane webhook.

## Keycloak integration

`druppie/core/auth.py` (183 lines). `AuthService` class:

- **Token decode** (`decode_token`, line 100–130) — fetches JWKS from `{KEYCLOAK_URL}/realms/druppie/protocol/openid-connect/certs`, validates RS256 signature, checks `iss` against expected issuer, checks `exp`.
- **Health check** (`is_keycloak_available`, line 83–92) — probes `{KEYCLOAK_URL}/realms/druppie/.well-known/openid-configuration`. Cached for 30 s.
- **Role extraction** (`get_user_roles`, line 156–158) — reads `realm_access.roles` array.
- **Role check** (`has_role(role)`, `has_any_role(*roles)`, line 160–170) — admin bypass built in: if `"admin" in roles`, returns True regardless of required role.

### Dev mode

Enabled via `DEV_MODE=true` in `.env`. Short-circuits auth and returns a singleton `DEV_USER` with all roles (`admin, developer, architect, devops`).

Guarded: `decode_token` refuses to activate dev mode if `ENVIRONMENT` is `production` or `staging`. Effectively, dev mode only works with `ENVIRONMENT=development`.

## Dependency injection

`druppie/api/deps.py` (438 lines) defines the FastAPI dependencies routes use.

| Dependency | Purpose |
|------------|---------|
| `get_current_user()` | JWT decode + user sync via `UserRepository.get_or_create()` |
| `get_optional_user()` | Same but returns None instead of raising 401 |
| `verify_internal_api_key()` | HMAC validate `Authorization: Bearer <internal_key>` |
| `get_user_roles()` | Shortcut to `user.roles` list |
| `require_admin()` | Raises 403 if not admin |
| `require_role(role: str)` | Factory returning a Depends that checks role |
| `require_any_role(roles: list[str])` | Factory with OR semantics |

On every authenticated request, `get_current_user()`:
1. Extracts Bearer token.
2. Validates via `AuthService.decode_token()`.
3. Upserts the user in DB (username, email, display_name, roles all synced from the token).
4. Returns a `User` domain model.

If the DB upsert fails, the request fails with 500 — this is treated as critical because downstream code assumes the user row exists.

## Internal API key

Used by:
- `module-coding` calling `POST /api/sandbox-sessions/internal/register` to record sandbox ownership.
- The sandbox control plane calling the webhook `POST /api/sandbox-sessions/{id}/complete` — actually uses a *per-session* HMAC (not the internal key) for better blast-radius isolation; see below.

Constant-time comparison prevents timing attacks (`hmac.compare_digest`).

Production requirement: `INTERNAL_API_KEY` must be overridden from the default `druppie-internal-secret-key`. If `ENVIRONMENT=production` and the key is still the default, the app refuses to start.

## Sandbox webhook signature

The sandbox control plane calls `POST /api/sandbox-sessions/{id}/complete` with:
- `X-Druppie-Signature: hmac-sha256(body, webhook_secret)`

where `webhook_secret` is the per-session random string generated when the sandbox was registered (`SandboxSession.webhook_secret`). This secret is passed to the control plane when the sandbox is created and stored only in DB.

Verification:
1. Look up `SandboxSession` by ID.
2. Compute HMAC of request body using its `webhook_secret`.
3. Compare to header — constant time.

Separate secret per session means a leaked secret only exposes one session.

## Roles (realm + synthetic)

Realm roles (from `iac/realm.yaml`):
- **admin** — composite including developer, architect, business_analyst
- **developer** — approves builds, deployments, PR merges
- **architect** — approves technical designs
- **business_analyst** — approves functional designs (in practice, most design approvals are `session_owner`)
- **infra-engineer, product-owner, compliance-officer** — legacy from earlier scope; still wired for extensibility
- **viewer** — read-only
- **user** — default; can start sessions

Synthetic role: **session_owner** — used in approval records to say "this session's starter must approve". Not present in Keycloak. Resolved at query time by joining `approvals → sessions.user_id`.

## Test users

Seeded by `scripts/setup_keycloak.py` from `iac/users.yaml`:

| Username | Password | Roles |
|----------|----------|-------|
| admin | Admin123! | admin (composite) |
| architect | Architect123! | architect |
| developer | Developer123! | developer |
| analyst | Analyst123! | business_analyst |
| normal_user | User123! | user |

All have `@druppie.local` email addresses.

Additional test users created on demand by evaluations — cleaned up via `DELETE /api/evaluations/test-users` or automatically at end of batch.

## Frontend token handling

`frontend/src/services/keycloak.js`:
- Tokens stored in `localStorage` (`kc_token`, `kc_refresh_token`).
- `onTokenExpired` auto-refreshes with 30 s leeway — transparent to pages.
- `getToken()` called by `api.js` on every request.
- Health checks the Keycloak URL 3× with 2 s delay before init (so transient 502s during dev startup don't break the app).

## Gitea OAuth2

Gitea is configured as an OIDC client of Keycloak. Users log in to Gitea via Keycloak SSO. On first login, Gitea auto-registers an account (username = email local-part). This is why the MCP `module-coding` can act as the user when creating PRs — it uses a personal access token from `user_tokens`.

The `setup_gitea.py` init script configures:
- OAuth2 provider in Gitea → Keycloak `gitea` client.
- Admin user + organization.
- `GITEA_TOKEN` personal access token for the admin, written to `/project/.env` for use by backend services.
