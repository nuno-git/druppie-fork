# SLSA Framework and Package Signing (Sigstore/Cosign)

## Overview

These are industry frameworks for ensuring software supply chain integrity at the build and distribution level. While the other research documents focus on detecting malicious dependencies, SLSA and Sigstore focus on proving that YOUR builds haven't been tampered with.

## SLSA (Supply-chain Levels for Software Artifacts)

### What Is SLSA?

An OpenSSF security standard (currently v1.1, April 2025) that defines progressive levels of supply chain security. Think of it as a maturity model for build integrity.

### SLSA Levels

| Level | Name | Requirements | What It Proves |
|-------|------|-------------|----------------|
| SLSA 0 | None | No controls | Nothing |
| SLSA 1 | Provenance | Build recorded, basic traceability | Someone built this, somewhere |
| SLSA 2 | Build Integrity | Hosted build platform, tamper-resistant, provenance attestation | A specific CI/CD system built this, and the build wasn't modified |
| SLSA 3 | Strong Controls | Hermetic builds, source control requirements, dependency pinning | This was built from exactly this source, with exactly these dependencies, in an isolated environment |

### Relevance to Druppie

| Aspect | Current State | SLSA Implication |
|--------|--------------|-----------------|
| Build system | Docker compose (local) | No provenance - anyone can build anything |
| CI/CD | Minimal (branch sync only) | No build attestation |
| Dependencies | Unpinned ranges | Not hermetic (different builds get different deps) |
| Source control | GitHub + Gitea | Good, but no signed commits |

### Pros of Adopting SLSA
- **Industry standard**: Increasingly required by enterprise customers and compliance frameworks
- **Systematic approach**: Forces good practices (pinning, CI/CD, provenance)
- **Progressive**: Can adopt incrementally (Level 1 → 2 → 3)
- **Framework, not tooling**: Works with existing CI/CD (GitHub Actions, etc.)

### Cons
- **Process overhead**: Requires changing how builds are done
- **Complexity**: Level 3 (hermetic builds) is significantly complex
- **Not directly protective**: A framework for proving integrity, not detecting attacks
- **Overkill for current stage**: Druppie is an internal platform, not a public software product

### Verdict
**SLSA Level 2 is a reasonable medium-term goal.** Level 1 we can achieve almost immediately by adding build provenance to our GitHub Actions. Level 3 is aspirational and not needed for our current threat model.

### What SLSA Level 2 Requires for Us
1. Build on a hosted platform (GitHub Actions - already there if we add build workflows)
2. Generate provenance attestation (what was built, from what source, with what deps)
3. Tamper-resistant build logs
4. All achievable with GitHub Actions + SLSA GitHub generator

---

## Sigstore / Cosign (Package Signing)

### What Is Sigstore?

An open-source project for code signing and verification. Cosign is the signing tool for container images and artifacts. The key innovation: **keyless signing** - no private keys to manage.

### How Cosign Works

1. Developer/CI runs `cosign sign` on a container image
2. Cosign creates an ephemeral key pair (in memory only)
3. Developer authenticates via OIDC (GitHub, Google, etc.)
4. Sigstore CA (Fulcio) issues a short-lived certificate tied to the identity
5. Signature is recorded in a tamper-proof transparency log (Rekor)
6. Key pair is destroyed - only the identity-based certificate remains

**Verification:**
```bash
cosign verify --certificate-identity=user@example.com \
  --certificate-oidc-issuer=https://github.com/login/oauth \
  ghcr.io/our-org/druppie-backend:latest
```

### Pros
- **Keyless**: No private keys to manage, rotate, or potentially leak
- **Identity-based**: "This image was signed by this GitHub user" (not "by whoever had this key")
- **Transparent**: All signatures recorded in public log (Rekor) - tamper-evident
- **Growing ecosystem**: PyPI (Nov 2024), Maven Central (Jan 2025), Homebrew already support it
- **GitHub Actions integration**: Easy to add cosign to CI/CD pipelines
- **Free**: Fully open-source, public infrastructure

### Cons
- **Container-focused**: Primarily designed for container images (though supports other artifacts)
- **OIDC dependency**: Requires identity provider integration
- **Complexity**: Understanding certificate chains, transparency logs is non-trivial
- **Verification burden**: Consumers must verify signatures (not enforced by default)
- **Ecosystem maturity**: Still early for some package managers

### Relevance to Druppie

Druppie builds multiple Docker images:
- `druppie-backend`
- `druppie-frontend`
- MCP server images (module-coding, module-docker, etc.)
- Sandbox base image

Signing these images would prove:
- The image was built by our CI/CD (not a compromised developer machine)
- The image hasn't been modified after build
- Exactly who/what triggered the build

### Verdict
**Recommended for medium-to-long term.** Not urgent (we're not distributing images externally), but good practice and required for SLSA Level 2+ compliance.

---

## Comparison: What Solves What

| Problem | SLSA | Sigstore/Cosign | Other Tools |
|---------|------|-----------------|-------------|
| Compromised dependency | Level 3 (hermetic builds) | No | pip-audit, npm audit, glassworm-hunter |
| Tampered build output | Level 2+ (provenance) | **Yes** (signed images) | - |
| Compromised CI/CD | Level 3 (isolated builds) | Partially (proves identity) | Token rotation, MFA |
| Untrusted images | No | **Yes** (verification) | - |
| Audit trail | Level 1+ (provenance) | **Yes** (transparency log) | SBOM |
| Malicious maintainer | No | No | Socket.dev, behavioral analysis |

## Prioritization for Druppie

| Priority | Action | Effort | Impact |
|----------|--------|--------|--------|
| P3 | SLSA Level 1 (build provenance) | Low | Documentation/audit value |
| P3 | Cosign for Docker images | Medium | Proves image integrity |
| P4 | SLSA Level 2 (hosted build + attestation) | Medium | Full build traceability |
| P5 | SLSA Level 3 (hermetic builds) | High | Maximum integrity guarantee |

These are lower priority than the P0-P2 items in other documents because they address "proving integrity" rather than "detecting/preventing attacks." Get the detection and prevention right first, then add provenance and signing.
