# Scripts

`scripts/` directory inventory.

## Init / reset

### `setup_keycloak.py`
Creates the `druppie` realm, roles, OAuth2 clients, users. Reads `iac/realm.yaml` + `iac/users.yaml`. Retries the Keycloak admin-cli handshake 10× over 50s. Idempotent — re-running picks up changes to `iac/*.yaml` without duplicating entities.

### `setup_gitea.py`
Creates the Gitea admin user, configures OAuth2 with Keycloak, creates the `druppie` organization and seed repository, generates `GITEA_TOKEN`, writes it to `/project/.env`. Also uses `docker exec` to run `gitea` CLI commands inside the Gitea container.

### `init-entrypoint.sh`
Runs on `druppie-init` container start. Checks `/init-marker/.initialized`. If absent: runs setup_keycloak.py + setup_gitea.py, touches the marker, exits.

### `reset-hard.sh` (~98 lines)
1. `docker compose --profile dev --profile prod --profile infra down -v`.
2. Remove named volumes individually (explicit list).
3. `docker compose --profile infra up -d`.
4. Wait for PostgreSQL / Keycloak / Gitea healthchecks (30 attempts, 2-3 s each).
5. Run `setup_keycloak.py` + `setup_gitea.py`.
6. Print next-steps banner.

### `nuke.sh` (~125 lines)
1. Stop all containers (every profile).
2. Remove all named volumes.
3. Remove local images (keeps upstream like `postgres:*`, `quay.io/*`, `docker:*`).
4. `git submodule update --init --recursive` (if applicable).
5. If `START_AFTER=true` (default): `docker compose --profile dev --profile init up -d --build`. Print URLs.
6. Else: exit, print manual instructions.

Intended for "my state is broken, start over" scenarios. Fully destructive.

## Testing

### `run_tests.sh`
Runs pytest on `testing/` directory.

### `test_api.sh` (~11KB)
API smoke tests — curl-based sanity checks of every major endpoint. Used for post-deploy validation.

## Seeding

### `seed_builder_retry.py` (~31KB)
Seeds the database with fixtures representing a builder retry scenario (tests failed 2×, third attempt). Used to develop/test the TDD retry UX without running the full pipeline.

### `seed_deployer_test.py` (~23KB)
Seeds a session paused on a `docker:compose_up` approval gate. For testing the Tasks page approval flow.

### `seed_update_core.py` (~24KB)
Seeds a session targeting the Druppie core with an `update_core_builder` run. For developing that agent's UI.

## Sandbox cache

### `scan-cache.sh`
Runs OSV-scanner across the sandbox cache volume's contents. Produces JSON reports per manager (npm, pnpm, pip, uv, bun). Packaged in `Dockerfile.cache-scanner`.

## Conventions

- All shell scripts start with `#!/usr/bin/env bash` and `set -e`.
- Idempotent where possible (setup scripts).
- Sensitive operations (nuke, reset-hard) print warnings and require explicit profile invocation.
- Scripts that modify `.env` use heredoc for the file write; the token insertion step is the main use case.

## Adding a new script

1. Place in `scripts/`.
2. If invoked from a container, add to `Dockerfile.init` / `Dockerfile.reset` COPY.
3. Make executable: `chmod +x scripts/<name>.sh`.
4. If invoked from docker-compose, add a new service definition referencing it.
5. Document in `08-infrastructure/scripts.md` (this file).

## Running scripts locally vs in containers

- **setup_keycloak.py, setup_gitea.py** — inside `druppie-init` container (has `docker-cli`, reaches `keycloak:8080` on the internal network).
- **seed_*.py** — run inside `druppie-backend-dev` with `docker compose exec druppie-backend-dev python /app/scripts/seed_*.py`.
- **reset-hard.sh, nuke.sh** — run in their own throwaway containers with host network + Docker socket access.
