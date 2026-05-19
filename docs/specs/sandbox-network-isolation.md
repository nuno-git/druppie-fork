# Sandbox Network Isolation — Architecture Spec

## Problem

Sandbox containers currently run on Docker's default `bridge` network. They cannot reach Gitea (`gitea:3000`), so `git clone` fails silently and agents work in an empty repo. Simply adding sandbox containers to the infrastructure network would give them unrestricted access to Gitea, backend, and other services during normal execution — a security risk.

Additionally, different agents need different network access:
- **developer** needs public internet (npm/pip installs) but NOT module access
- **test_builder** needs module access (to test generated apps against real SDK/module MCP servers) but maybe not internet
- **business_analyst** needs neither internet nor module access (just reads/writes markdown)
- Future agents may need custom combinations

## Design Principle

1. **Sandbox containers NEVER have infrastructure network access** (Gitea, backend, DB). All Gitea operations proxied through module-coding.
2. **Network access is per-agent, declarative** — defined in agent YAML, enforced at container creation.
3. **Three network tiers** — each sandbox is connected to exactly the right tier(s).

## Network Tiers

| Tier | Network Name | Access | Use Case |
|------|-------------|--------|----------|
| **Isolated** | `druppie-sandbox-net` | No external access at all | BA, architect (read/write files only) |
| **Internet** | `druppie-sandbox-inet` | Outbound internet only (NAT) | developer (npm/pip installs, curl public APIs) |
| **Modules** | `druppie-sandbox-modules` | Can reach module MCP servers (e.g., `module-ocr:9010`) | test_builder (test apps against real modules via SDK) |

### Network Composition

Each sandbox can be on multiple networks. The agent YAML declares which tiers:

```yaml
# business_analyst.yaml
sandbox:
  networks: []                    # Isolated only (implicit base network)

# developer.yaml
sandbox:
  networks: [internet]            # Internet + isolated base

# test_builder.yaml
sandbox:
  networks: [internet, modules]   # Internet + module access + isolated base
```

All sandboxes get the isolated base network (`druppie-sandbox-net`) automatically. The `networks` list adds tiers ON TOP of the base.

### Docker Network Setup

```yaml
networks:
  app-net:                         # Existing — Gitea, backend, module-coding, modules
    # ...
  sandbox-net:                     # NEW — isolated base, no external access
    name: ${COMPOSE_PROJECT_NAME:-druppie}-sandbox-net
    internal: true                 # NO outbound internet
  sandbox-inet:                    # NEW — internet access for sandboxes
    name: ${COMPOSE_PROJECT_NAME:-druppie}-sandbox-inet
    # NOT internal — allows outbound internet via Docker NAT
  sandbox-modules:                 # NEW — module MCP server access
    name: ${COMPOSE_PROJECT_NAME:-druppie}-sandbox-modules
    internal: true                 # No internet, but can reach module services
```

**Module MCP servers** (module-ocr, etc.) join BOTH `app-net` AND `sandbox-modules` so sandboxes on the modules tier can reach them:

```yaml
module-ocr:
  networks:
    - app-net              # Agent calls from core
    - sandbox-modules      # Sandbox calls via SDK during testing
```

**module-coding** joins `app-net` + `sandbox-net` (so it can docker-exec into sandboxes on the base network):

