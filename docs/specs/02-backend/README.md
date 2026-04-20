# 02 — Backend

Detailed specs for the FastAPI backend at `druppie/`.

## Files

- [api-routes.md](api-routes.md) — Every HTTP endpoint
- [services.md](services.md) — Service layer: business logic + authorization
- [repositories.md](repositories.md) — Data access, domain conversion
- [domain-models.md](domain-models.md) — Pydantic models (Summary/Detail)
- [db-models.md](db-models.md) — SQLAlchemy tables, columns, relationships
- [auth.md](auth.md) — Keycloak JWT, dev mode, internal API key, role checks
- [errors.md](errors.md) — Exception hierarchy, HTTP mapping
- [startup.md](startup.md) — Lifespan handler, crash recovery, watchdog

Where appropriate, each file cites file paths and line numbers. All code references are for the `colab-dev` branch at the time of writing.
