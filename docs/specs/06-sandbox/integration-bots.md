# Integration Bots

`background-agents/packages/` contains three bots that integrate the sandbox system with external platforms. Druppie **does not use these** today — they're provided by the vendored `background-agents` system for use in other deployments.

## github-bot

Path: `packages/github-bot/`. Stack: CF Workers + Hono framework.

Purpose: GitHub App webhook handler.

Responsibilities:
- Listen for GitHub events: `push`, `pull_request`, `issues`, `issue_comment`.
- On PR opened → trigger a sandbox session to review the PR.
- On issue labelled with `sandbox` → trigger a session to fix the issue.
- Post sandbox output as PR comments.

## slack-bot

Path: `packages/slack-bot/`. Stack: CF Workers + Hono.

Purpose: Slack app for starting/managing sandbox sessions from Slack.

Responsibilities:
- Slash commands (`/inspect`, `/sandbox`).
- Thread-based status updates (reactions 👀 → 🏃 → ✅).
- `@mention` triggers.
- Completion callbacks with thread replies (diff, PR URL, screenshots).

Depends on `@anthropic-ai/sdk` for optional Claude-powered classifications of the triggering message.

## linear-bot

Path: `packages/linear-bot/`. Stack: TypeScript (not yet CF Worker-deployed).

Purpose: Link Linear issues to sandbox sessions.

Responsibilities:
- Issue → session mapping (Linear custom fields).
- Update issue status on sandbox completion.
- Link PRs back to issues.

## web

Path: `packages/web/`. Stack: Next.js 16 + React 19.

Purpose: Background-agents dashboard (NOT Druppie's UI). Shows the sessions the control plane has handled, regardless of trigger source.

Typical use: an org running the sandbox system standalone with GitHub + Slack integrations points its users at this dashboard to audit activity.

## Why these exist in this repo

When `background-agents` was extracted from a parent project, it already had these bots. Keeping them in the vendored tree preserves the ability to light them up if a Druppie deployment ever grows into a multi-source sandbox platform.

## Deploying them

See `background-agents/terraform/environments/production/main.tf` — every bot has a CF Worker + Secret + route entry. Deploying the terraform stack brings them all up simultaneously.

Not needed for Druppie dev or production-Druppie paths.