```yaml
module-coding:
  networks:
    - app-net
    - sandbox-net          # Reach sandboxes for docker exec
```

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                                                                  │
│  ┌─ app-net (infrastructure) ─────────────────────────────────┐ │
│  │                                                             │ │
│  │  Gitea    Backend    module-coding    module-ocr    ...     │ │
│  │  :3000    API        (tools.py)       :9010                │ │
│  │                       │     │                │              │ │
│  └───────────────────────┼─────┼────────────────┼──────────────┘ │
│                          │     │                │                │
│     git clone/push ──────┘     │                │                │
│     (proxied via              │                │                │
│      module-coding)           │                │                │
│                                │                │                │
│  ┌─ sandbox-net (isolated base) ──────────────────────────────┐ │
│  │  │                                                          │ │
│  │  │  module-coding ── docker exec ──► sandbox container     │ │
│  │  │                                      (always here)      │ │
│  └──┼──────────────────────────────────────────────────────────┘ │
│     │                                                            │
│  ┌─ sandbox-inet (optional) ──┐                                 │
│  │  sandbox container ──► internet (npm/pip)                   │ │
│  │  (only if agent has internet tier)                           │ │
│  └──────────────────────────────┘                               │
│     │                                                            │
│  ┌─ sandbox-modules (optional) ──┐                              │
│  │  sandbox container ──► module-ocr:9010                      │ │
│  │  (only if agent has modules tier, via SDK)                   │ │
│  └────────────────────────────────┘                             │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

## Per-Agent Configuration

### Agent YAML Schema Addition

```yaml
# In any agent YAML (e.g., druppie/agents/definitions/developer.yaml)
sandbox:
  networks: [internet]    # Which additional network tiers this agent's sandbox gets
```

Valid values for `networks` list:
- `internet` — outbound internet access (npm/pip installs, curl public APIs)
- `modules` — can reach module MCP servers (for SDK testing)

Empty list or missing `sandbox` section = isolated only (no internet, no modules).

### Agent Access Matrix (current agents)

| Agent | Internet | Modules | Rationale |
|-------|----------|---------|-----------|
| `business_analyst` | ❌ | ❌ | Writes markdown designs. No code execution needed. |
| `architect` | ❌ | ❌ | Writes technical designs. Reads files only. |
| `developer` | ✅ | ❌ | Needs npm/pip install, curl public APIs. No module testing. |
| `test_builder` | ✅ | ✅ | Needs internet for test deps + modules for SDK testing against real MCP servers. |
| `planner` | N/A | N/A | No sandbox (builtin tools only: make_plan, done). |
| `router` | N/A | N/A | No sandbox (builtin tools only: set_intent, done). |

### Future agents can declare custom combos

```yaml
# A future "integration_tester" agent
sandbox:
  networks: [modules]       # Module access but NO internet (air-gapped testing)
```

## Tool Execution Matrix

### What runs INSIDE the sandbox (via `docker exec`)

| Tool | Operation | Needs Internet? | Needs Modules? |
|------|-----------|----------------|----------------|
| `bash` | Any command | Per-agent config | Per-agent config |
| `write_file` | Write file to filesystem | No | No |
| `read_file` | Read file from filesystem | No | No |
| `search_files` | grep/ripgrep in workspace | No | No |
| `get_file_info` | stat/lstat on files | No | No |
| `make_design` | Write markdown file | No | No |
| `push_pr` (part 1) | `git add -A && git commit && git bundle create` | No | No |
| `run_git` | Local git ops (add, commit, status, diff) | No | No |
| `build` / `run` | npm install, pip install, build commands | ✅ Internet | No |
| SDK calls (via bash) | `druppie_sdk.ocr.extract(...)` in test scripts | No | ✅ Modules |

### What runs in module-coding container (on app-net)

| Tool | Operation | Needs Gitea? |
|------|-----------|-------------|
| `_ensure_sandbox` | `git clone` repo to local temp dir | Yes |
| `_ensure_sandbox` | Stream cloned repo into sandbox via tar pipe | No |
| `push_pr` (part 2) | Extract git bundle from sandbox | No |
| `push_pr` (part 3) | `git push` to Gitea | Yes |
| `push_pr` (part 4) | `curl` to create PR on Gitea | Yes |

### Commit Flow (end-to-end)

