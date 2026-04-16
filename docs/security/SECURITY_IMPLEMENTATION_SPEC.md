# Security Implementation Spec: Supply Chain Attack Prevention

> **Status**: DRAFT - Pending review by Jeremy Bode (ISO) and development team  
> **Date**: 2026-04-16  
> **Author**: Security research initiative following LiteLLM and GlassWorm incidents  
> **Branch**: `security_improvements`

---

## Executive Summary

Druppie was exposed to the LiteLLM PyPI supply chain attack (March 2026). Additionally, our ISO flagged opencode-ai as a potential GlassWorm vector, though independent verification with glassworm-hunter could NOT confirm this (see [research/01-glassworm-threat-analysis.md](research/01-glassworm-threat-analysis.md) for details). Regardless, these incidents highlight critical gaps in our supply chain security that this spec addresses.

The plan is organized into four phases, ordered by urgency and impact. Each phase builds on the previous one.

---

## Phase 0: Verification & Baseline (Immediate - Before Any Other Work)

### 0.1 Verify opencode-ai status

**What**: Independently verify whether opencode-ai is compromised, and address its real CVEs.

**Context**: Jeremy flagged opencode-ai as a GlassWorm vector, but glassworm-hunter scans return clean and no public security report confirms this (see [research/01-glassworm-threat-analysis.md](research/01-glassworm-threat-analysis.md)). However, opencode-ai does have real CVEs (CVE-2026-22812 RCE, CVE-2026-22813 XSS).

**Action**:
- Share glassworm-hunter scan results with Jeremy and discuss findings
- Evaluate whether opencode-ai should remain in sandbox image given its real CVEs
- If keeping it: update to latest patched version
- If removing it: find alternative or remove from `Dockerfile.sandbox`

### 0.2 Run glassworm-hunter full scan

**What**: Scan the entire codebase and all installed packages for GlassWorm indicators.

**How**:
```bash
pip install glassworm-hunter
glassworm-hunter scan --path /path/to/druppie
```

**Action on findings**: Quarantine any flagged files. If scan is clean (as expected), this establishes our verified baseline.

### 0.3 Credential rotation (as precaution)

**What**: Even though the GlassWorm infection is unconfirmed, rotating credentials is good hygiene given the LiteLLM exposure and general supply chain risk.

**Priority checklist** (rotate these regardless):
- [ ] INTERNAL_API_KEY (MCP server auth - currently uses default value)
- [ ] SANDBOX_API_SECRET (HMAC secret)
- [ ] ZAI_API_KEY, DEEPINFRA_API_KEY, and other LLM provider keys
- [ ] Gitea admin credentials and tokens
- [ ] GitHub personal access tokens (team members who used compromised litellm versions)

**Lower priority** (rotate if time allows):
- [ ] GitHub App credentials
- [ ] Keycloak admin credentials
- [ ] Database passwords

---

## Phase 1: Dependency Integrity (Week 1-2)

### 1.1 Python: Hash-pinned dependencies

**What**: Convert all `requirements.txt` files to use pinned versions with SHA-256 hashes.

**How**:
```bash
# Install pip-tools (or use uv)
pip install pip-tools

# For each requirements file:
# 1. Rename requirements.txt → requirements.in (keep version ranges)
# 2. Generate locked requirements with hashes
pip-compile --generate-hashes requirements.in -o requirements.txt

# 3. Update Dockerfiles to use --require-hashes
# In Dockerfile: pip install --require-hashes -r requirements.txt
```

**Files to convert**:
- `druppie/requirements.txt` → `druppie/requirements.in` + `druppie/requirements.txt` (compiled)
- `druppie/mcp-servers/module-coding/requirements.txt`
- `druppie/mcp-servers/module-docker/requirements.txt`
- `druppie/mcp-servers/module-filesearch/requirements.txt`
- `druppie/mcp-servers/module-web/requirements.txt`
- `druppie/mcp-servers/module-archimate/requirements.txt`
- `druppie/mcp-servers/module-registry/requirements.txt`

