# AI Agent Sandboxing and Isolation

## The Problem

Druppie's AI agents (builder, reviewer, planner, etc.) can autonomously:
- Install Python and Node.js packages
- Generate and execute code
- Access network resources
- Read/write files in the workspace

This means a compromised LLM response or a malicious package installed by an agent can:
- Steal credentials from the sandbox environment
- Install backdoors that persist across sessions
- Exfiltrate data via network access
- Inject malicious code into the workspace that gets committed

Jeremy's requirement: "Alle agents moeten werken in een geïsoleerde container, waarbij er een verplichte scan moet plaatsvinden voordat de code deze sandbox verlaat."

## Current Sandboxing in Druppie

Druppie already has sandbox infrastructure (`background-agents/`):
- **Sandbox manager**: Creates Docker containers per session
- **Network isolation**: Sandboxes on `druppie-sandbox-network` (separate from main network)
- **Control plane**: Bridges sandbox and main networks (gatekeeper)
- **OSV Scanner**: Can scan cached dependencies for known vulnerabilities
- **Non-root user**: Sandbox runs as `sandbox:sandbox` (1000:1000)
- **Runtime option**: Supports `docker` or `kata` runtime (configured via `SANDBOX_RUNTIME`)

### Current Gaps
1. Docker containers share the host kernel - container escape = full compromise
2. No mandatory scan before code leaves the sandbox
3. No Unicode stripping on agent output
4. Agents can install packages freely without pre-approval
5. Network access from sandbox is not fully restricted

---

## Approach 1: Standard Docker Containers (Current)

### How It Works
Each agent session gets its own Docker container with:
- Isolated filesystem
- Separate network namespace
- Resource limits (CPU, memory)
- Non-root user

### Pros
- **Already implemented**: Current infrastructure supports this
- **Low overhead**: ~50ms container start, minimal memory overhead
- **Familiar tooling**: Docker is well-understood by the team
- **Good enough for trusted code**: Adequate isolation for known-good workloads

### Cons
- **Shared kernel**: ALL containers share the host Linux kernel
- **Kernel exploits**: A single kernel vulnerability = escape from ANY container
- **Insufficient for untrusted code**: AI agents installing arbitrary packages = untrusted code
- **Container escape techniques**: Actively researched, new escapes found regularly
- **Docker socket exposure**: sandbox-manager has Docker socket mounted (high-risk)

### Security Rating: **Insufficient** for AI agent workloads

---

## Approach 2: gVisor (User-Space Kernel)

### How It Works
gVisor interposes a user-space kernel (called "Sentry") between the container and the host kernel. All system calls from the container are intercepted and re-implemented in Go, never reaching the real kernel.

```yaml
# docker-compose.yml
services:
  sandbox:
    runtime: runsc  # gVisor runtime
```

### Pros
- **Kernel isolation**: Container syscalls never reach the host kernel
- **Container escape prevention**: Attacker would need to compromise the Go-based Sentry (much harder than kernel exploits)
- **Docker-compatible**: Drop-in replacement runtime, works with existing Docker infrastructure
- **Kubernetes-compatible**: Supported as RuntimeClass in K8s
- **Moderate overhead**: 10-30% on I/O-heavy workloads, minimal on compute
- **No hardware requirements**: Works on any Linux host (unlike Firecracker which needs KVM)
- **Active development**: Maintained by Google

### Cons
- **I/O overhead**: File-heavy operations (npm install, pip install) will be noticeably slower
- **Syscall coverage**: Not all Linux syscalls are implemented - some packages may fail
- **Debugging complexity**: Errors inside gVisor can be harder to diagnose
- **Not full VM isolation**: Still shares some host resources (though much less than Docker)

### Security Rating: **Good** - significantly better than Docker, suitable for most AI agent workloads

---

## Approach 3: Firecracker MicroVMs

### How It Works
Each agent gets its own lightweight virtual machine with a dedicated Linux kernel. Firecracker VMs boot in ~125ms with <5 MiB memory overhead.

### Pros
- **Full kernel isolation**: Each VM has its own kernel - zero shared kernel attack surface
- **Strongest isolation**: Used by AWS Lambda and Fargate for multi-tenant isolation
- **Fast boot**: ~125ms (comparable to container start times)
- **Low overhead**: <5 MiB per VM, 150+ VMs per second per host
- **Battle-tested**: Trusted by AWS for production multi-tenant workloads

