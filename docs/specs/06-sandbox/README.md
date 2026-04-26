# 06 — Sandbox

`background-agents/` is vendored from the `nuno120/background-agents` repo (`druppie` branch). It provides isolated coding sandboxes that Druppie agents invoke via the `execute_coding_task` builtin tool.

## Files

- [packages.md](packages.md) — Top-level package inventory
- [local-control-plane.md](local-control-plane.md) — Express + SQLite control plane for dev
- [local-sandbox-manager.md](local-sandbox-manager.md) — Python/FastAPI spawner (Docker/Kata)
- [llm-proxy.md](llm-proxy.md) — Provider chain routing + streaming passthrough
- [control-plane.md](control-plane.md) — Production Cloudflare Workers + D1 version
- [modal-infra.md](modal-infra.md) — Modal Labs sandbox runtime for production
- [sandbox-image.md](sandbox-image.md) — `open-inspect-sandbox:latest` contents
- [integration.md](integration.md) — How Druppie talks to the sandbox system
- [integration-bots.md](integration-bots.md) — Slack, GitHub, Linear bots (outside Druppie's direct use)

## Why vendored

- Druppie depends on specific behaviour: webhook shapes, ownership tracking, per-session HMAC secrets.
- Changes to the sandbox system ship through the Druppie repo's CI.
- Future: extract as a git submodule or npm package once the interface stabilises.

## Local vs production

| Environment | Control plane | Sandbox runtime |
|-------------|---------------|-----------------|
| **Local dev** | `local-control-plane` (Express, port 8787) | `local-sandbox-manager` (Docker/Kata on host daemon) |
| **Production** | `control-plane` (Cloudflare Workers + D1) | `modal-infra` (Modal Labs sandboxes) |

Druppie uses the local path today. Production has been terraformed but not yet routed through.
