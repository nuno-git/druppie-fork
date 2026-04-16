# Python Supply Chain Security

## Current State in Druppie

Druppie's Python dependencies are managed via `requirements.txt` files:
- **Main backend**: `/druppie/requirements.txt` (43 dependencies, version ranges like `>=`)
- **MCP servers**: Each has its own minimal `requirements.txt`
- **Sandbox image**: Additional Python packages in `Dockerfile.sandbox`
- **No lock files**: No `Pipfile.lock`, `poetry.lock`, or `pip-compile` output with hashes
- **No hash verification**: Dependencies installed without `--require-hashes`

This means any `pip install` can silently pull different (potentially compromised) versions of transitive dependencies.

---

## Approach 1: pip-compile with Hash Verification

### How It Works
Use `pip-tools` (or `uv pip compile`) to resolve the full dependency tree and generate a `requirements.txt` with pinned versions AND cryptographic hashes for every package (including transitive dependencies).

```bash
# Generate locked requirements with hashes
pip-compile --generate-hashes requirements.in -o requirements.txt

# Install with hash verification
pip install --require-hashes -r requirements.txt
```

### Pros
- **Deterministic builds**: Every install gets exactly the same packages
- **Tamper detection**: Hash mismatch = immediate failure, catches compromised packages
- **Covers transitive deps**: Hashes for ALL packages, not just direct dependencies
- **No new tooling**: Uses standard pip, just with stricter settings
- **Low complexity**: Easy to understand and implement
- **uv compatible**: `uv pip compile --generate-hashes` is even faster

### Cons
- **Update friction**: Every dependency update requires re-running pip-compile
- **Hash management**: Adding a single package means recalculating all hashes
- **Multi-platform**: Hashes may differ per platform (wheels vs sdist)
- **No vulnerability database**: Only verifies integrity, not whether a package has known CVEs

### Verdict
**Strongly recommended as baseline.** This is the single most impactful change for preventing supply chain attacks on the Python side.

---

## Approach 2: pip-audit (Vulnerability Scanning)

### How It Works
PyPA's official tool that audits Python environments against known vulnerabilities. Checks the OSV database (Google's Open Source Vulnerabilities).

```bash
pip-audit                           # Audit current environment
pip-audit -r requirements.txt       # Audit from requirements file
pip-audit --fix                     # Auto-fix where possible
```

### Pros
- **Official PyPA tool**: Maintained by Python Packaging Authority with Google support
- **Comprehensive database**: Uses OSV, which aggregates multiple vulnerability sources
- **CI/CD integration**: Easy to add as a pipeline step
- **Auto-fix**: Can suggest/apply version bumps for vulnerable packages
- **Fast**: Typically completes in seconds

### Cons
- **Reactive only**: Only catches KNOWN vulnerabilities already in the database
- **Zero-day blind**: A newly compromised package won't be flagged until reported
- **Single database**: OSV is comprehensive but not exhaustive
- **No malware detection**: Doesn't detect hidden Unicode, suspicious behavior, etc.

### Verdict
**Recommended as complementary tool.** Use alongside hash verification - pip-audit catches known CVEs, hashes catch tampering.

---

## Approach 3: Safety (Alternative Vulnerability Scanner)

### How It Works
Commercial tool (free for open-source) that checks installed packages against the Safety DB (curated vulnerability database).

### Pros
- **Curated database**: Human-reviewed vulnerability entries
- **Different coverage**: Catches some vulns that OSV misses and vice versa
- **License checking**: Also flags problematic licenses

### Cons
- **Commercial**: Full features require paid license
- **Overlap with pip-audit**: Significant overlap in coverage
- **Slower updates**: Database updates may lag behind OSV

### Verdict
**Optional.** pip-audit is sufficient for most cases, but running both provides broader coverage if budget allows.

---

## Approach 4: Private PyPI Registry (DevPI)

### How It Works
Run an internal PyPI mirror/proxy that caches packages from the public PyPI. All developers and CI/CD pull from the internal registry instead of directly from PyPI.

