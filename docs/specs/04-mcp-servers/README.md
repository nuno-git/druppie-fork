# 04 — MCP Servers

Every MCP module is a self-contained Docker service with its own Dockerfile, `MODULE.yaml`, versioned tool directory, and port. Six modules ship with Druppie today.

## Files

- [module-convention.md](module-convention.md) — Contract every module must follow
- [module-router.md](module-router.md) — Shared factory (eliminates server.py boilerplate)
- [mcp-config.md](mcp-config.md) — `druppie/core/mcp_config.yaml` + approval model
- [module-coding.md](module-coding.md) — Port 9001, 21 tools, the workhorse
- [module-docker.md](module-docker.md) — Port 9002, 10 tools, container orchestration
- [module-web.md](module-web.md) — Port 9005, 6 tools, HTTP + search
- [module-filesearch.md](module-filesearch.md) — Port 9004, 4 tools, dataset search
- [module-registry.md](module-registry.md) — Port 9007, 6 tools, self-description
- [module-archimate.md](module-archimate.md) — Port 9006, 8 tools, architecture model queries

## Port map

| Port | Module |
|------|--------|
| 9001 | coding |
| 9002 | docker |
| 9004 | filesearch |
| 9005 | web |
| 9006 | archimate |
| 9007 | registry |
| 9010–9099 | reserved for user-added modules |
| 9100–9199 | reserved for deployed user app containers |

## Transport

All modules use **FastMCP over HTTP** via Starlette + Uvicorn. Routing per module:

```
/health             → aggregate health (latest version)
/v1/mcp             → FastMCP JSON-RPC endpoint for v1
/v1/health          → per-version health
/mcp                → alias for latest version
```

## Why per-module containers

- Isolation — a misbehaving module can't crash others.
- Independent deploy — modules can ship on their own cadence.
- Resource limits — docker-compose can cap memory/CPU per module.
- Language freedom — each module can be any language; today all are Python.