**Dockerfile changes**:
```dockerfile
# Before:
RUN pip install -r requirements.txt

# After:
RUN pip install --require-hashes --no-deps -r requirements.txt
```

### 1.2 Node.js: Commit lock files and enforce npm ci

**What**: Commit `frontend/package-lock.json` to version control and use `npm ci` everywhere.

**How**:
1. Remove `package-lock.json` from `.gitignore` (if present for frontend)
2. Run `npm install` in `frontend/` to generate lock file
3. Commit the lock file
4. Update all Dockerfiles and scripts to use `npm ci` instead of `npm install`

**Dockerfile changes**:
```dockerfile
# Before (frontend/Dockerfile):
RUN npm install

# After:
RUN npm ci --frozen-lockfile
```

### 1.3 Add pip-audit to CI/CD

**What**: Add Python vulnerability scanning to every PR.

**GitHub Actions step**:
```yaml
- name: Audit Python dependencies
  run: |
    pip install pip-audit
    pip-audit -r druppie/requirements.txt
```

### 1.4 Add npm audit to CI/CD

**What**: Add Node.js vulnerability scanning to every PR.

**GitHub Actions step**:
```yaml
- name: Audit npm dependencies
  run: |
    cd frontend && npm audit --audit-level=high
    cd ../background-agents && npm audit --audit-level=high
```

### 1.5 Add lockfile-lint to CI/CD

**What**: Verify lock files point to expected registries and use HTTPS.

```yaml
- name: Verify lockfile integrity
  run: |
    npx lockfile-lint --path frontend/package-lock.json --type npm --allowed-hosts npm --validate-https
    npx lockfile-lint --path background-agents/package-lock.json --type npm --allowed-hosts npm --validate-https
```

### 1.6 Central Package Registry (DevPI + Verdaccio)

**What**: Set up internal package registries that all developers, CI/CD, and Docker builds pull from. No one downloads directly from PyPI/npmjs.org.

**Why**: A central registry gives us:
- **Single source of truth**: All packages flow through one controlled point
- **Quarantine window**: Delay mirroring new versions by 24-72 hours, giving the community time to catch malicious packages (the LiteLLM attack was live for only ~40 minutes)
- **Caching**: Faster builds, offline availability, protection against PyPI/npm outages
- **Audit trail**: Log exactly which packages were downloaded, when, and by whom
- **Allowlisting**: Can restrict which packages are available at all
- **Central scanning**: Run security scans on packages once at the registry level, not per-developer

**Architecture**:
```
Public PyPI ──► DevPI (internal) ──► All Python consumers
                 │                    (Dockerfiles, dev machines, CI/CD, sandbox)
                 ├── Quarantine delay (24-72h for new versions)
                 ├── Vulnerability scan on sync
                 └── Audit log

Public npmjs ──► Verdaccio (internal) ──► All Node.js consumers
                  │                        (frontend, background-agents, sandbox)
                  ├── Quarantine delay (24-72h for new versions)
                  ├── Vulnerability scan on sync
                  └── Audit log
```

**Implementation - Python (DevPI)**:
```bash
# Run DevPI as a Docker service (add to docker-compose.yml)
# Configure all pip.conf / requirements installations to use it
pip config set global.index-url http://devpi.internal:3141/root/pypi/+simple/
pip config set global.trusted-host devpi.internal
```

**Implementation - Node.js (Verdaccio)**:
```bash
# Run Verdaccio as a Docker service (add to docker-compose.yml)
# Configure all .npmrc files to use it
npm config set registry http://verdaccio.internal:4873/
```

**Docker Compose services** (to add):
```yaml
devpi:
  image: devpi/devpi:latest
  ports:
    - "3141:3141"
  volumes:
    - devpi_data:/data
  networks:
    - druppie-new-network
  healthcheck:
    test: ["CMD", "curl", "-f", "http://localhost:3141/+api"]

verdaccio:
  image: verdaccio/verdaccio:latest
  ports:
    - "4873:4873"
  volumes:
    - verdaccio_data:/verdaccio/storage
    - ./config/verdaccio.yaml:/verdaccio/conf/config.yaml
  networks:
    - druppie-new-network
  healthcheck:
    test: ["CMD", "curl", "-f", "http://localhost:4873/-/ping"]
```