```bash
# Install and run DevPI
pip install devpi-server devpi-client
devpi-server --start --init

# Configure pip to use internal registry
pip config set global.index-url http://devpi.internal/root/pypi/+simple/
```

### Pros
- **Caching layer**: Packages are cached locally after first download
- **Offline availability**: Builds work even if PyPI is down
- **Quarantine window**: Can delay mirroring new packages (e.g., 24h) to let malicious packages be caught first
- **Package allowlisting**: Can restrict which packages are available
- **Free and open-source**: DevPI is fully open-source

### Cons
- **Infrastructure overhead**: Need to host, maintain, and back up the registry
- **Not a security tool per se**: Still pulls from PyPI, just adds a caching layer
- **Configuration management**: All developers and CI/CD must be configured to use it
- **Delay trade-off**: Quarantine delays slow down legitimate package updates too

### Comparison: DevPI vs Artifactory vs Nexus

| Feature | DevPI | Artifactory | Nexus |
|---------|-------|-------------|-------|
| Cost | Free (OSS) | $150-800/mo | $135+/mo |
| Setup complexity | Low | High | High |
| Multi-format | Python only | All formats | All formats |
| Enterprise features | Basic | Full | Full |
| Best for | Small teams, Python-only | Enterprise, multi-language | Enterprise, multi-language |

### Verdict
**Recommended for medium-term.** Provides a meaningful security layer (quarantine window, caching) at low cost. DevPI is sufficient for our Python-focused needs.

---

## Approach 5: Poetry / Pipenv Lock Files

### How It Works
Use a dependency manager that generates lock files with cryptographic hashes automatically.

**Poetry:**
```bash
poetry lock                     # Generate poetry.lock with hashes
poetry install --no-root        # Install from lock file
```

**Pipenv:**
```bash
pipenv lock                     # Generate Pipfile.lock with hashes
pipenv install --deploy         # Fail if lock file out of sync
pipenv verify                   # Verify lock file integrity
```

### Pros
- **Automatic hashing**: Lock files include hashes by default
- **Dependency resolution**: Proper resolver catches conflicts
- **Developer experience**: Better than manual pip-compile for daily use
- **Lock file verification**: Built-in commands to check integrity

### Cons
- **Migration effort**: Requires converting all requirements.txt to pyproject.toml/Pipfile
- **Tooling change**: Team needs to learn new workflow
- **Docker integration**: Requires adjusting Dockerfiles
- **Poetry quirks**: Some edge cases with private packages and extras

### Verdict
**Consider for long-term.** pip-compile is easier to adopt now; Poetry/Pipenv are better if starting fresh or during a major refactor.

---

## Approach 6: Delay-Based Protection (--exclude-newer)

### How It Works
When resolving dependencies, exclude packages published after a certain date. This gives the community time to discover and report malicious packages.

```bash
# Only install packages published at least 7 days ago
uv pip compile --exclude-newer "2026-04-09" requirements.in
```

### Pros
- **Zero-day buffer**: Malicious packages are often caught within hours/days
- **No infrastructure needed**: Just a flag on the existing tool
- **The LiteLLM attack was live for ~40 minutes**: This approach would have caught it

### Cons
- **Delays legitimate updates**: Security patches are also delayed
- **Not available in standard pip**: Requires `uv` 
- **Manual date management**: Need to update the date periodically

### Verdict
**Recommended for CI/CD builds.** Use a 7-day delay in production builds. Developer environments can use latest.

---

## Recommended Combination for Druppie

| Layer | Tool | Purpose |
|-------|------|---------|
| **Lock & Hash** | `pip-compile --generate-hashes` | Deterministic builds + tamper detection |
| **Vulnerability Scan** | `pip-audit` | Known CVE detection |
| **CI/CD Gate** | `pip install --require-hashes` | Enforce hash verification |
| **Build Delay** | `uv pip compile --exclude-newer` | Zero-day buffer for production |
| **Registry** (medium-term) | DevPI | Caching + quarantine window |

This layered approach addresses: tampering (hashes), known vulnerabilities (pip-audit), zero-days (delay), and availability (DevPI cache).