```
1. Agent calls write_file("hello.ts", content)
   └─ module-coding: docker exec sandbox sh -c 'cat > /workspace/hello.ts'
      [INSIDE sandbox — no network]

2. Agent calls bash("npm install && npm test")
   └─ module-coding: docker exec sandbox sh -c 'cd /workspace && npm install && npm test'
      [INSIDE sandbox — needs INTERNET tier for npm install]

3. Agent calls push_pr(title, description)
   └─ Step A: docker exec sandbox git add -A && git commit
      [INSIDE sandbox — no network]
   └─ Step B: docker exec sandbox git bundle create /tmp/bundle.git --all
      [INSIDE sandbox — no network]
   └─ Step C: docker exec sandbox cat /tmp/bundle.git
      [READ from sandbox → into module-coding filesystem]
   └─ Step D: git clone /tmp/bundle.git /tmp/repo-xxx
      [IN module-coding — no network]
   └─ Step E: git push origin HEAD:refs/heads/feature/xxx
      [IN module-coding — NEEDS Gitea on app-net]
   └─ Step F: curl -X POST gitea:3000/api/v1/repos/.../pulls
      [IN module-coding — NEEDS Gitea on app-net]

4. test_builder calls bash("python -m pytest tests/test_ocr.py")
   └─ module-coding: docker exec sandbox sh -c 'cd /workspace && python -m pytest ...'
      [INSIDE sandbox — test code uses druppie_sdk which calls module-ocr:9010]
      [NEEDS MODULES tier for SDK → module connectivity]
```

## Module Access via SDK

When an agent has the `modules` tier, its sandbox can reach module MCP servers. This enables the test_builder to write test code that uses the Druppie SDK against real modules:

```python
# Inside test_builder's sandbox, test code does:
from druppie_sdk import DruppieClient

druppie = DruppieClient()
result = await druppie.modules.call("ocr", "extract_text", {"source": "invoice.png"})
assert result["text"] != ""
```

The SDK resolves module URLs from environment variables:

```yaml
# In docker-compose, when creating test_builder's sandbox:
# module-coding injects these env vars based on the agent's sandbox.networks config
DRUPPIE_MODULE_TOKEN: <short-lived Keycloak OBO token>
DRUPPIE_MODULE_OCR_URL: http://module-ocr:9010
DRUPPIE_APP_ID: <test-app-id>
DRUPPIE_PROJECT_ID: <project-id>
```

### How it works end-to-end

