# Sandbox Architecture

Each coding agent runs in an isolated Docker container. The `module-coding` MCP server mounts the host Docker socket and spawns per-agent containers via the Docker CLI, clones the target repo, executes the task, and extracts changes via `git bundle` -- all without the container ever having git credentials.

There is no `druppie/sandbox/` Python package. All sandbox lifecycle logic lives in `druppie/mcp-servers/module-coding/v1/tools.py`.

---

## Architecture

```
Druppie backend (LangGraph agent loop)
    |
    v
module-coding MCP server (port 9001)
    |  (host Docker socket mount -- spawns containers via Docker CLI)
    v
Per-agent container: druppie-{session[:12]}-{git_scope}
    |  (no git credentials, network-isolated)
    v
git bundle extraction on module-coding host
    |
    v
git push from module-coding host (has credentials)
```

### Key Components

| Component | Location | Role |
|-----------|----------|------|
| **MCP tools (orchestrator)** | `druppie/mcp-servers/module-coding/v1/tools.py` | Spawns containers via Docker CLI, proxies file/bash operations |
| **Sandbox base image** | `druppie/mcp-servers/module-coding/Dockerfile.sandbox` | Python 3.12 + git + Node + ripgrep + jq |
| **Image builder service** | `docker-compose.yml` (`sandbox-image-builder`) | One-shot build producing `druppie-sandbox:latest` |

---

## Container Naming & Lifecycle

Each session + `git_scope` combination gets its own container named `druppie-{session[:12]}-{git_scope}`. Containers:

- Have **no git credentials** -- stripped after clone
- Cannot `git push`, `git remote`, or `git config credential.*` (blocked by bash tool)
- Changes are extracted via `git bundle` and pushed externally from the module-coding host
- Run as a non-root user with minimal Linux capabilities

### Credential Flow

```
module-coding host (has credentials)
    |
    |-- git clone into container (credentials injected, then stripped)
    |
    |-- container executes task (no credentials)
    |
    |-- git bundle extraction on host
    |
    |-- git push from host (credentials used here, never in container)
```

---

## Network Isolation

Sandbox containers run on three dedicated Docker networks, keeping them away from Druppie's internal services (database, Keycloak, Gitea, backend):

| Network | Connectivity | Purpose |
|---------|--------------|---------|
| `sandbox-net` | internal only | Isolated sandbox network (no external connectivity) |
| `sandbox-inet` | internet | Sandbox network with outbound internet egress |
| `sandbox-modules` | internal only | Internal network bridging MCP modules and sandboxes |

---

## MCP Tools

The `module-coding` MCP server exposes these tools to the agent:

| Tool | Description |
|------|-------------|
| `read_file` | Read file contents from the sandbox container |
| `write_file` | Write a file into the sandbox container |
| `edit_file` | Apply targeted edits to a file in the container |
| `bash` | Execute shell commands (dangerous git commands blocked) |
| `grep` | Search file contents |
| `find` | Find files by name/pattern |
| `ls` / `list_dir` | List directory contents |
| `batch_write_files` | Write multiple files in one operation |
| `delete_file` | Delete a file from the container |
| `search_files` | Search across files |
| `get_file_info` | Get file metadata |
| `get_git_status` | Show working tree status |
| `push_changes` | Extract changes via git bundle and push/PR from host |

---

## Runtime Configuration

The container runtime is configurable via `DRUPPIE_SANDBOX_RUNTIME` (default: `sysbox-runc`). The sandbox uses the [sysbox](https://github.com/nestybox/sysbox) runtime for hardened, container-level isolation (nested containers, stronger isolation than the default `runc`).

---

## Sandbox Base Image

The image is built from `druppie/mcp-servers/module-coding/Dockerfile.sandbox` by the `sandbox-image-builder` service in `docker-compose.yml`. It includes:

- Python 3.12
- git
- Node.js
- ripgrep
- jq

The image is configurable via the `DRUPPIE_SANDBOX_IMAGE` environment variable (default: `druppie-sandbox:latest`).

```bash
# Rebuild the sandbox image
docker compose --profile dev up -d --build sandbox-image-builder
```

---

## Shared Dependency Cache

A shared Docker volume (`druppie_sandbox_dep_cache`) caches downloaded npm/pip/uv packages and is mounted into every sandbox container. Sandbox containers are otherwise ephemeral, so this volume lets dependency downloads persist across runs.

```bash
# Purge the cache
docker compose --profile reset-cache run --rm reset-cache

# Scan cached dependencies for vulnerabilities (OSV)
docker compose --profile scan-cache run --rm cache-scanner
```

---

## Configuration Reference

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DRUPPIE_SANDBOX_IMAGE` | `druppie-sandbox:latest` | Sandbox container base image |
| `DRUPPIE_SANDBOX_RUNTIME` | `sysbox-runc` | Container runtime |
| `SANDBOX_MEMORY_LIMIT` | `12g` | Docker memory limit per sandbox |
| `SANDBOX_CPU_LIMIT` | `4` | Docker CPU limit per sandbox |

### Key Files

| File | Purpose |
|------|---------|
| `druppie/mcp-servers/module-coding/v1/tools.py` | MCP tool implementations -- sandbox orchestrator (single source of truth) |
| `druppie/mcp-servers/module-coding/Dockerfile.sandbox` | Sandbox base image definition |
| `docker-compose.yml` | `sandbox-image-builder` service, Docker socket mount on module-coding |

### Troubleshooting

```bash
# Check module-coding logs
docker compose logs -f module-coding

# Verify sandbox image exists
docker images | grep druppie-sandbox

# List active sandbox containers
docker ps | grep druppie-
```
