# GlassWorm Threat Analysis

## Overview

GlassWorm is a sophisticated self-propagating worm discovered in October 2025 that represents one of the largest supply chain attacks to date. It has compromised 400+ repositories, 88+ npm packages, 72 VS Code extensions, and continues to evolve as of April 2026.

## How GlassWorm Works

### Attack Chain

1. **Initial Vector**: Malicious packages published on npm/PyPI or compromised VS Code extensions
2. **Hidden Payload**: Malicious code is encoded using invisible Unicode characters (variation selectors and private-use area code points) that are invisible to human review
3. **Execution**: Upon installation, a `postinstall` script executes the hidden payload
4. **Credential Harvesting**: The payload immediately begins collecting:
   - SSH keys
   - GitHub/npm/Git tokens
   - Environment variables
   - 49 cryptocurrency wallet extensions
5. **Self-Propagation**: Stolen credentials are used to force-push malware into other repositories the victim has access to
6. **Persistence**: Installs systemd backdoors for long-term access
7. **C2 Communication**: Uses Solana blockchain for command-and-control, with Google Calendar as fallback (making C2 infrastructure censorship-resistant)

### Why It's Particularly Dangerous

- **Invisible to code review**: Unicode characters are not visible in editors or diff tools
- **Self-propagating**: Each infected developer becomes a vector for infecting their other projects
- **Blockchain C2**: Cannot be taken down by seizing domains/servers
- **Multi-platform**: Targets npm, PyPI, VS Code extensions, and GitHub repositories
- **Exponential spread**: Stolen tokens enable compromise of trusted repositories

## Indicators of Compromise (IOCs)

| Indicator | Description |
|-----------|-------------|
| Hidden Unicode characters | Variation selectors and private-use area code points in source files |
| XOR key 134 | XOR decryption key used in the ForceMemo Python variant of GlassWorm (sometimes incorrectly referred to as "Artifact 134") |
| Postinstall scripts | Suspicious network calls during package installation |
| C2 markers | References to Solana blockchain transactions |
| Forced git pushes | Unexpected force-push events from compromised tokens |
| Systemd units | Unexpected systemd service files for persistence |
| Environment reads | Code that reads SSH keys, tokens, or wallet files |

## GlassWorm Campaign Timeline

| Date | Event |
|------|-------|
| October 17, 2025 | First wave: 72 VS Code extensions, 88 npm packages, 151+ GitHub repos |
| November 2025 | Second wave begins: 88 new npm packages via 50 disposable accounts |
| February 2026 | Campaign expands to new registries and platforms |
| March 2026 | Evolved campaign targets Python repositories with stolen GitHub tokens |
| April 2026 | Ongoing - new variants continue to appear |

## Impact on Druppie

### Initial Assessment (Jeremy Bode, ISO)

Jeremy Bode reported that `opencode-ai` (used in our sandbox image at `background-agents/packages/local-sandbox-manager/Dockerfile.sandbox`) was flagged in a security scan as a GlassWorm vector. The claims were:

- Source code contains thousands of invisible Unicode characters
- Postinstall script deploys GlassWorm payload
- Classified as "Artifact 134" - a specific GlassWorm footprint

### Verification (2026-04-16) - Likely Misidentification

Upon independent investigation, we could **NOT confirm** that the `opencode-ai` npm package itself is infected with GlassWorm:

- **glassworm-hunter scan**: Returns clean - zero hits on the opencode-ai package
- **glassworm-hunter IOC database**: Does not list opencode-ai as a known GlassWorm vector
- **No public reports**: No security researcher, CVE advisory, or vulnerability database identifies the opencode-ai npm package as a GlassWorm vector
- **Rescana article**: The article Jeremy cited does NOT mention opencode-ai at all
- **"Artifact 134"**: This is not a real GlassWorm classification. The number 134 refers to an XOR encryption key used in the ForceMemo Python variant - not an artifact identifier

**What likely happened**: The GlassWorm campaign DID target anomalyco (the organization behind OpenCode) in March 2026, but the compromised repository was `anomalyco/opencode-bench` (a peripheral benchmarking repo), NOT the main `anomalyco/opencode` repository or the `opencode-ai` npm package. Jeremy likely connected these dots incorrectly.

**Real security concerns with opencode-ai**: The package does have genuine (non-GlassWorm) CVEs:
- CVE-2026-22812 (Remote Code Execution)
- CVE-2026-22813 (Cross-Site Scripting)

These warrant keeping the package updated but are separate from the GlassWorm threat.

### Recommendation

While opencode-ai is likely NOT a GlassWorm vector, the incident highlights the importance of:
1. Verifying security claims independently before acting on them
2. Having automated scanning (glassworm-hunter, anti-trojan-source) to objectively verify or debunk reports
3. Evaluating whether opencode-ai should remain in the sandbox image given its real CVEs
4. The general supply chain security improvements proposed in this research remain critical regardless

## Recommendations

1. **Immediate**: Discuss findings with Jeremy Bode - share glassworm-hunter results and this analysis
2. **Immediate**: Run glassworm-hunter across the entire codebase (verify clean state)
3. **Immediate**: Evaluate opencode-ai's real CVEs (RCE, XSS) and decide whether to keep/update/remove it
4. **Short-term**: Implement Unicode detection in CI/CD pipeline (see [04-unicode-attack-detection.md](04-unicode-attack-detection.md))
5. **Short-term**: Integrate glassworm-hunter structurally (see [09-glassworm-hunter-integration.md](09-glassworm-hunter-integration.md))
6. **Medium-term**: Establish a process for verifying security reports before triggering emergency response

## References

- https://thehackernews.com/2026/03/glassworm-supply-chain-attack-abuses-72.html
- https://www.bleepingcomputer.com/news/security/glassworm-malware-hits-400-plus-code-repos-on-github-npm-vscode-openvsx/
- https://www.aikido.dev/blog/glassworm-returns-unicode-attack-github-npm-vscode
- https://fluidattacks.com/blog/glassworm-vs-code-extensions-supply-chain-attack
- https://www.rescana.com/post/glassworm-forcememo-campaign-supply-chain-attack-targets-github-python-repositories-with-stolen-tok/