### Cons
- **Infrastructure complexity**: Requires microVM orchestration (not Docker-compatible)
- **KVM required**: Needs hardware virtualization support (not available on all hosts)
- **Different tooling**: Cannot use Docker directly, needs custom orchestration
- **Image management**: VM images vs container images - different build pipeline
- **Networking**: Requires custom network setup (TAP devices, bridge networking)

### Security Rating: **Excellent** - strongest isolation available, gold standard for untrusted code

---

## Approach 4: Kata Containers

### How It Works
Lightweight VMs that look and feel like containers. Each container is actually a VM with its own kernel, but managed through standard container tooling (Docker, Kubernetes).

### Pros
- **VM isolation with container UX**: Best of both worlds
- **Docker-compatible**: Works as a Docker runtime (like gVisor)
- **Kubernetes-compatible**: Supported RuntimeClass
- **Already supported**: Druppie's `SANDBOX_RUNTIME` config already has a `kata` option

### Cons
- **Higher overhead than gVisor**: VM boot adds ~200-500ms
- **Memory overhead**: Each VM needs its own kernel memory (~30-50 MiB)
- **KVM required**: Needs hardware virtualization
- **Less mature than Firecracker**: Smaller community, fewer production deployments

### Security Rating: **Excellent** - full VM isolation with container ergonomics

---

## Comparison Matrix

| Feature | Docker | gVisor | Firecracker | Kata |
|---------|--------|--------|-------------|------|
| Kernel isolation | No | Partial (user-space) | **Full** | **Full** |
| Container escape risk | **High** | Low | **Minimal** | **Minimal** |
| Boot time | ~50ms | ~100ms | ~125ms | ~300ms |
| Memory overhead | ~5 MiB | ~10 MiB | ~5 MiB | ~30-50 MiB |
| Docker compatible | Yes | **Yes** | No | **Yes** |
| I/O performance | Best | 70-90% | 95%+ | 90%+ |
| KVM required | No | No | **Yes** | **Yes** |
| Druppie support | **Yes** | Needs config | Needs rework | **Yes (config)** |
| Best for | Trusted code | Most workloads | Highest security | VM + container UX |

---

## Decision: gVisor for Immediate, Kata for Production

### Rationale

1. **gVisor is the pragmatic choice now:**
   - Docker-compatible (minimal infrastructure changes)
   - No KVM requirement (works on our current hosts)
   - Good-enough isolation for AI agents
   - The I/O overhead is acceptable for our use case

2. **Kata Containers for production hardening:**
   - Already partially supported (`SANDBOX_RUNTIME=kata`)
   - Full VM isolation when we move to KVM-capable hosts
   - Container UX means no workflow changes

3. **Firecracker is overkill for our scale:**
   - Requires custom orchestration (abandoning Docker)
   - The additional security over Kata doesn't justify the infrastructure rework
   - Consider if we ever serve external/untrusted users

---

## Additional Sandboxing Requirements (from Jeremy)

Beyond container runtime isolation, Jeremy specified:

### 1. Mandatory Scan Before Code Leaves Sandbox

```
Agent generates code → Unicode strip → glassworm-hunter scan → 
  If clean: code exits sandbox
  If flagged: quarantine + alert
```

**Implementation**: Add a "security gate" step in the control plane that intercepts all code output from sandbox containers before it's written to the workspace volume.

### 2. Network Isolation Enhancement

Current: Sandboxes on separate Docker network
Needed: Restrict outbound internet access from sandboxes

```yaml
# Restrict sandbox network to internal only
networks:
  druppie-sandbox-network:
    internal: true  # No external access
```

Exception: Package installation requires internet access. Options:
- **Proxy-only access**: Route through an internal proxy that logs and filters requests
- **Pre-cached dependencies**: Install all dependencies in the base image, block runtime installs
- **Allowlisted domains**: Only allow access to pypi.org, npmjs.org, and github.com

### 3. Package Installation Control

Agents should NOT be able to install arbitrary packages. Options:
- **Pre-approved package list**: Only packages on an allowlist can be installed
- **Scan-then-install**: Every `pip install` / `npm install` triggers a security scan before proceeding
- **Read-only filesystem**: Make the package installation directories read-only after base image build

### Recommended Approach
Combine pre-cached dependencies (in the sandbox base image) with a scan-then-install gate for any new packages the agent requests. This provides both speed and security.