**All Dockerfiles and developer machines must be configured to pull from internal registries only.** This is enforced via:
- `pip.conf` in Docker images pointing to DevPI
- `.npmrc` in Docker images pointing to Verdaccio
- lockfile-lint verifying that lock files reference the internal registry

For detailed pros/cons comparison of DevPI vs Artifactory vs Nexus (Python) and Verdaccio vs alternatives (Node.js), see:
- [research/02-python-supply-chain-security.md](research/02-python-supply-chain-security.md) (Approach 4)
- [research/03-nodejs-supply-chain-security.md](research/03-nodejs-supply-chain-security.md) (Approach 7)

---

## Phase 2: Malware Detection & Unicode Defense (Week 2-3)

### 2.1 Integrate glassworm-hunter in CI/CD

**What**: Run glassworm-hunter on every PR to catch GlassWorm variants.

```yaml
- name: GlassWorm malware scan
  run: |
    pip install glassworm-hunter
    glassworm-hunter scan --path .
```

### 2.2 Integrate anti-trojan-source in CI/CD

**What**: Detect invisible Unicode characters in all source files.

```yaml
- name: Unicode attack detection
  run: |
    npx anti-trojan-source --files "**/*.{py,js,jsx,ts,tsx,json,yaml,yml,sh}"
```

### 2.3 Add pre-commit hooks

**What**: Install pre-commit framework with security hooks on all developer machines.

**Create `.pre-commit-config.yaml`**:
```yaml
repos:
  # Unicode attack detection
  - repo: https://github.com/lirantal/anti-trojan-source
    rev: v1.4.0
    hooks:
      - id: anti-trojan-source
        types: [text]

  # Secret detection
  - repo: https://github.com/gitleaks/gitleaks
    rev: v8.21.0
    hooks:
      - id: gitleaks

  # Python linting
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.4.0
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format

  # Lock file verification
  - repo: local
    hooks:
      - id: lockfile-lint-frontend
        name: lockfile-lint (frontend)
        entry: npx lockfile-lint --path frontend/package-lock.json --type npm --allowed-hosts npm --validate-https
        language: system
        files: frontend/package-lock\.json$
        pass_filenames: false

      - id: lockfile-lint-agents
        name: lockfile-lint (background-agents)
        entry: npx lockfile-lint --path background-agents/package-lock.json --type npm --allowed-hosts npm --validate-https
        language: system
        files: background-agents/package-lock\.json$
        pass_filenames: false
```

### 2.4 Build Unicode stripping filter

**What**: Create a Python utility that strips suspicious Unicode from agent output.

**Where**: `druppie/core/unicode_filter.py`

**Integration points**:
1. In `druppie/execution/orchestrator.py` - filter LLM responses before processing
2. In sandbox control plane - filter all output before it leaves the sandbox

**Behavior**:
- Strip all Unicode Format (Cf) and Control (Cc) characters except standard whitespace
- Strip Private Use Area, Variation Selectors, Tag Characters, Zero-Width characters
- Log every stripped character for security audit trail
- Alert if more than a threshold number of suspicious characters are found

### 2.5 Add secret scanning (gitleaks)

**What**: Prevent credentials from being committed to the repository.

```yaml
- name: Secret scanning
  uses: gitleaks/gitleaks-action@v2
  env:
    GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

---

## Phase 3: Agent Isolation & Security Gate (Week 3-5)

### 3.1 Switch sandbox runtime to gVisor

**What**: Replace standard Docker runtime with gVisor for sandbox containers.

**How**: Install gVisor (`runsc`) on the host and configure Docker:
```json
// /etc/docker/daemon.json
{
  "runtimes": {
    "runsc": {
      "path": "/usr/local/bin/runsc"
    }
  }
}
```

Update sandbox manager to use `runsc` runtime when creating containers.

### 3.2 Restrict sandbox network

**What**: Make sandbox network internal-only (no direct internet access).

```yaml
# docker-compose.yml
networks:
  druppie-sandbox-network:
    internal: true
