# CI/CD Security Gates and Pre-Commit Hooks

## Current State

Druppie's CI/CD is minimal:
- **GitHub Actions**: Only a `sync-main-to-colab-dev.yml` workflow (branch sync)
- **Pre-commit hooks**: Husky configured in `background-agents/` only (lint-staged)
- **No security scanning**: No dependency auditing, no Unicode detection, no vulnerability checks in CI
- **No pre-commit security hooks**: No security checks before code is committed

---

## Architecture: Two-Layer Defense

### Layer 1: Pre-Commit Hooks (Developer Machine)

**Purpose**: Catch issues at the earliest possible point, before code enters the repository.

**Requirements**:
- **Speed**: Must complete in <2 seconds (slow hooks = developers skip them)
- **Lightweight**: Only fast checks that don't need network access
- **Developer-friendly**: Clear error messages, easy to fix

**Recommended hooks**:
| Hook | Purpose | Speed |
|------|---------|-------|
| anti-trojan-source | Detect invisible Unicode characters | <0.5s |
| lockfile-lint | Verify lock file integrity | <0.5s |
| Secret detection (gitleaks) | Catch hardcoded credentials | <1s |
| Ruff (Python) | Lint + format check | <0.5s |
| ESLint (JS) | Lint check | <1s |

**NOT suitable for pre-commit** (too slow):
- pip-audit (network required)
- npm audit (network required)
- glassworm-hunter full scan (multi-second)
- Socket.dev analysis (network required)

### Layer 2: CI/CD Pipeline (Automated, Enforced)

**Purpose**: Comprehensive security scanning that cannot be bypassed by developers.

**Requirements**:
- **Comprehensive**: Run ALL security tools
- **Blocking**: PR cannot be merged if any security check fails
- **Logged**: All results stored for audit trail
- **Enforced**: Cannot be skipped without explicit security team approval

**Recommended CI checks**:
| Check | Purpose | Runtime |
|-------|---------|---------|
| pip-audit | Python vulnerability scanning | ~10s |
| npm audit | Node.js vulnerability scanning | ~5s |
| glassworm-hunter | GlassWorm malware detection | ~15s |
| anti-trojan-source | Unicode attack detection | ~5s |
| lockfile-lint | Lock file integrity | ~1s |
| Hash verification | Verify dependency hashes match | ~5s |
| SBOM generation | Software Bill of Materials | ~10s |
| Secret scanning | Detect leaked credentials | ~5s |

---

## Implementation: Pre-Commit Hooks

### Option A: Husky + lint-staged (Already Partial)

`background-agents/` already uses Husky. Extend to the root project.

```json
// package.json (root)
{
  "devDependencies": {
    "husky": "^9.0.0",
    "lint-staged": "^16.0.0"
  },
  "lint-staged": {
    "*.{js,jsx,ts,tsx}": ["npx anti-trojan-source --files"],
    "*.py": ["ruff check", "python -m anti_trojan_source"],
    "package-lock.json": ["npx lockfile-lint --path package-lock.json --type npm --allowed-hosts npm --validate-https"]
  }
}
```

**Pros**: Already partially set up, familiar tooling, fast
**Cons**: Node.js-centric, requires npm for Python projects

### Option B: pre-commit Framework (Python-based)

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/lirantal/anti-trojan-source
    rev: v1.0.0
    hooks:
      - id: anti-trojan-source
        types: [text]

  - repo: https://github.com/gitleaks/gitleaks
    rev: v8.18.0
    hooks:
      - id: gitleaks

  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.4.0
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format

  - repo: local
    hooks:
      - id: lockfile-lint
        name: lockfile-lint
        entry: npx lockfile-lint --path frontend/package-lock.json --type npm --allowed-hosts npm --validate-https
        language: system
        files: package-lock\.json$
        pass_filenames: false
