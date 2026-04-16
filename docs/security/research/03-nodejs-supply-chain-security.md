# Node.js Supply Chain Security

## Current State in Druppie

Druppie has two Node.js components:
- **Frontend**: React/Vite app (`/frontend/package.json`) - package-lock.json is NOT committed (in .gitignore)
- **Background agents**: Sandbox infrastructure (`/background-agents/package.json`) - package-lock.json IS committed

Key risks:
- Frontend builds are non-deterministic (no lock file in VCS)
- No dependency scanning in CI/CD
- No lockfile integrity verification
- Sandbox image installs npm packages globally without verification

---

## Approach 1: Lock File Integrity (npm ci + Committed Lock Files)

### How It Works
Commit `package-lock.json` to version control and use `npm ci` (clean install) in all builds. `npm ci` fails if the lock file doesn't match `package.json` and verifies SHA-512 hashes of all downloaded packages.

```bash
# In CI/CD and Docker builds - ALWAYS use npm ci
npm ci --frozen-lockfile

# NEVER use npm install in CI/CD (it can modify the lock file)
```

### Pros
- **Deterministic builds**: Every build gets exactly the same packages
- **Hash verification**: npm ci verifies SHA-512 integrity hashes from lock file
- **Tamper detection**: Modified packages = hash mismatch = build failure
- **Zero effort**: Just commit the lock file and use npm ci
- **Already works**: No new tools needed

### Cons
- **Lock file bloat**: package-lock.json can be large and create merge conflicts
- **Requires discipline**: Developers must not use `npm install` in CI

### Verdict
**Must-do, immediately.** The frontend's package-lock.json MUST be committed. This is the single most impactful Node.js security change.

---

## Approach 2: npm audit (Built-in Vulnerability Scanning)

### How It Works
Built into npm, checks all dependencies against the npm advisory database for known CVEs.

```bash
npm audit                    # Show vulnerabilities
npm audit --audit-level=high # Fail on high+ severity only
npm audit fix                # Auto-fix where possible
```

### Pros
- **Zero setup**: Already available with npm
- **Comprehensive database**: npm advisory database is well-maintained
- **CI/CD integration**: One-line addition to pipeline

### Cons
- **Known CVEs only**: Cannot detect malware, suspicious behavior, or zero-days
- **False positives**: Dev dependencies often show vulns that don't affect production
- **No malware detection**: Won't catch GlassWorm-type attacks

### Verdict
**Recommended as baseline.** Free, easy, catches the obvious stuff. Not sufficient alone.

---

## Approach 3: Socket.dev (Behavioral Analysis)

### How It Works
Analyzes packages for suspicious runtime behavior rather than just known CVEs. Detects:
- Network access during install
- Environment variable reads
- Filesystem access to sensitive paths
- Obfuscated or minified code in source packages
- Install scripts with suspicious patterns

### Pros
- **Catches unknown threats**: Behavioral analysis detects malware not yet in CVE databases
- **Would have caught GlassWorm**: Hidden Unicode + postinstall network access = flagged
- **Real-time blocking**: Can block malicious packages before installation
- **GitHub integration**: Reviews PRs for dependency changes

### Cons
- **Commercial tool**: Requires subscription for full features
- **False positives**: Legitimate packages that read env vars or make network calls get flagged
- **Newer tool**: Less track record than Snyk

### Verdict
**Strongly recommended.** Behavioral analysis is the gap that npm audit cannot fill. This is what would have caught the opencode-ai infection early.

---

## Approach 4: Snyk (Comprehensive Security Platform)

### How It Works
Commercial security platform that provides vulnerability scanning, fix guidance, and continuous monitoring for npm dependencies.

### Pros
- **Larger vulnerability database**: Covers more CVEs than npm advisory alone
- **Fix guidance**: Suggests specific version bumps to resolve vulnerabilities
- **Container scanning**: Can also scan Docker images
- **License compliance**: Flags problematic licenses

### Cons
- **Commercial**: Free tier is limited, full features require subscription
- **Overlap with npm audit**: Much of the same coverage
- **No behavioral analysis**: Still CVE-based, doesn't detect unknown malware

