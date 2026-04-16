# Developer Environment & Device Security

## Context

Beyond supply chain security in code, we need to secure the environments where code is written, tested, and deployed. This is especially important given:
- We are a waterschap (water authority) - classified as **essential entity** under NIS2
- BIO2 v1.3 (effective March 2026) mandates specific device and development security controls
- The recent supply chain incidents highlight that developer machines are a primary attack vector

This document covers device management, environment standardization, credential management, network security, and how these map to our compliance obligations.

---

## 1. Compliance Landscape (What's Mandatory)

### BIO2 (Baseline Informatiebeveiliging Overheid)

BIO2 v1.3 became effective March 5, 2026 as mandatory self-regulation for all waterschappen. Key controls relevant to developer environments:

| BIO2 Control | Requirement | What It Means For Us |
|-------------|-------------|---------------------|
| 5.16.02 | No shared/group accounts without CISO approval | Each developer gets personal accounts for all systems |
| 5.17.01 | MFA mandatory for primary logon, internet-accessible systems, privileged accounts | MFA everywhere, no exceptions |
| 5.17.02 | Password manager provided to all staff | Must provide team-wide password manager |
| 5.18.01 | Unauthorized privileged account creation = security incident | Strict access provisioning process |
| 5.18.02 | Access rights reviewed annually minimum | Annual access audit |
| 8.01.01 | "Zero footprint" for mobile devices (no local business data) | Dev environments should minimize local data |
| 8.01.02 | MDM/MAM, patch management, device hardening mandatory | All dev devices under MDM |
| 8.19.01 | Unauthorized software installation risk managed | Control what developers can install |
| 8.21.01-04 | Network monitoring, encryption for wireless/external | Network security controls |
| 8.22.01 | Network segments with defined security levels | Segment dev from production |
| 8.27.01 | Security by design and security by default | Baked into our SDLC |
| 8.29.01 | Structured testing, automated where possible | Automated security testing in CI/CD |

**ENSIA**: Waterschappen report BIO compliance via ENSIA annually. Self-evaluation runs July-December, final reports due April 30.

### NIS2 / Cyberbeveiligingswet (Cbw)

The Dutch implementation (Cyberbeveiligingswet) is expected Q2 2026. As a waterschap, we are an **essential entity** (highest tier).

| NIS2 Article | Requirement | Practical Impact |
|-------------|-------------|-----------------|
| Art. 21.2.d | Supply chain security | Dependency scanning, SBOM generation, vulnerability monitoring |
| Art. 21.2.e | Security in development and maintenance | Code scanning (SAST/DAST), secret scanning, signed commits, protected branches |
| Incident reporting | 24h initial alert → 72h update → 1 month final report to NCSC-NL | Must have incident response plan ready |

**Penalties**: Up to EUR 10 million or 2% global turnover for essential entities. Public bodies face corrective orders and reputational consequences.

### EU AI Act

Since we're building an AI governance platform as a public authority:
- From **August 2, 2026**: Must register high-risk AI deployments in EU database
- **Fundamental rights impact assessment** (FRIA) required before deploying high-risk AI
- Autoriteit Persoonsgegevens (AP) is the designated AI Act market supervisor

### Cloud Sovereignty (New, 2025-2026)

Dutch parliament passed motions in March 2025 declaring US cloud dependency "a threat to autonomy and cybersecurity." New migrations to US cloud providers are paused for government. A sovereign cloud initiative is being developed by the Cloud Acceleration Team, expected by end 2026.

**Impact**: Avoid new dependencies on US cloud services. Existing Microsoft deployments are not immediately revoked but prepare for potential transition.

---

## 2. Device Management (Endpoint Security)

### What's Standard in Dutch Government

The Dutch government overwhelmingly uses the Microsoft ecosystem. The typical waterschap endpoint stack:

| Component | Tool | Purpose |
|-----------|------|---------|
| MDM/UEM | **Microsoft Intune** | Device management, compliance policies, app management |
| EDR/XDR | **Microsoft Defender for Endpoint** | Threat detection and response |
| Identity | **Microsoft Entra ID** (Azure AD) | SSO, conditional access, MFA |
| Disk Encryption | **BitLocker** (Windows) / **FileVault** (macOS) | Full disk encryption, enforced via MDM |
| Provisioning | **Windows Autopilot** | Zero-touch device setup |

This stack maps well to BIO2 controls and is already approved/contracted via SLM Rijk framework agreements.

