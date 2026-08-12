# Incident Lessons Learned

## Context

Druppie was affected by two supply chain security incidents in early 2026. This document captures the lessons learned and how they inform our security strategy going forward.

---

## Incident 1: LiteLLM Supply Chain Attack (March 2026)

### What Happened

- **Package**: `litellm` - a popular Python library for unified LLM provider interfaces
- **Compromised versions**: 1.82.7 and 1.82.8
- **Duration on PyPI**: ~40 minutes before quarantine
- **Scale**: 95 million monthly downloads, present in 36% of cloud environments
- **Our exposure**: Druppie pins `litellm==1.82.6` in `druppie/requirements.txt`

### Attack Chain

1. **Initial compromise**: Trivy (a security scanner used in LiteLLM's CI/CD) was itself compromised
2. **Token theft**: Attackers (group "TeamPCP") exfiltrated PyPI publishing tokens from LiteLLM's CI/CD pipeline
3. **Malicious upload**: Two compromised versions uploaded to PyPI using stolen tokens
4. **Three-stage payload**:
   - Stage 1: Credential harvesting (environment variables, tokens)
   - Stage 2: Lateral movement (using stolen credentials to access other systems)
   - Stage 3: Systemd backdoor (persistence mechanism)

### Why We Were (Partially) Protected

- **Version pinning**: We pinned `litellm==1.82.6`, so automatic pip installs wouldn't pull 1.82.7/1.82.8
- **Docker builds**: Our images are built with specific versions, not auto-updated

### Why We Were Still At Risk

- **No hash verification**: If someone ran `pip install litellm==1.82.6` and PyPI was serving a modified 1.82.6 (hypothetical but possible with a full PyPI compromise), we'd have no way to detect it
- **No lock file with hashes**: Our requirements.txt has version pins but no SHA-256 hashes
- **Manual updates**: A developer manually updating litellm could have pulled a compromised version
- **No CI/CD scanning**: No automated check would have caught a compromised dependency

### Key Lessons

1. **Version pinning is necessary but not sufficient**: Hashes are what actually verify integrity
2. **Even security tools can be attack vectors**: Trivy (a security scanner!) was the initial compromise vector
3. **CI/CD tokens are high-value targets**: Protect publishing tokens with maximum security
4. **Speed matters**: 40 minutes was enough for widespread compromise
5. **Official container images were safe**: LiteLLM's proxy Docker images were not affected - container images with pinned versions provide an additional layer of isolation

---

## Incident 2: opencode-ai / GlassWorm Report (Likely Misidentification)

### What Was Reported

- **Package**: `opencode-ai` - an AI coding tool used in our sandbox image
- **Claim**: GlassWorm malware infection, discovered by Jeremy Bode via security scan
- **Stated indicators**: Thousands of invisible Unicode characters, "Artifact 134" classification, postinstall GlassWorm deployment

### Independent Verification (2026-04-16)

Upon investigation, we could **NOT confirm** that opencode-ai is infected with GlassWorm:

- **glassworm-hunter**: Returns zero hits when scanning the opencode-ai package
- **IOC database**: opencode-ai is not listed in glassworm-hunter's known-infected packages
- **No public reports**: No security researcher or CVE advisory identifies this package as a GlassWorm vector
- **Rescana article**: The article Jeremy cited does not mention opencode-ai
- **"Artifact 134"**: Not a real classification - 134 is an XOR key in the ForceMemo Python variant

### What Likely Happened

The GlassWorm campaign DID target **anomalyco** (the org behind OpenCode) in March 2026. However, the compromised repository was `anomalyco/opencode-bench` (a peripheral benchmarking repo), NOT the main product or npm package. Jeremy likely conflated "anomalyco was targeted" with "the opencode-ai package is infected."

### Real Security Concerns

opencode-ai does have genuine (non-GlassWorm) vulnerabilities:
- **CVE-2026-22812**: Remote Code Execution
- **CVE-2026-22813**: Cross-Site Scripting

These warrant evaluation of whether opencode-ai should remain in our sandbox image.

### Key Lessons

1. **Verify security claims independently**: Even reports from trusted security professionals should be verified with automated tools before triggering emergency response
2. **Automated scanning provides objective evidence**: glassworm-hunter gave us a clear "clean" result to compare against the manual assessment
3. **Correlation is not causation**: An organization being targeted by GlassWorm does not mean all their packages are compromised
4. **The general threat is still real**: The GlassWorm campaign IS real and actively targeting supply chains - our defenses should still be improved regardless of this specific misidentification
5. **"It works" is still not a security assessment**: Even if opencode-ai isn't GlassWorm-infected, its real CVEs show that functionality doesn't equal security
6. **AI agents amplify the risk**: An AI agent that installs packages without review is a multiplication factor for supply chain attacks

---

## Combined Lessons: What Must Change

### Lesson 1: Every Dependency is a Trust Decision

**Before**: Dependencies were added based on functionality ("does it work?")
**After**: Every dependency must be evaluated for:
- Maintainer reputation and history
- Download statistics and age
- Known security issues
- Presence of postinstall scripts
- Source code quality (automated scanning for suspicious patterns)

### Lesson 2: Hash Everything

**Before**: Version pins without hashes
**After**: All dependencies must have cryptographic hashes verified at install time

### Lesson 3: Scan Continuously, Not Once

**Before**: No automated security scanning
**After**: Security scanning at every stage:
- Pre-commit (Unicode detection)
- CI/CD (full vulnerability + malware scan)
- Sandbox exit (mandatory scan before code leaves)
- Weekly full-codebase scan

### Lesson 4: AI Agents Need Guardrails

**Before**: Agents can install packages and generate code freely
**After**: 
- Agents work in isolated containers (gVisor/Kata)
- All agent output is stripped of suspicious Unicode
- All agent output is scanned before leaving sandbox
- Package installation requires approval or allowlisting

### Lesson 5: Credentials Must Be Rotated

**Before**: Long-lived tokens and SSH keys
**After**:
- Rotate ALL credentials after the GlassWorm incident
- Use short-lived tokens where possible
- Enable MFA (hardware keys, not TOTP) on all critical accounts
- Monitor for credential abuse

### Lesson 6: Defense in Depth

No single tool or practice prevents all attacks. Our security must be layered:

```
Layer 1: Dependency selection     → Package vetting, download stats, age checks
Layer 2: Installation integrity   → Hash verification, lock files
Layer 3: Vulnerability scanning   → pip-audit, npm audit, OSV scanner
Layer 4: Malware detection        → glassworm-hunter, anti-trojan-source, Socket.dev
Layer 5: Agent isolation          → gVisor/Kata containers, network restriction
Layer 6: Output filtering         → Unicode stripping, security gate
Layer 7: CI/CD gates             → All scans must pass before merge
Layer 8: Monitoring & response   → Alerts, quarantine, incident response
```

Each layer catches what the previous layers miss. The LiteLLM attack would have been caught by Layer 2 (hashes) or Layer 3 (pip-audit after CVE published). The GlassWorm attack would have been caught by Layer 4 (glassworm-hunter) or Layer 6 (Unicode stripping).

---

## Action Items (from Jeremy's Email)

Jeremy specified these actions. Status tracking:

| # | Action | Status | Document Reference |
|---|--------|--------|--------------------|
| 1 | Clean up repository (opschoonactie) | **TODO** | - |
| 2 | Integrate glassworm-hunter structurally | **Planned** | [09-glassworm-hunter-integration.md](09-glassworm-hunter-integration.md) |
| 3 | Security agent scans builder output | **Planned** | [09-glassworm-hunter-integration.md](09-glassworm-hunter-integration.md) |
| 4 | Isolated containers for all agents | **Planned** | [05-ai-agent-sandboxing.md](05-ai-agent-sandboxing.md) |
| 5 | Mandatory scan before code exits sandbox | **Planned** | [09-glassworm-hunter-integration.md](09-glassworm-hunter-integration.md) |
| 6 | Unicode stripping filter on agent output | **Planned** | [04-unicode-attack-detection.md](04-unicode-attack-detection.md) |
| 7 | Check package-lock.json / requirements.txt for suspicious entries | **Planned** | [02-python-supply-chain-security.md](02-python-supply-chain-security.md), [03-nodejs-supply-chain-security.md](03-nodejs-supply-chain-security.md) |
| 8 | Agent-based initial dependency review | **Planned** | [07-cicd-security-gates.md](07-cicd-security-gates.md) |
| 9 | Control over Python and npm environment integrity | **Planned** | [02-python-supply-chain-security.md](02-python-supply-chain-security.md), [03-nodejs-supply-chain-security.md](03-nodejs-supply-chain-security.md) |

See [../SECURITY_IMPLEMENTATION_SPEC.md](../SECURITY_IMPLEMENTATION_SPEC.md) for the full implementation plan with phases and timelines.
