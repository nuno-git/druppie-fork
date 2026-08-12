# Agent Internet Safety: Unified Defense Architecture — Summary

> **Status:** Revised v3 summary  
> **Date:** 2026-06-17  
> **Based on:**  
> - `docs/research/agent-internet-safety.md` (unified architecture)  
> - `docs/research/sandbox-data-exfiltration.md` (threat research)  
> - `docs/specs/sandbox-network-isolation.md` (v1 network tiers)  
> - `docs/specs/sandbox-network-isolation-v2.md` (temporal separation & dynamic enforcement)  

---

## 1. The Problem: The Lethal Trifecta

LLM agents that simultaneously hold **(1) sensitive data**, **(2) exposure to untrusted content**, and **(3) an outbound communication channel** are vulnerable to prompt-injection-driven data exfiltration. No single factor is dangerous; the combination is lethal. Prompt-level defenses (input filtering, output filtering, instruction hardening) fail against sophisticated attacks.

### Real-World Attacks Referenced

| Attack | CVE / Source | Key Lesson |
|--------|-------------|------------|
| **EchoLeak** | CVE-2025-32711 (arxiv 2509.10540) | Zero-click injection via email → outbound Markdown reference links. Defense-in-depth is required — CSP, classifiers, and filters all failed. |
| **AWS AgentCore DNS Exfiltration** | CSA research note | TCP/IP isolation was incomplete; unrestricted DNS enabled full exfiltration via DNS queries. Verify isolation at ALL protocol layers. |
| **Silent Egress** | arxiv 2602.22450 | URL preview metadata caused 89% success rate; sharded exfiltration splits data across requests, evading per-request checks. |
| **README-Based Instruction Injection** | arxiv 2603.11862 | Attackers plant payloads in GitHub READMEs. Agents treat them as trusted docs. Network-level isolation was the only control that stopped exploitation (OpenDevin). |

---

## 2. The Core Tension

Druppie agents need **both** public internet data (docs, packages, APIs) **and** proprietary module data (Azure SQL, Data Lake, SDKs). The requirements conflict:

- **R1:** Agents must browse the internet  
- **R2:** Agents must read proprietary module data  
- **R3:** Module data must never be exfiltrated via the internet  
- **R4:** Agents must combine internet + module data for real applications  
- **R5:** Solution must be practical (not require approval for every action)  

No single agent can safely hold both internet access and module data at the same time. The solution is **temporal separation + defense in depth**.

---

## 3. Unified Defense Architecture (4 Layers)

The architecture combines deterministic infrastructure controls with application-level enforcement and human oversight:

```
LAYER 0: TEMPORAL SEPARATION & NETWORK ISOLATION (v2)
├── Pipeline ordering: internet phases → module phases → isolated
├── Dynamic network switching per agent / tool call
├── Persistent workspace volumes across transitions
├── One-way network transitions (internet → modules → isolated)
└── Primary defense — operates automatically, no user involvement

LAYER 1: CONTEXT-AWARE APPROVAL
├── Tracks data origins across the pipeline
├── Gates tool calls when sensitive data + risky operation detected
├── User-facing approval with full data visibility
└── Secondary defense — catches edge cases and policy escapes

LAYER 2: INFORMATION FLOW CONTROL (IFC)
├── Deterministic policy enforcement with data origin labels
├── Data origin labels propagate through tool calls
├── Block operations that mix untrusted + sensitive data
└── Tertiary defense — hard block with audit trails

LAYER 3: APPLICATION-LEVEL SAFEGUARDS
├── Safe visualization paths (server-side rendering)
├── Web content sanitization for documentation
├── Parameter scanning for exfiltration patterns
└── Final defense — reduces attack surface
```

**Key insight:** Layer 0 (temporal separation) and Layer 2 (IFC) are the **primary defenses** — deterministic, automatic, and user-independent. Layer 1 (approval) is a safety net; if users suffer approval fatigue, Layers 0 and 2 still protect them.

