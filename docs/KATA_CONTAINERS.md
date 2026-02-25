# Kata Containers for Sandbox Isolation

Druppie's sandbox infrastructure (Open-Inspect) supports two container runtimes for the coding sandboxes:

| Runtime | Isolation | Platform | Use case |
|---------|-----------|----------|----------|
| **docker** (default) | Container-level (cgroups, namespaces) | Linux, macOS, Windows | Development, general use |
| **kata** | VM-level (lightweight QEMU VMs) | Linux with KVM only | Production, untrusted code |

Kata Containers run each sandbox inside a lightweight virtual machine with its own guest kernel. This provides hardware-enforced isolation — a sandbox escape would need to break out of a VM, not just a container.

## Prerequisites

- **Linux host** with KVM support (`/dev/kvm` must exist)
- **Nested virtualization** enabled if running inside a VM (e.g., cloud instances)
- **containerd** installed and running
- **Not compatible with Docker Desktop** — requires native Linux containerd

Check KVM support:

```bash
ls -la /dev/kvm
# If missing, enable nested virtualization on your hypervisor
```

## Setup

### 1. Install Kata Containers

Run the bundled setup script (as root or with sudo):

```bash
sudo vendor/open-inspect/packages/local-sandbox-manager/scripts/setup-kata.sh
```

This script:
- Verifies `/dev/kvm` exists
- Installs Kata Containers from the official repository
- Configures containerd with the `io.containerd.kata.v2` runtime handler
- Restarts containerd
- Runs a verification test (Alpine container with Kata runtime)

### 2. Build the sandbox image for containerd

Docker Compose builds the sandbox image as a Docker image. For Kata, it also needs to be imported into containerd:

```bash
vendor/open-inspect/packages/local-sandbox-manager/scripts/build-sandbox-image.sh --kata
```

This builds the Docker image and then runs `docker save | ctr images import` to make it available to containerd.

### 3. Configure `.env`

```bash
# In your .env file:
SANDBOX_RUNTIME=kata

# Optional — these are the defaults:
# KATA_RUNTIME=io.containerd.kata.v2
# CONTAINERD_NAMESPACE=default
```

### 4. Restart services

```bash
docker compose --profile dev down
docker compose --profile dev --profile init up -d
```

The `sandbox-manager` service reads `SANDBOX_RUNTIME` at startup and loads either `DockerContainerManager` or `KataContainerManager` accordingly. No Docker Compose profile changes needed.

## How it works

When `SANDBOX_RUNTIME=kata`, the sandbox-manager:

1. Uses `ctr` (containerd CLI) instead of `docker` CLI
2. Creates containers with `--runtime io.containerd.kata.v2`
3. Each sandbox gets its own lightweight QEMU VM with a dedicated guest kernel
4. Supports snapshot/restore (pause VM, commit layer, export as OCI tar)

The rest of the stack (control plane, MCP coding server, frontend) is unchanged — the runtime swap is entirely within the sandbox-manager.

```
MCP coding server
    |
    v
sandbox-control-plane (unchanged)
    |
    v
sandbox-manager  ──── SANDBOX_RUNTIME=docker ──> Docker CLI ──> runc container
                 └─── SANDBOX_RUNTIME=kata   ──> ctr CLI    ──> Kata VM (QEMU)
```

## Switching back to Docker

```bash
# In .env:
SANDBOX_RUNTIME=docker

# Restart:
docker compose --profile dev down
docker compose --profile dev up -d
```

## Verifying Kata is working

After setup, verify the sandbox-manager is using Kata:

```bash
# Check sandbox-manager logs for runtime selection
docker compose logs sandbox-manager | grep -i runtime

# The health endpoint reports the active runtime
curl -s http://localhost:8000/api/health | jq .runtime
```

You can also verify at the containerd level:

```bash
# List running Kata containers
sudo ctr -n default containers ls

# The guest kernel should differ from the host kernel
sudo ctr -n default run --rm --runtime io.containerd.kata.v2 \
  docker.io/library/alpine:latest test-kata uname -r
```

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `/dev/kvm` not found | Enable nested virtualization on the hypervisor. For cloud VMs, use instance types that support it (e.g., AWS `.metal`, GCP with nested virt enabled). |
| `ctr: command not found` | Install containerd: `sudo apt-get install containerd` |
| Kata test container fails | Check containerd logs: `journalctl -u containerd -n 50` |
| Sandbox image not found in containerd | Re-run `build-sandbox-image.sh --kata` to import the image |
| sandbox-manager can't reach containerd | The sandbox-manager container needs access to the host containerd socket. When running via Docker Compose, the manager uses `ctr` inside its container — for Kata mode, consider running the sandbox-manager directly on the host instead of in Docker. |

## Security comparison

| Property | Docker (runc) | Kata (QEMU) |
|----------|--------------|-------------|
| Kernel isolation | Shared host kernel | Separate guest kernel |
| Syscall filtering | seccomp profile | VM boundary + seccomp |
| Memory isolation | cgroups | VM memory allocation |
| Privilege escalation | `no-new-privileges`, `cap-drop=ALL` | VM boundary |
| Container escape impact | Host access | Guest VM only |
| Performance overhead | Minimal | ~100-200ms startup, ~5-10% runtime |
