# Sandbox Infrastructure

Druppie delegates coding tasks to isolated Docker sandboxes. Each sandbox is a fresh container with git, a coding agent ([OpenCode](https://github.com/opencode-ai/opencode)), and proxied LLM access. The sandbox clones the project from Gitea, executes the task, commits and pushes changes back -- all without touching the shared workspace.

---

## Architecture

The sandbox infrastructure is based on [Open-Inspect](https://github.com/nuno120/background-agents) (our fork, branch `druppie`), integrated as a git submodule at `background-agents/`. Sandbox containers run [OpenCode](https://github.com/opencode-ai/opencode) (`latest`).

Three Docker services power the infrastructure:

| Service | Port | Role |
|---------|------|------|
| **sandbox-control-plane** | 8787 | HTTP API for session/event management, SQLite storage, coordinates lifecycle |
| **sandbox-manager** | 8000 | Creates/manages sandbox Docker containers, enforces resource limits |
| **sandbox-image-builder** | — | One-shot build producing `open-inspect-sandbox:latest` from our fork; Docker caches it |

Communication flow:

```
Druppie backend (built-in tool)
    │
    ▼
sandbox-control-plane (:8787)     ◄─── LLM proxy (rewrites provider requests)
    │
    ▼
sandbox-manager (:8000)
    │
    ▼
Docker container (sandbox)        ◄─── OpenCode + git + coding agent
    │
    ▼  (webhook on completion)
Druppie backend
```

---

## Webhook + Pause/Resume

`execute_coding_task` is a **built-in tool** (not an MCP tool) that runs inside the backend process. Instead of holding an HTTP connection open for the duration of the sandbox, it uses a fire-and-forget pattern with a webhook callback.

### Flow

1. **Create session** — `POST /sessions` on the control plane with repo URL, agent config, and LLM model
2. **Send prompt with callback** — `POST /sessions/{id}/message` with the task description plus `callbackUrl` and `callbackSecret`
3. **Register ownership** — `POST /api/sandbox-sessions/internal/register` to map the sandbox session to the requesting user
4. **Return immediately** — The tool returns `WAITING_SANDBOX` status. The agent loop pauses, freeing the thread.
5. **Webhook callback** — When the sandbox completes, the control plane POSTs to `POST /api/sandbox-sessions/{id}/complete` with an HMAC-signed payload. The webhook handler fetches final events, extracts changed files and agent output, completes the tool call, and resumes the agent via `Orchestrator.resume_after_sandbox()`.

### Status Model

| Level | Status | Meaning |
|-------|--------|---------|
| ToolCallStatus | `WAITING_SANDBOX` | Tool call dispatched, waiting for webhook |
| AgentRunStatus | `PAUSED_SANDBOX` | Agent paused while sandbox executes |
| SessionStatus | `paused_sandbox` | Session paused for sandbox, visible in UI |

### Webhook Endpoint

`POST /api/sandbox-sessions/{sandbox_session_id}/complete` (in `druppie/api/routes/sandbox.py`):

1. Verifies HMAC-SHA256 signature via `X-Signature` header
2. Finds the `WAITING_SANDBOX` tool call via `tool_call_id` FK on `sandbox_sessions`
3. Fetches final events from control plane
4. Extracts changed files and agent output
5. Completes the tool call with result payload
6. Resumes the agent asynchronously

---

## Sandbox Agents

Two preconfigured agents run inside sandboxes (defined in `druppie/sandbox-config/agents/`):

| Agent | Purpose | Key Behavior |
|-------|---------|--------------|
| **druppie-builder** | Implements features, writes code | Must output a structured `---SUMMARY---` block with files changed, commands run, and key decisions |
| **druppie-tester** | Writes tests, validates code | Auto-detects test framework, reports results in structured format |

Both agents enforce a mandatory git workflow: `git add <files>` → `git commit` → `git push origin HEAD`. No unpushed commits are allowed.

Agents that can delegate to sandboxes declare `extra_builtin_tools: [execute_coding_task]` in their YAML definition (currently: `builder`, `tester`).

---

## OpenCode Integration

### Config Injection

Sandbox agents are configured via files in `druppie/sandbox-config/`:

- **`opencode-config.json`** — Sets `default_agent` to `druppie-builder` and grants broad tool permissions
- **`agents/druppie-builder.md`** — Coding agent system prompt
- **`agents/druppie-tester.md`** — Testing agent system prompt

The sandbox provider uses `@ai-sdk/openai-compatible` to route all LLM requests through the proxy. Configuration is injected into sandbox containers via the `OPENCODE_CONFIG_CONTENT` environment variable and also written as `opencode.json` to both the global config directory and the project directory. `OPENCODE_DISABLE_PROJECT_CONFIG=true` prevents user `.opencode/` overrides inside the sandbox.

### Agent Parameter Threading

The `agent` parameter threads through 5 layers to select which sandbox agent runs:

```
builtin_tools.py → control plane router → session instance → bridge → OpenCode API
```

### Key OpenCode Details

- OpenCode uses `latest` (no longer pinned to a specific version)
- OpenCode config uses `"agent"` (singular), not `"agents"` (plural)
- OpenCode SDK sends paths WITHOUT `v1/` prefix (e.g., `chat/completions` not `v1/chat/completions`) when using a custom `baseURL`
- The LLM proxy must handle both path patterns
- `opencode.json` is written to both the global config directory and the project directory

---

## Provider Resilience

Sandbox coding tasks survive provider outages with three independent layers of defense:

### Layer A: Proxy Failover (sub-second)

The LLM proxy intercepts all sandbox LLM requests. When a provider returns a non-2xx response, the proxy transparently retries with the next provider in the model chain, rewriting the model name in the request body.

```
Provider A fails → non-2xx
  → Proxy rewrites model to Provider B → 200 OK
  → Sandbox agent never notices the switch
```

Failover triggers on any non-2xx response (auth errors, rate limits, server errors, etc.).

### Layer B: Druppie Retry (30-60 seconds)

If the sandbox itself fails (all providers exhausted, crash, etc.), the webhook arrives with `success=false`. The Druppie webhook handler retries with the next model in the chain by creating a new sandbox session.

### Layer C: Detection (10 seconds - 5 minutes)

Three detection signals work in parallel:

| Signal | Source | Trigger |
|--------|--------|---------|
| **C1** | LLM proxy | Error counter hits threshold → `provider_unhealthy` event |
| **C2** | Bridge | Detects session errors → emits `provider_unhealthy` event |
| **C3** | Session instance | Activity watchdog — no successful LLM call for N minutes |

### Model Chains (Profile-Based Routing)

Model chains are configured in `druppie/sandbox-config/sandbox_models.yaml`. Each agent/subagent name acts as a "profile" (e.g., `sandbox/druppie-builder`). OpenCode sees profile-based model names via a single `sandbox` provider using `@ai-sdk/openai-compatible`. The LLM proxy resolves profile names to real provider chains at request time.

Each profile has an ordered list of `{provider, model}` pairs. Model names in the YAML use the raw API model name without a provider prefix. The chain is threaded from `builtin_tools.py` → credential store for proxy failover.

---

## Kata Containers (Optional VM Isolation)

For production or untrusted code, sandboxes can run inside lightweight VMs instead of Docker containers using [Kata Containers](https://katacontainers.io/).

| Runtime | Isolation | Platform | Use Case |
|---------|-----------|----------|----------|
| **docker** (default) | Container-level (cgroups, namespaces) | Linux, macOS, Windows | Development, general use |
| **kata** | VM-level (lightweight QEMU VMs) | Linux with KVM only | Production, untrusted code |

### Prerequisites

- Linux host with KVM support (`/dev/kvm` must exist)
- Nested virtualization enabled if running inside a VM
- Not compatible with Docker Desktop — requires native Linux containerd

### Setup

```bash
# 1. Install Kata Containers
sudo background-agents/packages/local-sandbox-manager/scripts/setup-kata.sh

# 2. Build the sandbox image for containerd
background-agents/packages/local-sandbox-manager/scripts/build-sandbox-image.sh --kata

# 3. Configure .env
echo "SANDBOX_RUNTIME=kata" >> .env

# 4. Restart services
docker compose --profile dev down
docker compose --profile dev --profile init up -d
```

### How It Works

When `SANDBOX_RUNTIME=kata`, the sandbox-manager uses `ctr` (containerd CLI) instead of Docker CLI and creates containers with `--runtime io.containerd.kata.v2`. Each sandbox gets its own lightweight QEMU VM with a dedicated guest kernel.

```
sandbox-manager ──── SANDBOX_RUNTIME=docker ──> Docker CLI ──> runc container
                └─── SANDBOX_RUNTIME=kata   ──> ctr CLI    ──> Kata VM (QEMU)
```

The runtime swap is entirely within the sandbox-manager — the rest of the stack (control plane, frontend) is unchanged.

### Switching Back to Docker

```bash
# In .env: SANDBOX_RUNTIME=docker
docker compose --profile dev down && docker compose --profile dev up -d
```

### Security Comparison

| Property | Docker (runc) | Kata (QEMU) |
|----------|--------------|-------------|
| Kernel isolation | Shared host kernel | Separate guest kernel |
| Syscall filtering | seccomp profile | VM boundary + seccomp |
| Memory isolation | cgroups | VM memory allocation |
| Container escape impact | Host access | Guest VM only |
| Performance overhead | Minimal | ~100-200ms startup, ~5-10% runtime |

---

## Security

### Session Ownership

The `sandbox_sessions` table maps control plane session IDs to Druppie users. Sandbox events are only visible to the user who triggered the session (admins can view any session). Registration uses an internal API key, not user tokens.

### Credential Proxying

Git and LLM credentials are never exposed to the sandbox. The control plane generates per-session proxy keys and intercepts git/LLM requests to inject real credentials.

**Per-sandbox Gitea accounts:** Each sandbox gets its own restricted Gitea user with collaborator access to only the target repository. The user is created before the sandbox starts and deleted after it completes. Even if a sandbox extracts its proxy key, the underlying Gitea token can only access the authorized repo.

**Proxy-side validation:** The git proxy validates that the requested `owner/repo` matches the session's authorized scope. Requests for other repos return 403.

**Credential lifecycle:** Proxy keys (both git and LLM) are invalidated when the sandbox completes (`execution_complete`), when the container is destroyed (timeout, failure, manual kill), and when the session is deleted. Orphaned Gitea service accounts are cleaned up on backend startup.

**Implementation details:**
- Gitea users are named `sandbox-{session_id[:12]}` to stay within Gitea's username length limits
- Each user gets `write` collaborator access on the target repo and a scoped access token (`write:repository`)
- The `git_user_id` is stored on the `sandbox_sessions` DB table for cleanup
- The credential store's `GitCredentials` interface includes an `authorizedRepo` field (`"owner/repo"`) enforced by the git proxy
- Credentials are destroyed in three places: `execution_complete` event handler, `destroySandboxContainer()`, and router `DELETE /sessions/:id`
- On backend startup, `cleanup_orphaned_sandbox_users()` deletes all restricted `sandbox-*` Gitea users (startup-only — assumes no active sandboxes survive a restart)
- Key files: `druppie/sandbox/gitea_credentials.py` (create/delete), `druppie/sandbox/gitea_cleanup.py` (GC), `credential-store.ts` (authorizedRepo), `git-proxy.ts` (scope validation)

### Webhook Authentication

All webhooks are signed with HMAC-SHA256. The `callbackSecret` is set when creating the sandbox session and verified on every webhook delivery.

---

## Configuration Reference

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SANDBOX_CONTROL_PLANE_URL` | `http://sandbox-control-plane:8787` | Control plane endpoint |
| `SANDBOX_API_SECRET` | `sandbox-dev-secret` | HMAC-SHA256 secret for auth tokens |
| `SANDBOX_MEMORY_LIMIT` | `4g` | Docker memory limit per sandbox |
| `SANDBOX_CPU_LIMIT` | `2` | Docker CPU limit per sandbox |
| `SANDBOX_RUNTIME` | `docker` | Container runtime (`docker` or `kata`) |
| `LLM_FORCE_PROVIDER` | — | Override: forces all sandbox profiles to use this provider (e.g., `deepinfra`). Must be set together with `LLM_FORCE_MODEL`. |
| `LLM_FORCE_MODEL` | — | Override: forces all sandbox profiles to use this model (e.g., `Qwen/Qwen3-32B`). Must be set together with `LLM_FORCE_PROVIDER`. |

### Config Files

| File | Purpose |
|------|---------|
| `druppie/sandbox-config/opencode-config.json` | OpenCode configuration injected into sandboxes |
| `druppie/sandbox-config/agents/druppie-builder.md` | Builder agent system prompt |
| `druppie/sandbox-config/agents/druppie-tester.md` | Tester agent system prompt |
| `druppie/sandbox-config/sandbox_models.yaml` | Model chains for provider failover (profile-based routing) |

### Troubleshooting

```bash
# Check sandbox services
docker compose logs -f sandbox-control-plane sandbox-manager

# Verify sandbox image exists
docker images | grep open-inspect-sandbox

# Check active sandboxes
curl -s http://localhost:8787/sessions | jq .
```

For Kata-specific troubleshooting, see the [Kata Containers section](#kata-containers-optional-vm-isolation).