---

## 4. Layer 0: Temporal Separation & Network Isolation

### Network Tiers (v1 Spec)

| Tier | Network Name | Access | Agent Examples |
|------|-------------|--------|----------------|
| **Isolated** | `druppie-sandbox-net` | No external access | `business_analyst`, `architect`, `deployer` |
| **Internet** | `druppie-sandbox-inet` | Outbound internet (NAT) | `developer`, `data_fetcher`, `installer` |
| **Modules** | `druppie-sandbox-modules` | Module MCP servers only | `module_integrator`, `module_tester` |

All containers start on the isolated base network. The agent's `sandbox.networks` list adds tiers on top.

### Dynamic Network Enforcement (v2)

**Old (v1, broken):** Networks are applied **once** at container creation. Agents sharing a session inherit whatever networks the first agent had.

**New (v2):** `_sync_networks()` adjusts container networks **before every command**:
- Disconnects networks the agent no longer needs
- Connects networks the agent needs
- Enforces: module access can never coexist with internet in the same context

### Pipeline Ordering — Defer Module Access

The pipeline is strictly ordered to minimize risk:

```
installer (internet) → data_fetcher (internet) → developer (internet) → test_builder (internet) → [ONE-WAY TRANSITION] → module_integrator (modules) → module_tester (modules) → deployer (isolated)
```

**Why this ordering matters:**
- Developer has internet for the **entire coding phase** (pip install, browse docs, fetch APIs)
- All dependencies resolved while internet is available
- Code is tested with **mocks** before real module integration
- Module integration is just "swap mock imports for real imports"
- Only **one network transition** (internet → modules), irreversible

### Workspace Persistence

Per-session workspace volume (`druppie-ws-{session}-{scope}`):
- Shared across all agents in a session
- Survives container recreation during network transitions
- `pip install` output persists across phases
- Destroyed on session end

**Security note:** Filesystem is intentionally shared. Data flows through the workspace. Security relies on **network isolation**, not filesystem isolation.

### Pipeline Validation

`validate_plan_network_order(steps)` rejects any plan where an internet-enabled agent follows a module-access agent. This prevents accidental trifecta creation.

---

## 5. Layer 1: Context-Aware Approval

### How It Works

Instead of always or never requiring approval for a tool, the system tracks the agent's **data origins** and triggers approval only when risky combinations are detected.

**Example:** `fetch_url` normally requires no approval. But if the agent previously called `dataaccess:read_data`, the system recognizes proprietary data is now in context and gates the web request.

### SessionContext & DataOrigin Tracking

```
DataOrigin values:
- WEB — Content from public internet (untrusted)
- SANITIZED_WEB — Internet content that passed sanitization (still higher risk than CODING)
- DATAACCESS — Proprietary data from databases (confidential)
- CODING — Workspace files (confidential if module-derived)
- USER — Input from authenticated user (trusted)
- SYSTEM — System prompts and configuration (trusted)
- INTERNAL — Druppie internal APIs
```

`SessionContext` records every tool call and its origin. By checking `session_context.data_origins` before dispatching tools, the system detects dangerous combinations.

### Approval Roles

| Role | When Used |
|------|-----------|
| `session_owner` | Routine context-aware approvals (user understands their workflow) |
| `developer` / `architect` | Re-planning, Clean Room, technical judgment needed |
| `admin` | High-risk operations, progressive escalation |

### Approval Fatigue Mitigation

Approval fatigue is a real risk — users habitually click "Approve," nullifying the control:

1. **IFC as primary defense** — approval is a safety net, not the main control
2. **Minimize approval frequency** — temporal separation already prevents most risky combinations
3. **Smart defaults** — default to Deny with timeout, require explicit "Yes, I understand" checkbox
4. **Progressive escalation** — repeated suspicious approvals escalate to `admin`
5. **Rich context UI** — show exactly what data was accessed, make Deny more prominent than Approve

