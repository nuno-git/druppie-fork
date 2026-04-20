# Gitea

Self-hosted Git server. `gitea/gitea:1.21`, port 3100 HTTP + 2223 SSH.

Plays two roles:
1. **Project repo store** — every Druppie project gets a Gitea repo.
2. **Reference source** — cross-project file lookup via `coding:list_projects` etc.

## Configuration

`docker-compose.yml` sets Gitea via env vars:
- `GITEA__database__DB_TYPE=postgres`.
- `GITEA__database__HOST=gitea-db:5432`.
- `GITEA__server__DOMAIN=gitea`, `SSH_DOMAIN=localhost`.
- `GITEA__server__ROOT_URL=http://localhost:3100/`.
- `GITEA__openid_connect__ENABLE_AUTO_REGISTRATION=true`.
- `GITEA__openid_connect__ACCOUNT_LINKING=auto`.
- `GITEA__openid_connect__USERNAME=email` (username = email local-part).
- `GITEA__service__DISABLE_REGISTRATION=false`.
- `INSTALL_LOCK=true` (skip the install wizard).

## Init script

`scripts/setup_gitea.py`:
1. `wait_for_gitea()` — poll `/api/v1/version` up to 30× over 150s.
2. `gitea admin user create` (via `docker exec`) — creates `GITEA_ADMIN_USER` (default `gitea_admin`) with password from env.
3. Configure OAuth2 with Keycloak:
   - Endpoint: `http://keycloak:8080/realms/druppie/.well-known/openid-configuration` (internal URL).
   - Client: `gitea` (confidential client in Keycloak).
   - Secret: `GITEA_CLIENT_SECRET`.
4. Create organization `druppie`.
5. Generate `GITEA_TOKEN` (personal access token for the admin) and write to `/project/.env`.

The admin token is used by Druppie's `module-coding` and `module-docker` for all git operations.

## Per-user vs shared token

Today's MVP uses the admin token for all operations. The `user_tokens` table in Druppie's DB supports per-user Gitea tokens; the plan is to use them for attribution ("this commit was made on behalf of <user>"). Not yet wired.

## Repository shape

Each project repo has:
- Default branch: `main`.
- Initial commit: auto-generated from `druppie/templates/project/` (via agent workflow, not template copy).
- Feature branches: `feature/<description>` for update_project flows.

After the full pipeline runs, a typical repo has:
- `docs/functional_design.md`
- `docs/technical_design.md`
- `docs/builder_plan.md`
- `app/` (backend code)
- `frontend/` (frontend code)
- `tests/` (pytest + vitest)
- `docker-compose.yaml`, `Dockerfile`
- `.gitignore`

## API usage

Druppie's `module-coding` uses Gitea REST API:

- `GET /api/v1/repos/{owner}/{repo}` — fetch repo.
- `POST /api/v1/orgs/{org}/repos` — create.
- `DELETE /api/v1/repos/{owner}/{repo}` — delete.
- `GET /api/v1/repos/{owner}/{repo}/contents/{path}?ref=…` — read file.
- `GET /api/v1/repos/{owner}/{repo}/git/trees/{sha}?recursive=true` — list tree.
- `POST /api/v1/repos/{owner}/{repo}/pulls` — create PR.
- `POST /api/v1/repos/{owner}/{repo}/pulls/{num}/merge` — merge PR.

All requests authenticate with `Authorization: token ${GITEA_TOKEN}`.

## Users

Gitea users are auto-provisioned via OIDC on first login. Username = email local-part (e.g. `developer` for `developer@druppie.local`).

Test runs create temporary users with patterns like `test_user_abc123` — cleanup via `/api/evaluations/test-users` endpoint or at the end of the batch.

## Storage

`druppie_new_gitea` volume holds repos (including LFS if enabled). `druppie_new_gitea_postgres` holds metadata (users, orgs, PRs, etc.).

Backups not configured in the default compose file. Production would add a scheduled pg_dump.

## Production-ready notes

- Override `GITEA_ADMIN_PASSWORD` from default `GiteaAdmin123`.
- Set `GITEA__server__ROOT_URL` to the public domain with TLS.
- Consider external Git hosting (GitHub, internal GitLab) for large teams — Druppie only needs a git server that supports the REST API shape used by `module-coding`.