```

**Package installation**: Route through a proxy or use pre-cached dependencies in the base image.

### 3.3 Implement security gate in control plane

**What**: Add mandatory scanning before any code exits the sandbox.

**Architecture**:
```
Sandbox → Control Plane Security Gate → Workspace
                    │
           1. Unicode strip
           2. glassworm-hunter scan
           3. Pattern check
                    │
           Clean → Allow
           Flagged → Quarantine + Alert
```

**Where**: `background-agents/packages/local-control-plane/`

### 3.4 Package installation controls

**What**: Prevent agents from installing arbitrary packages without approval.

**Options (choose one)**:
- **Allowlist**: Maintain a list of approved packages; reject any install of unlisted packages
- **Scan-then-install**: Every install triggers a security scan before proceeding
- **Pre-cached only**: All packages pre-installed in base image; no runtime installs allowed

**Recommended**: Pre-cached base image + scan-then-install for exceptions.

---

## Phase 4: Monitoring & Hardening (Week 5+, Ongoing)

### 4.1 Enable Dependabot security alerts

**What**: Enable GitHub Dependabot for security vulnerability alerts (NOT auto-merge).

**Config**: `.github/dependabot.yml`
```yaml
version: 2
updates:
  - package-ecosystem: "pip"
    directory: "/druppie"
    schedule:
      interval: "weekly"
    open-pull-requests-limit: 5
    labels: ["dependencies", "security-review"]

  - package-ecosystem: "npm"
    directory: "/frontend"
    schedule:
      interval: "weekly"
    open-pull-requests-limit: 5
    labels: ["dependencies", "security-review"]

  - package-ecosystem: "npm"
    directory: "/background-agents"
    schedule:
      interval: "weekly"
    open-pull-requests-limit: 5
    labels: ["dependencies", "security-review"]

  - package-ecosystem: "docker"
    directory: "/"
    schedule:
      interval: "weekly"
    labels: ["dependencies", "security-review"]
```

**CRITICAL**: Do NOT enable auto-merge. All dependency PRs require manual review.

### 4.2 Set up GitHub branch protection

**What**: Enforce that all security checks pass before merging.

**Rules for `colab-dev`**:
- Require status checks to pass (all security scan jobs)
- Require at least 1 PR review
- No force pushes
- No direct pushes (all changes via PR)

### 4.3 Evaluate Socket.dev

**What**: Trial Socket.dev for behavioral analysis of npm packages.

**Why**: Socket.dev detects suspicious package behavior (postinstall scripts, env var reads, network calls during install) that CVE databases miss. It would catch real GlassWorm-infected packages proactively.

### 4.4 Weekly security scan

**What**: Run a comprehensive security scan weekly, not just on PRs.

**GitHub Actions schedule**:
```yaml
on:
  schedule:
    - cron: '0 8 * * 1'  # Every Monday at 08:00 UTC
