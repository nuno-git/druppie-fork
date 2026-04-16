# Dependency Update Automation: Dependabot vs Renovate

## The Problem

Dependencies must be updated regularly to receive security patches, but every update is a potential attack vector. During the LiteLLM supply chain attack, compromised versions were live on PyPI for ~40 minutes - long enough for automated update bots to pick them up.

The question: How do we stay up-to-date without auto-accepting compromised packages?

---

## Approach 1: GitHub Dependabot

### How It Works
GitHub's built-in dependency update bot. Creates PRs automatically when new versions of dependencies are available or security vulnerabilities are discovered.

### Pros
- **Zero configuration**: Enable via GitHub UI, no self-hosting
- **GitHub-native**: Deep integration with GitHub security advisories
- **Security alerts**: Immediate alerts for known vulnerabilities
- **Auto-merge option**: Can auto-merge minor/patch updates (with caveats - see below)
- **Free**: Included with GitHub

### Cons
- **GitHub-only**: Locked to GitHub (we use GitHub, so this is fine)
- **Limited configuration**: Fewer options than Renovate for grouping, scheduling
- **Fewer package managers**: Doesn't support all ecosystems Renovate does
- **No Gitea support**: Cannot run against our internal Gitea repositories

---

## Approach 2: Renovate

### How It Works
Open-source dependency update bot with extensive configuration options. Can run as GitHub App, GitLab CI, or self-hosted.

### Pros
- **90+ package managers**: Supports virtually everything
- **Advanced grouping**: Can group related updates into single PRs
- **Scheduling control**: Update on specific days/times, with configurable windows
- **Monorepo support**: Superior handling of workspace/monorepo patterns (relevant for background-agents)
- **Cross-platform**: Works with GitHub, GitLab, Gitea, Bitbucket
- **Gitea support**: Can run against our Gitea repositories
- **Custom rules**: Regex-based package rules for fine-grained control

### Cons
- **Configuration complexity**: More setup than Dependabot
- **Learning curve**: Many options can be overwhelming
- **Self-hosting optional**: GitHub App is free, self-hosted needs infrastructure

---

## Critical Security Concern: Auto-Merge is Dangerous

### The Implicit Trust Problem (2026)

Research from GitGuardian (early 2026) highlighted a critical issue:

> Dependabot and Renovate PRs carry implicit trust that human PRs don't. Teams that auto-merge dependency updates are one compromised package away from a breach.

**Real-world attack chain:**
1. Attacker compromises a maintainer account (or publishes a malicious version)
2. Malicious version appears on npm/PyPI
3. Dependabot/Renovate creates a PR to update to the malicious version
4. PR is auto-merged (because "it's just a dependency update")
5. Malicious code is now in the codebase and deployed

**This is exactly what happened with LiteLLM:**
- Compromised versions 1.82.7 and 1.82.8 were on PyPI for ~40 minutes
- Any project with auto-merge enabled for LiteLLM would have been compromised
- 95 million monthly downloads = massive blast radius

### Recommendation: NEVER Auto-Merge

- **Security updates**: Create PR, but require manual review
- **Minor/patch updates**: Create PR, require manual review
- **Major updates**: Create PR, require thorough review
- **CI/CD workflow changes**: Create PR, require security team approval

The time saved by auto-merge is not worth the risk of automatically merging a supply chain attack.

---

## Comparison

| Feature | Dependabot | Renovate |
|---------|-----------|----------|
| Cost | Free (GitHub) | Free (open-source) |
| Setup effort | Minimal | Moderate |
| Package managers | ~15 | 90+ |
| Grouping | Basic | Advanced |
| Scheduling | Basic | Advanced |
| Monorepo support | Basic | **Excellent** |
| Gitea support | No | **Yes** |
| GitHub integration | **Native** | Good (App) |
| Custom rules | Limited | **Extensive** |
| Vulnerability alerts | **Excellent** | Good |
| Configuration complexity | Low | High |

---

## Recommendation for Druppie

### Use Both (Hybrid Approach)

1. **Dependabot** for GitHub security alerts:
   - Enable Dependabot security alerts on the GitHub repository
   - Creates immediate PRs for known vulnerabilities
   - Best-in-class GitHub integration for security advisories

2. **Renovate** for regular dependency updates:
   - Better configuration control
   - Superior monorepo support (for background-agents)
   - Can be configured with Gitea for internal repos
   - Group related updates to reduce PR noise

### Configuration Principles

```
Auto-merge: DISABLED for all updates
Schedule: Weekly (Monday morning)
Grouping: Group minor+patch by ecosystem (one PR for all Python, one for Node.js)
Labels: Add "security-review" label to all dependency PRs
Reviewers: Assign security team as required reviewer
```

### Review Checklist for Dependency PRs

Before merging any dependency update PR:

1. **Check the package**: Is it a known, trusted package? Has the maintainer changed recently?
2. **Check the version**: How old is this version? Was it published in the last 24 hours? (If yes, wait)
3. **Check the changelog**: Do the changes match what's expected for this version bump?
4. **Check the lock file**: Are there unexpected changes to transitive dependencies?
5. **Run security scans**: Does the CI pipeline (pip-audit, npm audit, glassworm-hunter) pass?
6. **Check download stats**: Has there been a sudden spike or drop in downloads? (Indicator of compromise or package takeover)
