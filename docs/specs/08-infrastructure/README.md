# 08 — Infrastructure

Docker, Dockerfiles, init scripts, identity/VCS setup, environment variables, and Terraform for the production sandbox path.

## Files

- [docker-compose.md](docker-compose.md) — Every service + profile + volume + network
- [dockerfiles.md](dockerfiles.md) — Backend, init, reset, cache scanner, sandbox images
- [keycloak.md](keycloak.md) — Realm config, roles, test users, OAuth2 clients
- [gitea.md](gitea.md) — OIDC login, admin user, org, tokens
- [environment.md](environment.md) — `.env.example` variable reference
- [scripts.md](scripts.md) — `scripts/` inventory
- [iac.md](iac.md) — `iac/realm.yaml` + `iac/users.yaml` authoritative config
- [terraform.md](terraform.md) — `background-agents/terraform/` for production sandbox