```

### 4.5 SLSA Level 1 provenance

**What**: Generate build provenance attestations for Docker images.

**Why**: Proves what was built, from what source, by what CI/CD system.

**How**: Use SLSA GitHub generator action.

---

## Summary: Priority Matrix

| ID | Action | Phase | Priority | Effort | Impact |
|----|--------|-------|----------|--------|--------|
| 0.1 | Verify opencode-ai status + address real CVEs | 0 | **HIGH** | Low | Clarifies threat, fixes real vulns |
| 0.2 | glassworm-hunter full scan | 0 | **HIGH** | Low | Establishes verified clean baseline |
| 0.3 | Credential rotation (precautionary) | 0 | **MEDIUM** | Medium | Good hygiene after LiteLLM exposure |
| 1.1 | Hash-pinned Python deps | 1 | **HIGH** | Medium | Prevents dependency tampering |
| 1.2 | Commit Node.js lock files | 1 | **HIGH** | Low | Deterministic builds |
| 1.3 | pip-audit in CI/CD | 1 | **HIGH** | Low | Known CVE detection |
| 1.4 | npm audit in CI/CD | 1 | **HIGH** | Low | Known CVE detection |
| 1.5 | lockfile-lint in CI/CD | 1 | **HIGH** | Low | Registry verification |
| 1.6 | Central package registry (DevPI + Verdaccio) | 1 | **HIGH** | Medium | Single source of truth, quarantine window |
| 2.1 | glassworm-hunter in CI/CD | 2 | **HIGH** | Low | GlassWorm detection |
| 2.2 | anti-trojan-source in CI/CD | 2 | **HIGH** | Low | Unicode attack detection |
| 2.3 | Pre-commit hooks | 2 | **MEDIUM** | Medium | Developer-level defense |
| 2.4 | Unicode stripping filter | 2 | **HIGH** | Medium | Agent output defense |
| 2.5 | Secret scanning | 2 | **MEDIUM** | Low | Credential leak prevention |
| 3.1 | gVisor sandbox runtime | 3 | **MEDIUM** | High | Container escape prevention |
| 3.2 | Restrict sandbox network | 3 | **MEDIUM** | Medium | Network isolation |
| 3.3 | Security gate in control plane | 3 | **HIGH** | High | Mandatory exit scanning |
| 3.4 | Package installation controls | 3 | **MEDIUM** | Medium | Prevent rogue installs |
| 4.1 | Dependabot alerts | 4 | **MEDIUM** | Low | Ongoing vulnerability tracking |
| 4.2 | Branch protection | 4 | **MEDIUM** | Low | Enforcement |
| 4.3 | Evaluate Socket.dev | 4 | **LOW** | Low | Behavioral analysis |
| 4.4 | Weekly security scan | 4 | **MEDIUM** | Low | Continuous monitoring |
| 4.5 | SLSA provenance | 4 | **LOW** | Medium | Build integrity attestation |

---

## Tools Summary

| Tool | Purpose | License | Where |
|------|---------|---------|-------|
| glassworm-hunter | GlassWorm malware detection | MIT | CI/CD, pre-scan, security gate |
| anti-trojan-source | Unicode attack detection | MIT | Pre-commit, CI/CD |
| pip-audit | Python vulnerability scanning | Apache 2.0 | CI/CD |
| pip-compile (pip-tools) | Hash-pinned requirements | BSD | Dev workflow |
| lockfile-lint | Lock file integrity | Apache 2.0 | Pre-commit, CI/CD |
| gitleaks | Secret detection | MIT | Pre-commit, CI/CD |
| npm audit | Node.js vulnerability scanning | Built-in | CI/CD |
| gVisor (runsc) | Container isolation | Apache 2.0 | Sandbox runtime |
| Socket.dev | Behavioral analysis | Commercial | CI/CD (evaluation) |
| DevPI | Internal Python package registry/proxy | MIT | All Python installs |
| Verdaccio | Internal npm package registry/proxy | MIT | All Node.js installs |
| OSV Scanner | Vulnerability scanning (existing) | Apache 2.0 | Cache scanning |
| pre-commit | Hook framework | MIT | Developer machines |

---

## Appendix: Mapping to Jeremy's Requirements

| Jeremy's Requirement | Spec Section | Phase |
|---------------------|-------------|-------|
| Opschoonactie (cleanup) | Phase 0 (all) | 0 |
| glassworm-hunter structureel integreren | 2.1 + 3.3 | 2-3 |
| Security agent scant output builder agent | 3.3 (security gate) | 3 |
| Agents in geïsoleerde container | 3.1 (gVisor) | 3 |
| Verplichte scan voordat code sandbox verlaat | 3.3 (security gate) | 3 |
| Filter dat Unicode-tekens stript | 2.4 (Unicode filter) | 2 |
| Controleren package-lock.json / requirements.txt | 1.1, 1.2, 1.5 | 1 |
| Controle over Python en npm omgevingen | 1.1-1.6, 3.4 | 1, 3 |

---

## Research Documents

For in-depth analysis, pros/cons, and alternative approaches for each topic, see the research documents in [research/](research/README.md).
