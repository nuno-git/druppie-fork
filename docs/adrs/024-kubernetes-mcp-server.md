---
id: "024"
title: Dedicated read-only Kubernetes MCP server and kubernetes_admin agent
status: accepted
date: 2026-07-17
deciders:
  - nuno
supersedes: null
superseded_by: null
linked_prd: null
linked_research: null
---

# ADR 024: Dedicated read-only Kubernetes MCP server and kubernetes_admin agent

## Context

PR #257 added a read-only Kubernetes MCP server (module-kubernetes, port 9013)
and a dedicated kubernetes_admin agent for cluster status questions. Before this
change, Druppie had no way for agents to inspect the Kubernetes cluster. Users
who wanted to know whether pods were healthy, which services were running, or
how the cluster was doing had to use kubectl directly.

ADR 002 covers Kubernetes INFRASTRUCTURE decisions: hosting (Hetzner K3s),
database (CloudNativePG), networking (Traefik), autoscaling (HPA + KEDA), and
cluster provisioning. That ADR is about running Druppie ON Kubernetes. This ADR
is about Druppie agents inspecting the Kubernetes cluster itself -- an
application-level concern that ADR 002 does not address.

The forces at play:

- **Security boundary.** Cluster access requires a different security model than
  coding or file access. A compromised coding module should not grant access to
  the Kubernetes API. The MCP server must be isolated by both network and
  credentials.
- **Read-only by design.** Agents must never modify cluster state. No delete,
  scale, apply, exec, or patch operations. The design must make mutation
  impossible even if the MCP server is misused or an agent is compromised.
- **Agent specialization.** Cluster monitoring needs a different system prompt,
  different tool scoping, and different approval rules than general coding or
  data access. Routing a "how is the cluster doing?" question to a developer
  agent would give that agent unnecessary access to coding tools.
- **Planner integration.** The platform's orchestration layer (ADR 022) must be
  able to dispatch cluster status queries to the right agent without manual
  routing.

## Decision

Add a dedicated Kubernetes MCP server and a kubernetes_admin agent, both
read-only by construction.

### MCP server: module-kubernetes

A new MCP module at `druppie/mcp-servers/module-kubernetes/` exposes exactly
four read-only tools:

- `list_pods(namespace?, limit=100)` -- pods with status, restart count, age,
  node, and container-level state
- `list_nodes(limit=100)` -- nodes with Ready/NotReady status, conditions,
  CPU/memory capacity and allocatable
- `list_services(namespace?, limit=100)` -- services with type, cluster IP,
  and port mappings
- `get_cluster_health()` -- single healthy/unhealthy verdict with counts of
  unhealthy nodes, problem pods, and high-restart pods

The server runs on port 9013 and uses the official `kubernetes` Python client.
It loads in-cluster config when running as a pod (ServiceAccount token) and
falls back to the default kubeconfig for local development.

The server is accessible only within the Docker network (docker-compose) or as
a ClusterIP service (Helm/Kubernetes). No external port exposure.

### RBAC: ServiceAccount + ClusterRole with get/list/watch only

A dedicated ServiceAccount (`module-kubernetes`) is bound to a ClusterRole that
grants only `get`, `list`, and `watch` verbs on `pods`, `nodes`, `services`,
and `namespaces` in the core API group. No `create`, `update`, `patch`,
`delete`, or any other mutation verb is granted. This means even if the MCP
server code had a bug that allowed write operations, the Kubernetes API itself
would reject them.

### Agent: kubernetes_admin

A new agent definition at
`druppie/agents/definitions/kubernetes_admin.yaml`:

- Category: `execution`
- LLM profile: `cheap` (fast, low-cost model)
- Temperature: 0.1 (deterministic output)
- Max iterations: 10
- MCP scope: only the `kubernetes` MCP server with all four tools
- No coding, docker, or other MCP servers

The system prompt instructs the agent to start with `get_cluster_health` for
the overall picture, drill into `list_pods` and `list_nodes` when problems are
found, and summarize findings in plain language via `hitl_ask_question`. The
agent is explicitly told it is read-only and cannot modify the cluster.

### Planner routing

The planner (ADR 022) recognizes cluster status queries and routes them to
`kubernetes_admin`. The routing rules in `planner.yaml` match questions about
pod health, node status, service availability, and general cluster health.
This is a `general_chat` intent -- the agent reports findings but does not
create or modify projects.

### Network isolation

In docker-compose, module-kubernetes is on the internal Docker network with no
published ports. In Helm, it is a ClusterIP service with no Ingress. The
backend reaches it by internal hostname (`module-kubernetes:9013`). External
access is impossible by design.

## Consequences

Positive:

- **Safe K8s observability.** Non-admin users can ask about cluster status
  through agents without needing kubectl access or cluster-admin credentials.
- **RBAC-enforced read-only.** Even if the MCP server or agent is compromised,
  the Kubernetes API itself rejects write operations. Two layers of defense:
  no write tools in the MCP server, no write verbs in the ClusterRole.
- **Separate agent keeps tool scoping clean.** The kubernetes_admin agent has
  no access to coding, docker, or file system tools. A cluster status question
  cannot accidentally trigger a file write or container build.
- **Planner integration.** The orchestrator dispatches cluster queries to the
  right agent automatically. No manual routing needed.
- **Deterministic and cheap.** Low temperature and cheap LLM profile keep
  cluster status responses fast and predictable.
- **Tested read-only guarantee.** Static analysis tests
  (`test_kubernetes_readonly.py`) verify that only the four expected tools are
  exposed, no tool name contains a write verb, and the module uses only
  read-only Kubernetes API methods.

Negative:

- **New MCP module to maintain.** module-kubernetes adds to the set of MCP
  servers that need Dockerfiles, Helm templates, CI builds, and dependency
  updates.
- **New agent to maintain.** kubernetes_admin adds to the agent definitions
  that need prompt tuning and testing.
- **Read-only limitation is intentional but constraining.** The agent cannot
  take self-healing actions (restart a crashlooping pod, scale a deployment,
  cordon a node). This is by design -- write operations need a separate auth
  model and are out of scope for this ADR.
- **Future write access needs a separate auth model.** If Druppie ever needs
  agents to modify cluster state, a new ADR must define the auth model
  (separate agent, elevated approval role, per-operation RBAC). The current
  design makes this safe by making it impossible.