---

## 6. Layer 2: Information Flow Control (IFC)

### Core Concept

IFC is a security model where **every piece of data is tagged with a label** (origin + sensitivity) and policies enforce rules about how labeled data can flow through the system.

**DataLabel structure:**
- `origin` — where data came from (WEB, DATAACCESS, CODING, etc.)
- `sensitivity` — PUBLIC, INTERNAL, CONFIDENTIAL, RESTRICTED
- `source` — specific identifier
- `timestamp` — when it entered the system

### Policy Engine

Before any tool executes, the `PolicyEngine` evaluates policies against the tool being called and current data origins in context:

| Policy | What It Does |
|--------|-------------|
| `no_exfiltration` | Block `web:fetch_url` whenever `DATAACCESS` or `CODING` (module-derived) is present |
| `safe_visualization` | Require server-side rendering for proprietary data |

Policy results: **ALLOWED**, **BLOCKED** (hard block, no user override), or **REQUIRES_APPROVAL**.

### ToolResult Labels

Every tool result carries a `DataLabel`. When `dataaccess:read_data` returns customer data, it is tagged `origin=DATAACCESS, sensitivity=RESTRICTED`. If a later tool call is `web:fetch_url`, IFC sees the conflict and blocks.

---

## 7. Layer 3: Application-Level Safeguards

### Safe Visualization

`dataaccess_create_chart_from_source` (server-side rendering) is the **only** approved path for visualizing proprietary data. Never `dataaccess_read_data` followed by a client-side chart tool.

### Web Content Sanitization

When agents fetch documentation:
1. Extract visible text only
2. Remove zero-width / invisible characters
3. Pattern-match injection markers
4. Wrap with `[BEGIN UNTRUSTED WEB CONTENT: {url}]` delimiters

**Critical caveat:** Sanitization is NOT a guarantee. It reduces but does not eliminate injection risk.

### Trusted Documentation Cache (TDC)

Pre-populated documentation cache (`/docs/cache/`) eliminates the need for live `fetch_url` during module-tainted phases:
- Built during safe internet phase
- Mounted read-only
- Carries `SANITIZED_WEB` origin — never reclassified as `CODING`
- Re-scanned on read with updated heuristics

### Parameter Scanning

Outbound requests are scanned for high-entropy strings (potential secrets) and data patterns (emails, phone numbers). Suspicious requests trigger approval gates.

---

## 8. Fine-Grained Flexibility Mechanisms

The core invariant — *no single agent context window may simultaneously contain proprietary data and an outbound internet channel* — is non-negotiable. But **how** it's enforced can be made flexible without relaxing the invariant:

### Per-File Origin Tracking (PFOT)

Replaces the coarse session-level `CODING` flag with a **file-level registry**:
- Opening `README.md` (non-module) → `fetch_url` is **allowed**
- Opening `customer_segments.py` (module-derived) → `fetch_url` is **blocked**
- Session is only tainted by files actually **read into context**, not by files merely existing in the workspace

### Context Window Segmentation (CWS)

Allows an agent to fetch documentation mid-workflow even after module data is present:
1. **Segment 1:** Module integration (module data in context)
2. **Segment 2:** Fresh agent with **empty context**, subset workspace (no module files), approved by expert → fetches docs, writes to shared workspace
3. **Segment 3:** Original agent resumes with new docs available (tagged `SANITIZED_WEB`)

### Safe Summarisation Gateway

Before module data enters an internet-facing context, raw data is passed through a trusted summariser that strips values and outputs only **statistical aggregates** (schema, counts, distributions) with downgraded `INTERNAL` label. Internet-phase agents can work with insights, but never raw proprietary values.

---

## 9. Real-World Workflow: Building a Dashboard

### Scenario

Build a dashboard combining **public CBS data** with **proprietary module data** (demographics, geo modules).

### Data Flow Through Filesystem