### BYOD vs Company-Managed

BIO2's "zero footprint" requirement (8.01.01) effectively rules out unmanaged BYOD for developer work. Options:

| Approach | BIO2 Compliant? | Practical For Devs? |
|----------|-----------------|---------------------|
| **Company-owned, Intune-managed** | Yes | Yes - standard approach |
| **BYOD with Intune MAM** | Partially (data containerization) | Limited - can't enforce disk encryption, patching |
| **Cloud dev environments (Codespaces)** | Yes (zero footprint by design) | Yes - no code on local device |

**Recommendation**: Company-owned devices managed via Intune. For developers who need Linux, use cloud development environments or VMs within managed devices.

### Device Hardening Checklist

Based on BIO2 and NCSC guidance:

- [ ] Full disk encryption (BitLocker/FileVault) enforced via MDM
- [ ] OS auto-updates enabled, max 7-day deferral for critical patches
- [ ] Defender for Endpoint installed and reporting
- [ ] Screen lock after 5 minutes inactivity
- [ ] Local admin rights: limited (see below)
- [ ] MFA required for all logins (Entra ID conditional access)
- [ ] VPN/ZTNA for accessing internal resources
- [ ] Remote wipe capability enabled

### The Admin Rights Question

Developers typically need more system access than regular office workers. Balancing BIO2 (8.19.01 - manage unauthorized software) with developer productivity:

**Option A: No local admin** (strictest)
- All software installed via Intune Company Portal
- Developers request packages through IT
- **Pro**: Maximum control, BIO2 compliance clear
- **Con**: Massive friction, developers will find workarounds

**Option B: Separate admin account** (pragmatic)
- Standard account for daily use (email, browsing)
- Separate admin account for development (installing packages, Docker, etc.)
- UAC prompts require admin credentials
- **Pro**: Balance of security and productivity
- **Con**: Some developers will just stay logged in as admin

**Option C: Cloud dev environments** (modern)
- Local machine is a thin client with no dev tooling
- All development happens in GitHub Codespaces, Coder, or similar
- Local machine only needs browser + SSH client
- **Pro**: True zero footprint, no admin rights needed
- **Con**: Latency, cost, requires reliable internet

**Recommendation**: Option B for now (separate admin account with Intune compliance monitoring). Evaluate Option C (cloud dev environments) as a medium-term goal - it's the cleanest solution for BIO2 compliance.

---

## 3. Developer Environment Standardization

### Dev Containers (Recommended)

Define development environments as code using `.devcontainer/devcontainer.json` in each repository. Every developer gets the exact same toolchain, extensions, security configs, and dependencies.

```
.devcontainer/
  devcontainer.json      # Environment definition
  Dockerfile             # Custom container image
  post-create.sh         # Setup scripts (pre-commit hooks, etc.)
```

**Pros**:
- "Works on my machine" disappears
- Security tools (pre-commit hooks, linters, scanners) baked in
- New developer onboarding: minutes instead of days
- Satisfies BIO2 8.27.01 (security by design)
- Works locally (VS Code) or in cloud (GitHub Codespaces)

**Cons**:
- Docker required on developer machines
- Some overhead on local machines

**Recommendation**: Implement devcontainers for all repositories. This is the highest-impact change for both security and developer experience.

### Cloud Development Environments

| Platform | Cost | Government-Friendly? | Notes |
|----------|------|---------------------|-------|
| **GitHub Codespaces** | Free 60 hrs/mo; $4/user/mo + compute | Yes (GitHub Enterprise has government customers) | US-hosted (cloud sovereignty concern) |
| **Coder** (self-hosted) | Free open-source core | **Best fit** - self-hosted, data stays on our infra | Full control, no US cloud dependency |
| **Gitpod/Ona** | $20-36/user/mo | Partial (EU hosting available) | Less control than self-hosted |

**Recommendation**: Evaluate **Coder** (self-hosted, open-source). It satisfies zero-footprint (BIO2 8.01.01), avoids US cloud dependency (sovereignty), and keeps all code on our own infrastructure. Can run on our existing Docker infrastructure.

---

## 4. Credential & Secret Management

### What BIO2 Requires
- MFA mandatory (5.17.01)
- Password manager for all staff (5.17.02)
- No shared accounts (5.16.02)
- Annual access review (5.18.02)

### Recommended Stack

