# GitHub API Proxy for Sandbox Agents

**Date:** 2026-03-09
**Status:** Implemented

## Problem

Sandbox agents (druppie-builder) need GitHub API access to create PRs, read issues, and
interact with the repository. The sandbox security model prevents direct credential exposure —
all auth is injected server-side via proxies.

## Solution

**GitHub API reverse proxy** (`/github-api-proxy/:proxyKey/*`) in the control plane. Same
pattern as the git proxy and LLM proxy: the sandbox only knows a random proxy key, the control
plane injects the real Bearer token server-side before forwarding to `api.github.com`.

No real tokens enter the sandbox. The agent uses:
- `curl $GITHUB_API_PROXY_URL/...` for direct API calls
- `create-pull-request` built-in tool for PR creation (calls control plane `/sessions/:id/pr`)
- `gh` CLI is replaced with a wrapper that shows curl usage (it hardcodes HTTPS to api.github.com)

## Architecture

```
Sandbox Agent
  ├── create-pull-request tool  → control plane /sessions/:id/pr → GitHub API
  └── curl $GITHUB_API_PROXY_URL/repos/.../pulls
        → control plane proxy → injects Bearer token → api.github.com
```

### Files Changed

**Control plane (submodule: vendor/open-inspect/):**
- `src/proxy/github-api-proxy.ts` — new reverse proxy handler
- `src/credentials/credential-store.ts` — added `GithubApiCredentials`, proxy key index
- `src/index.ts` — registered proxy route, skip JSON parser for proxy paths
- `src/router.ts` — added `/github-api-proxy/` to `PUBLIC_ROUTES`
- `src/session/session-instance.ts` — pass `GITHUB_API_PROXY_URL` to sandbox

**Sandbox image (submodule: vendor/open-inspect/):**
- `src/sandbox/entrypoint.py` — `gh` CLI wrapper with curl usage instructions

**Druppie backend:**
- `druppie/sandbox/__init__.py` — send `githubApi` credentials for GitHub repos
- `druppie/sandbox-config/agents/druppie-builder.md` — updated agent instructions with curl examples

### Credential Flow

1. Druppie backend obtains GitHub App installation token (1-hour TTL)
2. Token sent to control plane as `credentials.githubApi.token` alongside git credentials
3. Control plane generates random proxy key, stores token in credential store
4. Sandbox receives only `GITHUB_API_PROXY_URL` (opaque proxy key in URL, no real token)
5. On session destroy, all credentials and proxy keys are wiped

### Security

- No real tokens in sandbox — only opaque proxy keys
- Proxy key is 256-bit random hex — effectively unguessable
- GitHub App tokens expire in 1 hour (stored server-side in credential store)
- Sandbox is ephemeral (destroyed after task completion)
- Same security model as git proxy and LLM proxy