**Phase 1-4 (Internet):**
- `installer`: pip install dependencies (`[internet]`)
- `data_fetcher`: Fetch CBS data, save to `/workspace/data/cbs/` (`[internet]`)
- `developer`: Write dashboard using **mock** module clients (`[internet]`)
- `test_builder`: Write/run tests with mocks (`[internet]`)

**Phase 5-6 (Modules — No Internet):**
- `module_integrator`: Replace mocks with real SDK calls (`[modules]`)
- `module_tester`: Run integration tests against real module servers (`[modules]`)

**Phase 7:**
- `deployer`: Push code via proxy (`[]` isolated)

**Security invariants maintained:**
- CBS data never reaches internet-connected agent alongside module data
- Module data never reaches an internet-connected agent
- When module data enters context (Phase 5), internet is already disconnected
- Prompt injection in CBS data cannot exfiltrate module data

---

## 10. Re-Planning & Clean Room

### The Problem

If the `module_integrator` (no internet) discovers it needs a new dependency, re-enabling internet risks exposing module data to the web.

### Tiered Strategy

| Tier | Mechanism | When |
|------|-----------|------|
| **A** | **Pre-staged base image** | Common packages baked into sandbox image; covers 90% of needs |
| **B** | **Trusted package proxy** | If no module data exists yet, install from approved read-only mirror |
| **C** | **Clean Room** | Last resort — full isolation when module data is present |

### Clean Room Protocol (Tier C)

1. Agent signals via `done()` with reason
2. Orchestrator creates dev/architect approval gate
3. Reviewer inspects git diff for injection artifacts
4. If approved:
   - Current container destroyed
   - **Workspace volume destroyed** (contains module data)
   - Fresh empty workspace + transfer volume created
   - New container with `[internet]`, EMPTY workspace, transfer volume
   - `pip install` runs into transfer volume
   - Internet container destroyed
   - Git clone restores code; transfer packages extracted
   - New container with `[modules]`, full workspace restored

---

## 11. Clean Room Research + Offline Build Architecture

### Core Principle

An evolved architecture (later in v2) proposes an even stricter model: **developers NEVER have internet**. Internet access is reserved for dedicated **clean room agents** running in ephemeral containers with:
- `[internet]` network
- **Ephemeral workspace** (destroyed on stop)
- **Staging volume** as the only bridge to the shared workspace
- **No shared workspace mount** (no module data exposure)

### Pipeline

```
clean room (internet, ephemeral):
  research_agent → package_agent → data_fetch_agent
  ↓ (after dev/architect approval gates)
build phase (offline, shared workspace):
  installer ← internal registry
  developer ← research report
  test_builder ← internal registry
  module_integrator ← [modules] network
  deployer ← isolated
```

### Internal Mirror Registry

- Private PyPI/npm mirror on `sandbox-net` (no internet)
- Populated only by approved `package_agent` (clean room)
- Build agents install with `pip install --index-url http://registry:8080/`

### Comparison

| Aspect | Previous (developer had internet) | Clean Room (developers never have internet) |
|--------|-----------------------------------|-----------------------------------------------|
| Developer network | `[internet]` | `[]` isolated |
| Package source | Live PyPI | Internal mirror registry |
| Documentation | Live browsing | Research report (human-reviewed) |
| Transfer mechanism | Implicit shared filesystem | Explicit staging + MANIFEST + approval gate |
| Validation | None | Checksums, type checks, size limits, human review |
| Security guarantee | No exfiltration when module data present | ABSOLUTE — no agent ever has both internet and shared volume |

### MANIFEST + Transfer Validation

Every clean room writes a `MANIFEST.json` to the staging volume listing all files with SHA-256 checksums. The receiving side validates:
- Every MANIFEST entry exists
- Every checksum matches
- No extra files outside MANIFEST
- No excluded patterns (`.git`, `node_modules`, `.env`)
- File type and size limits enforced

If any validation fails → transfer rejected, staging purged, alert logged, pipeline paused for review.

