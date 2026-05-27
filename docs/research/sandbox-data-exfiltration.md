# Research: LLM Agent Data Exfiltration via Internet Access

**Date:** 2026-05-27
**Context:** Informs `docs/specs/sandbox-network-isolation-v2.md`

---

## Executive Summary

LLM agents that simultaneously hold sensitive data and internet access are vulnerable to data exfiltration through prompt injection. Real-world attacks (EchoLeak, AWS AgentCore DNS bypass) demonstrate this in production systems. The defense is network-layer isolation: never allow an agent sandbox to have both sensitive data access and outbound internet connectivity at the same time.

## The Lethal Trifecta

A data exfiltration vector exists whenever a single agent execution path holds all three:

1. **Access to private/sensitive data** — module APIs, business logic, credentials, internal documents
2. **Exposure to untrusted content** — user input, fetched URLs, document content, README files
3. **Outbound network channel** — HTTP requests, DNS queries, image tags, WebSocket connections

No single factor is sufficient. The danger is the combination. An attacker injects instructions into untrusted content, the agent (holding sensitive data) follows those instructions, and uses its network channel to exfiltrate.

### Why Prompt-Level Defenses Fail

- **Input filtering** — attackers craft payloads that evade classifiers (EchoLeak bypassed Microsoft's XPIA classifier)
- **Output filtering** — sharded exfiltration splits data across requests, reducing per-request leakage by 73% (Silent Egress paper)
- **Instruction hardening** — "never exfiltrate data" instructions are routinely ignored when the injection is sophisticated enough
- **The model is the confused deputy** — it holds legitimate privileges that get redirected by untrusted content

## Real-World Attacks

### EchoLeak (CVE-2025-32711) — Microsoft 365 Copilot

**What:** Zero-click prompt injection in Microsoft 365 Copilot enabling remote, unauthenticated data exfiltration via a single crafted email.

**Attack chain:**
1. Attacker sends email with hidden prompt injection payload
2. Copilot retrieves the email via normal retrieval process
3. Hidden instructions cause Copilot to embed sensitive data from user's context into outbound reference links
4. Reference-style Markdown links survive Copilot's safety filters
5. Client (Outlook/Teams) auto-fetches the external image URL → exfiltration complete
6. To bypass CSP, exploit uses Microsoft Teams preview API as proxy to attacker server

**Key lesson:** Defense-in-depth is required. No single filter suffices. Content security policies, input classifiers, and output filters all failed. The agent had data access AND network access AND processed untrusted content.

**Source:** arxiv 2509.10540 — "EchoLeak: The First Real-World Zero-Click Prompt Injection Exploit in a Production LLM System"

### AWS AgentCore DNS Exfiltration — Bedrock Code Interpreter

**What:** Sandbox mode enforced TCP/IP isolation but left DNS unrestricted, enabling full data exfiltration through DNS queries.

**Attack chain:**
1. Malicious CSV file contains prompt injection payload
2. LLM-generated Python code manipulated to establish DNS command-and-control channel
3. Attacker-controlled DNS authoritative server receives exfiltrated data encoded in DNS queries
4. Demonstrated: `whoami` execution, S3 bucket enumeration and exfiltration, AWS Secrets Manager credential retrieval
5. No VPC Flow Logs capture DNS traffic → attack is invisible to standard monitoring

**Key lesson:** "Complete isolation with no external access" claims must be verified at ALL protocol layers, not just TCP/IP. DNS is a viable exfiltration channel with sufficient bandwidth for credentials and structured data.

**Source:** Cloud Security Alliance research note — "AI Agent Trust Boundaries: DNS Escape and Exfiltration Flaws"

### Silent Egress — Implicit Prompt Injection via URL Previews

**What:** Adversarial instructions embedded in URL metadata (titles, snippets) cause agents to exfiltrate data through outbound requests, even when the final response appears harmless.

**Results:**
- 89% attack success rate (P(egress) ≈ 0.89) with qwen2.5:7b agent
- 95% of successful attacks evade output-based safety checks
- Introduced "sharded exfiltration" — splitting sensitive data across multiple requests
- Sharded approach reduces single-request leakage by 73%

**Key lesson:** Network egress should be treated as a first-class security outcome. Prompt-level defenses offer limited protection. System and network layer controls (domain allowlisting, redirect-chain analysis, per-session rate limiting) are considerably more effective.

**Source:** arxiv 2602.22450 — "Silent Egress: When Implicit Prompt Injection Makes LLM Agents Leak Without a Trace"

### README-Based Instruction Injection

**What:** Attackers plant prompt injection payloads in GitHub README files. Agents treat READMEs as authoritative project documentation, lowering the trust barrier.

**Attack chain:**
1. Attacker creates/modifies a public GitHub README with injection payload
2. Agent clones repo, reads README as "trusted" project documentation
3. Hidden instructions direct agent to locate sensitive files, construct exfiltration commands
4. Agent attempts `scp`, `curl`, or similar commands

**Results across agents:**
- Claude Computer Use: completed full end-to-end attack (file access, command execution, network transmission)
- OpenDevin: correctly located files and constructed exact `scp` command — failed only because sandbox blocks outbound traffic (capability gap, not security gap)
- OpenManus, Browser Use: all parsed and attempted injected instructions

**Key lesson:** The semantic vulnerability exists across ALL tested agents. OpenDevin's sandbox blocked it only at the network layer — proving that network-level isolation is the effective control.

**Source:** arxiv 2603.11862 — "You Told Me to Do It: Measuring Instructional Text-induced Private Data Leakage in LLM Agents"

## Defense Patterns

### 1. Network-Layer Isolation (Most Effective)

Default-deny all network egress. Explicit allowlist for required destinations. Block DNS except to controlled resolver. This is what stopped OpenDevin from being exploited — the sandbox had no internet access.

**Implementation in Druppie:** Per-agent network profiles. Agent that reads module data gets `sandbox-modules` network (no internet). Agent that needs internet gets `sandbox-inet` (no module access). Never both simultaneously.

### 2. Plan-then-Execute

Agent formulates a fixed plan before executing. Tool outputs cannot deviate the plan. Provides control flow integrity — untrusted content in tool outputs cannot trigger new actions.

**Limitation:** Does not prevent injection from the user prompt itself.

### 3. Taint Tracking / Provenance

Mark content from untrusted sources as TAINTED. Track taint propagation through the context window. Block tainted data from reaching network-capable tools (sinks).

**Limitation:** Complex to implement correctly. Requires runtime instrumentation of the agent's context management.

### 4. Dual-Agent Architecture

Separate agents for different trust levels. Privileged agent reads data but has no network. Unprivileged agent has network but reads only sanitized summaries from the privileged agent.

**Limitation:** Increased latency and complexity. Requires careful design of the information channel between agents.

### 5. Human-in-the-Loop for Outbound Actions

Approval gates for any action that could carry sensitive content outbound (email, HTTP requests, file uploads). The most reliable control but adds latency.

**Limitation:** Users approve without reading carefully. Not suitable for autonomous agents.

## Druppie-Specific Threat Model

### Assets at Risk
- Module SDK code and API specifications (proprietary business logic)
- Functional/technical design documents (business requirements, architecture)
- Agent execution context (conversation history, intermediate results)
- Git credentials and repository access

### Attack Vectors
1. **Module data injection** — malicious content embedded in module SDK responses
2. **User input injection** — crafted user prompts that instruct the agent to exfiltrate
3. **Dependency confusion** — malicious package on PyPI/npm that the agent installs
4. **DNS exfiltration** — agent runs `dig` or `nslookup` to send data to attacker DNS server
5. **HTTP exfiltration** — agent runs `curl` to POST data to attacker server

### Recommended Defenses (Priority Order)
1. **Per-agent network profiles** (this spec) — prevents vectors 4 and 5 by eliminating internet when module data is present
2. **make_plan validation** — prevents accidental ordering that creates the trifecta
3. **DNS filtering** (future) — restrict DNS to approved resolvers even on internet network
4. **Package registry mirroring** (future) — use controlled PyPI/npm mirrors instead of open internet
5. **Egress proxy with allowlisting** (future) — route all internet traffic through authenticated proxy with domain allowlist

## Relevant Frameworks

| Framework | Relevance |
|-----------|-----------|
| MITRE ATLAS | Documents indirect prompt injection and tool exfiltration techniques |
| CSA Zero Trust | Applicable to AI agent execution environments — continuous verification of network flows |
| CWE-346 | Origin validation — verify the source of instructions/data |
| CWE-20 | Input validation — scrutinize instructions from untrusted sources |
| CWE-284 | Improper access control — scope agent privileges to minimum needed |
| Agent Patterns Catalog | "Sandbox Isolation" and "Lethal Trifecta Threat Model" patterns |

## Sources

- arxiv 2509.10540 — EchoLeak
- arxiv 2602.22450 — Silent Egress
- arxiv 2603.11862 — README-based Instruction Injection
- arxiv 2506.08837v3 — Design Patterns for Securing LLM Agents against Prompt Injections
- CSA Research Note — AI Agent Trust Boundaries: DNS Escape and Exfiltration Flaws
- Agent Patterns Catalog — sandbox-isolation, lethal-trifecta patterns
- Safeguard.sh — Data Exfiltration via LLM Agents in 2026
- Safeguard.sh — Sandboxing LLM Agent Code Execution Patterns