| Layer | Tool | Purpose | Cost |
|-------|------|---------|------|
| **Password manager** | **1Password Business** or **Bitwarden** | Team password vault, SSH key storage | $4-8/user/mo |
| **Application secrets** | **Doppler** or **Infisical** (self-hosted) | Env vars for dev/staging/prod, CI/CD injection | Free-$6/user/mo |
| **Hardware tokens** | **YubiKey 5 series** | Phishing-resistant MFA, SSH signing, Git commit signing | ~$75/key one-time |

### Hardware Security Keys (YubiKey)

**Strongly recommended**. At ~$75 per key (buy 2 per developer: primary + backup), this is the highest-ROI security investment:

- **SSH authentication**: FIDO2-backed SSH keys stored on hardware (`ssh-keygen -t ed25519-sk`)
- **Git commit signing**: Physical touch required for each signature
- **MFA for everything**: GitHub, Entra ID, 1Password, cloud providers
- **Phishing-proof**: Cannot be phished (unlike TOTP or push notifications)
- **BIO2 5.17.01 compliance**: Strongest form of MFA

**Total cost for 10 developers**: ~$1,500 one-time. Compare to cost of one credential theft incident.

### Git Commit Signing Enforcement

1. Each developer generates SSH signing key on YubiKey
2. Upload public keys to GitHub
3. Enable branch protection: require signed commits on `colab-dev` and `main`
4. This proves authorship - a compromised account can't sign without the physical key
5. Maps to NIS2 Art. 21.2.e (integrity of development lifecycle)

### Short-Lived Credentials

Replace long-lived tokens wherever possible:

| Current | Better | Best |
|---------|--------|------|
| Long-lived API keys in .env | Secrets manager with rotation | OIDC federation (no stored credentials) |
| Permanent GitHub tokens | Fine-grained tokens with expiry | GitHub App installation tokens (1hr TTL) |
| Static database passwords | Rotated via secrets manager | Dynamic credentials via Vault (TTL-based) |

---

## 5. Network Security

### Zero Trust Network Access (Recommended over VPN)

BIO2 explicitly references zero trust as an architectural principle. Traditional VPN is being replaced:

| Solution | Cost | Fit for Government |
|----------|------|-------------------|
| **Tailscale** | Free personal; $5/user/mo teams | Good - peer-to-peer, no central server, WireGuard-based |
| **Cloudflare Access** | Free up to 50 users | Good for web apps - but routes through Cloudflare (US company, sovereignty concern) |
| **ZScaler** | Enterprise pricing | Common in larger government orgs |

**Recommendation**: **Tailscale** for developer infrastructure access. Peer-to-peer mesh means no traffic routes through a third party (important for sovereignty). ACLs defined as code. Built-in SSH.

### DNS Filtering

Block known malicious domains before connections are established:

- **NextDNS** ($2/mo personal, ~$20/mo team): Privacy-focused, highly configurable
- **Cloudflare Gateway** (free for up to 50 users): Part of Zero Trust suite
- BIO2 8.21.01 requires monitoring at external connection points - DNS filtering helps satisfy this

### Network Segmentation (BIO2 8.22.01)

Our Docker setup already has some segmentation (`druppie-sandbox-network` separate from main). Extend this:

```
                    Internet
                        │
                   ┌────▼────┐
                   │ Firewall │
                   └────┬────┘
                        │
          ┌─────────────┼─────────────┐
          │             │             │
    ┌─────▼─────┐ ┌────▼────┐ ┌─────▼─────┐
    │  Dev/Test  │ │ Staging │ │ Production │
    │  Network   │ │ Network │ │  Network   │
    └───────────┘ └─────────┘ └───────────┘
          │                         │
    No direct access ──────────► Production
```

- Development network cannot reach production directly
- Staging is a separate environment
- Production access requires JIT (just-in-time) approval

### Monitoring Outbound Traffic

Post-supply-chain-attack, monitor what developer machines connect to:

- EDR (Defender for Endpoint) monitors outbound connections
- Alert on connections to unusual/new destinations
- DNS monitoring catches C2 callbacks (GlassWorm uses blockchain C2 but initial callbacks are DNS-based)

---

## 6. Leveraging Shared Government Services

### Het Waterschapshuis