```

**Pros**: Language-agnostic, well-established framework, manages hook versions
**Cons**: Requires Python, additional tool to install

### Recommendation: pre-commit Framework

The `pre-commit` framework is more suitable because:
1. Druppie is primarily a Python project
2. Supports both Python and JavaScript hooks
3. Manages hook versions automatically
4. Well-established with good ecosystem of hooks
5. Can run anti-trojan-source, gitleaks, ruff, and custom hooks

---

## Implementation: CI/CD Pipeline

### GitHub Actions Workflow

```yaml
# .github/workflows/security-scan.yml
name: Security Scan

on:
  pull_request:
    branches: [colab-dev, main]
  push:
    branches: [colab-dev]

jobs:
  dependency-audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Set up Node.js
        uses: actions/setup-node@v4
        with:
          node-version: '20'

      # Python dependency audit
      - name: Install pip-audit
        run: pip install pip-audit

      - name: Audit Python dependencies
        run: pip-audit -r druppie/requirements.txt

      # Node.js dependency audit
      - name: Audit npm dependencies (frontend)
        working-directory: frontend
        run: npm audit --audit-level=high

      - name: Audit npm dependencies (background-agents)
        working-directory: background-agents
        run: npm audit --audit-level=high

  malware-scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      # GlassWorm scanner
      - name: Install glassworm-hunter
        run: pip install glassworm-hunter

      - name: Run GlassWorm scan
        run: glassworm-hunter scan --path .

      # Unicode attack detection
      - name: Install anti-trojan-source
        run: npm install -g anti-trojan-source

      - name: Scan for Unicode attacks
        run: npx anti-trojan-source --files "**/*.{py,js,jsx,ts,tsx,json,yaml,yml}"

  lockfile-integrity:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Verify frontend lockfile
        run: npx lockfile-lint --path frontend/package-lock.json --type npm --allowed-hosts npm --validate-https

      - name: Verify background-agents lockfile
        run: npx lockfile-lint --path background-agents/package-lock.json --type npm --allowed-hosts npm --validate-https

  secret-scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0  # Full history for secret scanning

      - name: Run Gitleaks
        uses: gitleaks/gitleaks-action@v2
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

### Branch Protection Rules

Configure on GitHub:
- **Require status checks**: All security scan jobs must pass
- **Require PR reviews**: At least 1 reviewer
- **Require review from security team**: For dependency changes
- **No force pushes**: Prevent overwriting protected branches
- **Require signed commits**: Optional but recommended

---

## Tool-by-Tool Analysis

### gitleaks (Secret Detection)

**What it does**: Scans git history and current files for hardcoded secrets (API keys, passwords, tokens)

**Pros**:
- Catches credentials before they're pushed
- Scans git history (not just current files)
- Configurable rules for custom patterns
- Fast execution

**Cons**:
- False positives with test fixtures
- Doesn't catch secrets in .env files (which should be gitignored anyway)

**Verdict**: Must-have. Prevents the credential theft that enables supply chain attacks like GlassWorm's self-propagation.

### SBOM Generation (CycloneDX / SPDX)

**What it does**: Generates a Software Bill of Materials listing all components, versions, and licenses

**Pros**:
- Audit trail of exactly what's in each build
- Required by some compliance frameworks
- Enables post-hoc vulnerability analysis

**Cons**:
- Doesn't prevent attacks (documentation only)
- Adds build time
- Requires tooling to consume SBOMs

**Verdict**: Nice-to-have for compliance. Lower priority than active scanning tools.

---

## Performance Budget

Total pre-commit hook time should be <3 seconds:

| Hook | Budget |
|------|--------|
| anti-trojan-source | 0.5s |
| lockfile-lint | 0.3s |
| gitleaks | 1.0s |
| ruff | 0.5s |
| ESLint | 0.7s |
| **Total** | **3.0s** |

Total CI pipeline time should be <2 minutes:

| Job | Budget | Parallelizable |
|-----|--------|----------------|
| pip-audit | 15s | Yes |
| npm audit | 10s | Yes |
| glassworm-hunter | 20s | Yes |
| anti-trojan-source | 10s | Yes |
| lockfile-lint | 3s | Yes |
| gitleaks | 15s | Yes |
| **Total (parallel)** | **~20s** | All jobs run in parallel |
