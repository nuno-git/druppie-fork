# Security Research Documents

This folder contains in-depth research, design choices, and decision records for improving Druppie's supply chain security posture. Each document covers a specific area of concern with pros/cons analysis and comparison of approaches.

## Context

In March 2026, Druppie was exposed to a supply chain attack via the `litellm` Python package (versions 1.82.7 and 1.82.8). Additionally, the `opencode-ai` tool was flagged as a potential GlassWorm vector (later found to be a likely misidentification - see document 01).

These incidents prompted a comprehensive security review by our Information Security Officer and this research initiative.

## Documents

| Document | Topic |
|----------|-------|
| [01-glassworm-threat-analysis.md](01-glassworm-threat-analysis.md) | GlassWorm malware: how it works, indicators of compromise, and the opencode-ai infection |
| [02-python-supply-chain-security.md](02-python-supply-chain-security.md) | Python dependency security: pinning, hashing, auditing, private registries |
| [03-nodejs-supply-chain-security.md](03-nodejs-supply-chain-security.md) | Node.js dependency security: lockfile integrity, npm hardening, scanning tools |
| [04-unicode-attack-detection.md](04-unicode-attack-detection.md) | Invisible Unicode attacks: detection methods, stripping/sanitization approaches |
| [05-ai-agent-sandboxing.md](05-ai-agent-sandboxing.md) | Container isolation for AI agents: Docker vs gVisor vs Firecracker |
| [06-dependency-update-automation.md](06-dependency-update-automation.md) | Dependabot vs Renovate: risks of auto-merge, recommended approval workflows |
| [07-cicd-security-gates.md](07-cicd-security-gates.md) | Pre-commit hooks and CI/CD gates for dependency scanning |
| [08-slsa-and-signing.md](08-slsa-and-signing.md) | SLSA framework and Sigstore/cosign for build provenance and package signing |
| [09-glassworm-hunter-integration.md](09-glassworm-hunter-integration.md) | Integrating glassworm-hunter into our architecture per our ISO's recommendations |
| [10-incident-lessons-learned.md](10-incident-lessons-learned.md) | Lessons from LiteLLM and GlassWorm incidents, and how they inform our strategy |
| [11-developer-environment-security.md](11-developer-environment-security.md) | Device management, environment standardization, credential management, network security, and BIO2/NIS2 compliance |

## How to Use

1. Read [10-incident-lessons-learned.md](10-incident-lessons-learned.md) first for context on what happened
2. Read the topic-specific documents for areas you want to dive deeper into
3. See the final implementation spec at [../SECURITY_IMPLEMENTATION_SPEC.md](../SECURITY_IMPLEMENTATION_SPEC.md) for the recommended action plan