As a waterschap, we can leverage:
- **CERT-WM**: 24/7 incident response for the water management sector (housed in Rijkswaterstaat's SOC)
- **Secura**: Mandated by Het Waterschapshuis for incident response and forensics
- **Shared architecture standards**: Don't reinvent the wheel
- **ENSIA coordination**: Shared approach to BIO compliance reporting

### SLM Rijk Framework Agreements

SLM Rijk manages government-wide contracts with Microsoft, Google Cloud, AWS, Oracle, etc. We can leverage these for:
- Pre-negotiated security terms
- Government-specific pricing
- Pre-approved tools and services
- Reduced procurement overhead

### NCSC-NL

The National Cyber Security Centre provides:
- Threat intelligence and advisories
- Incident response support
- Security guidelines and best practices
- Required reporting destination under NIS2/Cbw

---

## 7. Practical Implementation Roadmap

### Phase 1: Immediate (Weeks 1-4) - Non-Negotiable BIO2 Items

| Action | BIO2 Control | Effort | Cost |
|--------|-------------|--------|------|
| Enroll all dev devices in Intune | 8.01.02 | Medium | Included in M365 |
| Enforce disk encryption (BitLocker/FileVault) | 8.01.01 | Low | Free (Intune) |
| Enable Defender for Endpoint on all devices | 8.21.01 | Low | Included in M365 |
| Deploy MFA via Entra ID (all accounts) | 5.17.01 | Low | Included in M365 |
| Provide password manager (1Password/Bitwarden) | 5.17.02 | Low | $4-8/user/mo |
| Buy and distribute YubiKeys | 5.17.01 | Low | ~$150/dev one-time |
| Audit and remove shared accounts | 5.16.02 | Low | Free |

### Phase 2: Foundation (Months 1-3)

| Action | Compliance | Effort | Cost |
|--------|-----------|--------|------|
| Implement devcontainers in all repos | 8.27.01 | Medium | Free |
| Deploy Tailscale for infrastructure access | 8.21.01 | Low | $5/user/mo |
| Set up secrets manager (Doppler/Infisical) | General hygiene | Medium | Free-$6/user/mo |
| Enforce signed commits | NIS2 21.2.e | Low | Free (YubiKeys already bought) |
| Network segmentation (dev/staging/prod) | 8.22.01 | Medium | Depends on infra |
| DNS filtering (NextDNS) | 8.21.01 | Low | ~$20/mo |

### Phase 3: Maturity (Months 3-6)

| Action | Compliance | Effort | Cost |
|--------|-----------|--------|------|
| Evaluate Coder for cloud dev environments | 8.01.01 (zero footprint) | High | Free (OSS) |
| Implement JIT access for production | Least privilege | Medium | Free (Teleport OSS) |
| SBOM generation in CI/CD | NIS2 21.2.d | Low | Free |
| Annual access rights review process | 5.18.02 | Low | Free |
| ENSIA self-evaluation preparation | BIO2 | Medium | Internal effort |
| Incident response plan (NIS2 24h reporting) | NIS2 | Medium | Internal effort |

### Estimated Monthly Cost (10-person team)

| Category | Solution | Monthly Cost |
|----------|----------|-------------|
| MDM + Identity + EDR | Microsoft (existing M365) | Already paid |
| Password manager | 1Password Business | ~$60 |
| Hardware keys | YubiKeys (one-time) | ~$1,500 total |
| Network access | Tailscale Teams | ~$50 |
| DNS filtering | NextDNS | ~$20 |
| Secrets manager | Doppler/Infisical | Free-$60 |
| Dev environments | Devcontainers | Free |
| **Total new costs** | | **~$130-190/mo + $1,500 one-time** |

Most of the heavy lifting is done by the Microsoft stack you're likely already paying for via your waterschap's M365 license.

---

## References

- BIO2 v1.3: https://www.bio-overheid.nl/
- BIO2 Controls: https://minbzk.github.io/Baseline-Informatiebeveiliging-Overheid/maatregelen/
- NIS2/Cbw: https://business.gov.nl/amendments/nis2-directive-protects-network-information-systems/
- NIS2 + GitHub: https://navara.nl/en/inspiration/how-github-can-help-you-to-meet-nis2-cyberbeveiligingswet-requirements
- Sovereign Cloud: https://www.nldigitalgovernment.nl/featured-stories/joining-forces-to-build-a-sovereign-cloud-for-government/
- Het Waterschapshuis: https://www.hetwaterschapshuis.nl/
- NCSC-NL: https://english.ncsc.nl/
- ENSIA: https://vng.nl/projecten/ensia
- EU AI Act Guide NL: https://www.government.nl/binaries/government/documenten/publications/2025/09/04/ai-act-guide/ai-act-guide.pdf