### Comparison: npm audit vs Snyk vs Socket.dev

| Feature | npm audit | Snyk | Socket.dev |
|---------|-----------|------|------------|
| Cost | Free | Freemium | Freemium |
| Known CVEs | Good | Better | Good |
| Unknown malware | No | No | **Yes** |
| Behavioral analysis | No | No | **Yes** |
| Fix guidance | Basic | Advanced | Basic |
| Container scanning | No | Yes | No |
| Would catch GlassWorm | No | No | **Yes** |

### Verdict
**Socket.dev preferred over Snyk** for our threat model. GlassWorm-type attacks are our primary concern, and behavioral analysis is what catches them.

---

## Approach 5: lockfile-lint (Lock File Policy Enforcement)

### How It Works
Validates that lock files conform to security policies: verifying that all packages resolve to expected registries and use HTTPS.

```bash
npx lockfile-lint \
  --path package-lock.json \
  --type npm \
  --allowed-hosts npm \
  --validate-https \
  --validate-package-names
```

### Pros
- **Registry verification**: Ensures all packages come from npmjs.org (not malicious mirrors)
- **HTTPS enforcement**: Prevents MITM during package download
- **Package name validation**: Catches typosquatting in lock files
- **Fast**: Runs in milliseconds
- **Pre-commit hook compatible**: No CI/CD delay

### Cons
- **Narrow scope**: Only validates lock file format/sources, not package contents
- **Configuration needed**: Requires setting up policies
- **npm-focused**: Primary support for npm and Yarn

### Verdict
**Recommended for CI/CD.** Low-cost, fast check that catches lock file manipulation attacks. Complements npm audit and Socket.dev.

---

## Approach 6: Disable npm Scripts (ignore-scripts)

### How It Works
Prevent lifecycle scripts (preinstall, postinstall, etc.) from running during package installation.

```bash
# Global config
npm config set ignore-scripts true

# Per-install
npm install --ignore-scripts

# In .npmrc
ignore-scripts=true
```

### Pros
- **Blocks postinstall payloads**: GlassWorm's primary execution vector is postinstall scripts
- **Simple to enable**: One config change
- **Defense in depth**: Even if a malicious package is installed, it can't auto-execute

### Cons
- **CRITICAL: Bypasses exist** (discovered early 2026): Six zero-day vulnerabilities in npm, pnpm, vlt, and Bun allow bypassing ignore-scripts
- **Breaks legitimate packages**: Some packages require postinstall scripts to function (e.g., native modules, Playwright browser downloads)
- **npm's stance**: "Works as expected" - not treating bypasses as bugs
- **False sense of security**: Cannot be sole defense

### Verdict
**Use as defense-in-depth, but do NOT rely on it.** Enable where possible (CI/CD builds), but acknowledge it's bypassable. Always combine with other measures.

---

## Approach 7: Verdaccio Private Registry

### How It Works
Self-hosted npm registry that proxies npmjs.org and caches packages locally.

### Pros
- **Caching**: Faster installs, offline availability
- **Quarantine**: Can delay mirroring new package versions
- **Private packages**: Host internal packages alongside public ones
- **Free and open-source**: No licensing costs

### Cons
- **Infrastructure overhead**: Need to host and maintain
- **Not a security scanner**: Still serves whatever npmjs.org has
- **Configuration**: All developers/CI must point to internal registry

### Verdict
**Consider for medium-term** if also using DevPI for Python. One private registry for each ecosystem provides consistent caching and quarantine.

---

## Recommended Combination for Druppie

| Priority | Action | Purpose |
|----------|--------|---------|
| **P0** | Commit frontend package-lock.json | Deterministic builds |
| **P0** | Use `npm ci` in all Dockerfiles and CI | Hash verification |
| **P1** | Add `npm audit` to CI/CD | Known CVE detection |
| **P1** | Add lockfile-lint to CI/CD | Registry and HTTPS verification |
| **P1** | Evaluate Socket.dev | Behavioral malware detection |
| **P2** | Set `ignore-scripts=true` in CI .npmrc | Defense-in-depth (with caveats) |
| **P3** | Consider Verdaccio | Caching + quarantine |