---

## 12. Updating Existing Projects

### Two-Phase Entry Protocol

When updating an existing repo that may contain files of unknown provenance:

**Phase A: Repo Initialiser (isolated tier)**
- Clones repo to scratch workspace with **no network**
- Generates `RepoDataMap` — classifies files by origin:
  - `DATAACCESS_DERIVED` — SQL connection strings, API keys
  - `UNTRUSTED` — suspicious dependency declarations
  - `CODING` — standard source files

**Phase B: Classification-Driven Pipeline**
| Classification | Behavior |
|----------------|----------|
| No module indicators | Standard internet phases |
| Contains module indicators | Session pre-classified as `MODULE-TAINTED`; internet phases use shadow workspace |
| Contains `UNTRUSTED` markers | Block all agents; raise approval gate |

---

## 13. Cross-Session Data Transfer (Git Commits)

**The concern:** If Session A commits module data to git, and Session B clones that repo, has the temporal separation been bypassed?

**Answer:** IFC blocks `fetch_url` whenever `CODING` origin is present. But three residual risks remain:

1. **Coarse-grained origin tracking** — once any file is read, the session is marked `CODING`. PFOT fixes this by tracking per-file.
2. **Origin lost at git boundary** — `DATAACCESS` label becomes `CODING` after git commit/clone. **Mitigation:** Repository provenance tagging (`.druppie-provenance` file) pre-populates `data_origins` in future sessions.
3. **Non-`fetch_url` exfiltration** — committed data could leave via `commit_and_push` to attacker-controlled remote. **Mitigation:** remote URL allowlisting + push-time scanning.

---

## 14. Open Design Questions

### Research Phase Tension

Module API knowledge must reach the developer somehow, but giving module schemas to an internet-connected agent re-establishes the trifecta.

**Resolutions evaluated:**
- **A:** Accept API schemas as non-sensitive (like public API docs) — most pragmatic
- **B:** Separate pipelines + feature-only functional design — developer never sees module knowledge
- **C:** Human as the bridge — dev/architect reads both reports and writes the FD

This is a **product decision**, not purely a security decision — it depends on whether Druppie's competitive moat is the module APIs or the data they return.

---

## 15. Implementation Roadmap

| Phase | Duration | Goal |
|-------|----------|------|
| **0** | Weeks 1-2 | v2 temporal separation: `_sync_networks()`, plan validation, workspace volumes, agent YAML updates |
| **1** | Weeks 3-4 | Context-aware approval: `requires_approval_if` schema, `SessionContext`, UI integration |
| **2** | Weeks 5-7 | IFC: `DataLabel`, `PolicyEngine`, audit logging |
| **3** | Weeks 8-9 | Application safeguards: web sanitization, safe visualization, parameter scanning |
| **4** | Week 10 | Clean Room: re-enablement approval gates, transfer volumes, package extraction |

---

## 16. Key Takeaways

1. **The lethal trifecta is real and demonstrated in production** (EchoLeak, AWS AgentCore DNS, Silent Egress).
2. **Temporal separation (Layer 0) is the load-bearing wall.** Network isolation prevents simultaneous internet + module access by construction.
3. **IFC (Layer 2) provides deterministic, automatic enforcement.** Unlike approval-based systems, it does not depend on users paying attention.
4. **Approval gates (Layer 1) are a safety net, not the primary defense.** They should be rare in normal workflows. Frequent approvals indicate pipeline design or IFC policy problems.
5. **Data flows through the filesystem, not the LLM context.** Internet agents and module agents never share a context window. The workspace volume is the bridge.
6. **Flexibility lives in IFC, not in relaxing Layer 0.** Per-File Origin Tracking, Context Window Segmentation, and Trusted Documentation Cache enable iterative workflows without violating the core invariant.
7. **The clean room model (developers never have internet)** provides the highest security guarantee: no agent ever simultaneously holds internet access and the shared workspace.
