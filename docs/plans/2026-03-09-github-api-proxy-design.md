# GitHub API Proxy for Sandbox Agents

**Date:** 2026-03-09
**Status:** Implemented

## Problem

Sandbox agents (druppie-builder) need GitHub API access to create PRs, read issues, and
interact with the repository. The sandbox security model prevents direct credential exposure —
all auth is injected server-side via proxies.

The `gh` CLI requires HTTPS for enterprise hosts, making it impossible to redirect to our
HTTP-only control plane proxy. A hybrid approach is needed.

## Solution

Two-path credential injection:

1. **GitHub API proxy** (`/github-api-proxy/:proxyKey/*`) — reverse proxy in the control plane
   that forwards requests to `api.github.com` with Bearer auth injected. Used by `curl` and
   programmatic HTTP access from inside the sandbox.

2. **`GH_TOKEN` env var** — the short-lived GitHub App installation token passed directly to
   the sandbox as `GH_TOKEN`. The `gh` CLI uses this automatically for github.com operations.
   The token expires in 1 hour and is scoped to the GitHub App's installed repositories.

### Why both paths?

- `gh` CLI hardcodes `https://` for enterprise hosts and cannot be redirected to an HTTP proxy
- `curl`-based access benefits from the proxy pattern (no token in sandbox env needed)
- `GH_TOKEN` is NOT stripped by the entrypoint (unlike `GITHUB_TOKEN` and `GITHUB_APP_TOKEN`)

## Architecture

```
Sandbox Agent
  ├── gh pr create ...        → uses GH_TOKEN env var → github.com (direct HTTPS)
  └── curl $GITHUB_API_PROXY_URL/repos/.../pulls
        → control plane proxy → injects Bearer token → api.github.com
```

### Files Changed

**Control plane (submodule: vendor/open-inspect/):**
- `src/proxy/github-api-proxy.ts` — new reverse proxy handler
- `src/credentials/credential-store.ts` — added `GithubApiCredentials`, proxy key index
- `src/index.ts` — registered proxy route, skip JSON parser for proxy paths
- `src/router.ts` — added `/github-api-proxy/` to `PUBLIC_ROUTES`
- `src/session/session-instance.ts` — pass `GITHUB_API_PROXY_URL` and `GH_TOKEN` to sandbox

**Druppie backend:**
- `druppie/sandbox/__init__.py` — send `githubApi` credentials for GitHub repos
- `druppie/sandbox-config/agents/druppie-builder.md` — updated agent instructions

### Credential Flow

1. Druppie backend obtains GitHub App installation token (1-hour TTL)
2. Token sent to control plane as `credentials.githubApi.token` alongside git credentials
3. Control plane generates random proxy key, stores token in credential store
4. Sandbox receives:
   - `GITHUB_API_PROXY_URL` — for curl/programmatic access via proxy
   - `GH_TOKEN` — for `gh` CLI (direct github.com access)
5. On session destroy, all credentials and proxy keys are wiped

### Security Considerations

- Proxy key is 256-bit random hex — effectively unguessable
- GitHub App tokens expire in 1 hour
- Sandbox is ephemeral (destroyed after task completion)
- `GH_TOKEN` exposure is acceptable given the token's short lifetime and sandbox isolation
- Entrypoint strips `GITHUB_TOKEN` and `GITHUB_APP_TOKEN` but intentionally preserves `GH_TOKEN`