1. Agent YAML declares `sandbox.networks: [modules]`
2. module-coding reads agent config, creates sandbox on `sandbox-modules` network
3. module-coding injects `DRUPPIE_MODULE_*` env vars into sandbox container
4. Backend (orchestrator) requests short-lived OBO token from Keycloak, passes to module-coding
5. module-coding injects token as `DRUPPIE_MODULE_TOKEN` env var
6. SDK inside sandbox uses token + URLs to call modules directly
7. Modules validate token against Keycloak (they're on app-net, CAN reach Keycloak)

### Token flow for module access

```
┌──────────┐    request OBO token     ┌──────────┐
│ Backend  │ ──────────────────────► │ Keycloak │
│ (core)   │ ◄────────────────────── │          │
└──────────┘    short-lived JWT       └──────────┘
     │
     │ pass token via tool context injection
     ▼
┌──────────────┐    inject env vars    ┌──────────────┐
│module-coding │ ────────────────────► │   Sandbox    │
│ (tools.py)   │    DRUPPIE_MODULE_*   │  container   │
└──────────────┘                       └──────────────┘
                                            │
                                     SDK calls module
                                            │
                                            ▼
                                       ┌──────────┐
                                       │module-ocr│
                                       │  :9010   │
                                       └──────────┘
```

## Detailed Changes

### 1. docker-compose.yml — Three new networks + service updates

```yaml
networks:
  app-net:
    # existing — unchanged
  sandbox-net:
    name: ${COMPOSE_PROJECT_NAME:-druppie}-sandbox-net
    internal: true               # No external access
  sandbox-inet:
    name: ${COMPOSE_PROJECT_NAME:-druppie}-sandbox-inet
    # NOT internal — allows outbound internet
  sandbox-modules:
    name: ${COMPOSE_PROJECT_NAME:-druppie}-sandbox-modules
    internal: true               # No internet, but module services join this
```

module-coding gets sandbox-net:
```yaml
module-coding:
  networks:
    - app-net
    - sandbox-net
  environment:
    DRUPPIE_SANDBOX_NETWORK: ${COMPOSE_PROJECT_NAME:-druppie}-sandbox-net
```

Module servers get sandbox-modules:
```yaml
module-ocr:
  networks:
    - app-net              # Agent calls from core
    - sandbox-modules      # Sandbox calls via SDK
```

### 2. Agent YAML — Add sandbox.networks field

Each agent YAML gets an optional `sandbox` section:

```yaml
# druppie/agents/definitions/developer.yaml
sandbox:
  networks: [internet]
```

```yaml
# druppie/agents/definitions/test_builder.yaml
sandbox:
  networks: [internet, modules]
```

```yaml
# druppie/agents/definitions/business_analyst.yaml
sandbox:
  networks: []    # or omit entirely — isolated only
```

### 3. Agent Config Loader — Parse sandbox.networks

In the agent definition loader (wherever YAML is parsed), add `sandbox.networks` to the agent model:

```python
@dataclass
class SandboxConfig:
    networks: list[str] = field(default_factory=list)  # "internet", "modules"
```

Pass this to module-coding via the tool context injection (similar to how `git_scope` is passed today).

### 4. tools.py — Sandbox container creation with per-agent networks

```python
SANDBOX_NETWORK = os.getenv("DRUPPIE_SANDBOX_NETWORK", "bridge")
SANDBOX_INET_NETWORK = os.getenv("DRUPPIE_SANDBOX_INET_NETWORK", "")
SANDBOX_MODULES_NETWORK = os.getenv("DRUPPIE_SANDBOX_MODULES_NETWORK", "")

async def _create_sandbox_container(
    session_id: str,
    git_scope: str,
    repo_name: str | None = None,
    repo_owner: str | None = None,
    agent_networks: list[str] | None = None,   # ← NEW
) -> dict:
    # ... existing container creation ...

    cmd = [
        "docker", "run", "-d",
        "--name", container_name,
        "--network", SANDBOX_NETWORK,      # Base isolated network
        # ... security flags, memory, CPU ...
    ]

    rc, stdout, stderr = await _docker_run(cmd, timeout=60)

    # Connect additional networks based on agent config
    if agent_networks:
        for tier in agent_networks:
            if tier == "internet" and SANDBOX_INET_NETWORK:
                await _docker_run(
                    ["docker", "network", "connect", SANDBOX_INET_NETWORK, container_name],
                    timeout=10,
                )
            elif tier == "modules" and SANDBOX_MODULES_NETWORK:
                await _docker_run(
                    ["docker", "network", "connect", SANDBOX_MODULES_NETWORK, container_name],
                    timeout=10,
                )
                # Inject module env vars for SDK
                # (URLs, token — passed via tool context injection)
```

### 5. tools.py — Proxy clone (same as v1 spec)

Replace `docker exec sandbox git clone` with module-coding-local clone + tar pipe:

```python
# Step 1: Clone in module-coding (on app-net, CAN reach Gitea)
clone_dir = f"/tmp/clone-{short_session}"
await _run_subprocess(["rm", "-rf", clone_dir], timeout=10)
rc, _, err = await _run_subprocess(
    ["git", "clone", "--depth=50", clone_url, clone_dir],
    timeout=120,
)

# Step 2: Stream into sandbox via tar pipe
tar_proc = await asyncio.create_subprocess_exec(
    "tar", "cf", "-", "-C", clone_dir, ".",
    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
)
docker_proc = await asyncio.create_subprocess_exec(
    "docker", "exec", "-i", container_id,
    "tar", "xf", "-", "-C", "/workspace",
    stdin=tar_proc.stdout,
    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
)
tar_proc.stdout.close()
await docker_proc.wait()
await tar_proc.wait()

# Step 3: Strip credentials + create session branch
await _exec_in_container(container_id, ["git", "remote", "set-url", "origin", public_url])
await _exec_in_container(container_id, ["git", "checkout", "-b", branch])

# Cleanup
await _run_subprocess(["rm", "-rf", clone_dir], timeout=10)
```

### 6. Verify push_pr runs from module-coding (no changes expected)

From code analysis, push_pr already works correctly:
- `git bundle create` → inside sandbox (no network)
- Bundle extraction → module-coding filesystem
- `git push` → from module-coding (on app-net) ✅
- `curl` PR creation → from module-coding (on app-net) ✅

### 7. Fix test YAMLs

Replace `coding:run_git` with `push_pr` for BA/architect in test setup YAMLs.

### 8. Fix session API `_get_project_summary`

Add `repo_name=project.repo_name` to the `ProjectSummary` constructor in `session_repository.py`.

### 9. New helper: `_run_subprocess`

```python
async def _run_subprocess(
    cmd: list[str], timeout: float = 120
) -> tuple[int, str, str]:
    """Run a subprocess in module-coding's own filesystem."""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return proc.returncode or 0, stdout.decode(), stderr.decode()
    except asyncio.TimeoutError:
        proc.kill()
        return -1, "", "timeout"
```

## Enforcement Model

There are **no runtime checks** — enforcement is purely network-level. If a sandbox container can't route to a service, it can't reach it. Period. No amount of `curl`, `git push`, or SDK calls from inside the sandbox will work unless the Docker network allows it.

### What each tier can route to

| Tier | Can reach | Cannot reach | How enforced |
|------|----------|-------------|-------------|
| **Isolated** (base, all sandboxes) | Nothing external | Gitea, backend, internet, modules | Docker `internal: true` network |
| **+ Internet** | Outbound internet (npm, pip, curl public APIs) | Gitea, backend, modules | Separate non-internal Docker network with NAT only |
| **+ Modules** | Module MCP servers (e.g., `module-ocr:9010`) | Gitea, backend, internet | Docker `internal: true` network that only module services are connected to |

### Why certain things work despite isolation

| Operation | How it bypasses sandbox isolation |
|-----------|----------------------------------|
| `git clone` (project code) | Doesn't run inside sandbox. module-coding clones to its own filesystem → tar-pipes files into sandbox. |
| `push_pr` (git push + PR) | Doesn't run inside sandbox. Sandbox creates a git bundle → module-coding extracts it and pushes to Gitea from app-net. |
| `run_git` (local git ops) | Runs inside sandbox but only uses local `.git` directory. No network needed for `add`, `commit`, `status`, `diff`. |

### What CANNOT be bypassed

| Attempted from inside sandbox | Result | Why |
|-------------------------------|--------|-----|
| `curl http://gitea:3000` | Connection refused / DNS failure | Not on app-net |
| `git push origin main` | Connection refused / DNS failure | Not on app-net |
| `curl http://module-ocr:9010` (without modules tier) | Connection refused / DNS failure | Not on sandbox-modules network |
| `pip install requests` (without internet tier) | Connection timeout | Not on sandbox-inet network |
| `curl http://backend:8000` | Connection refused / DNS failure | Not on app-net |

## Implementation Order

1. Create 3 networks in docker-compose.yml
2. Add `sandbox.networks` to agent YAMLs + config loader
3. Update tools.py container creation with per-agent network connect
4. Add `_run_subprocess` helper
5. Proxy clone through module-coding
6. Verify push_pr works from module-coding (not sandbox)
7. Fix test YAMLs
8. Fix session API `_get_project_summary`
9. Rebuild + E2E test

## Out of Scope (future)

- Kata Containers for production isolation
- Sysbox for hardened dev (nesting support)
- Warm pool of pre-created sandbox containers
- Stale container reaper cron job
- Resource limit enforcement via config
- Fine-grained module allowlist per agent (currently: all modules or none)
