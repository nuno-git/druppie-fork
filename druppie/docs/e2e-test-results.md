# E2E Test Results — Summary Relay + Branch Injection Removal

**Date**: 2026-02-01
**Branch**: `refactor/clean-architecture`

## Changes Under Test

1. **Summary relay pattern**: Each agent's `done()` prepends its summary to the next agent's `planned_prompt`
2. **Repository pattern refactor**: `builtin_tools.py` uses `ExecutionRepository` instead of raw `db.query()`
3. **Branch injection removal**: Removed `session.branch_name` auto-injection from docker MCP; agents pass branch explicitly
4. **MCP tool fixes**: Added parameters to `create_branch`/`create_pull_request`/`merge_pull_request` schemas
5. **commit_and_push fix**: Always pushes even when no new staged changes (handles auto-commit case)
6. **Idempotent create_branch**: Falls back to `git checkout` if branch exists
7. **Gitea reserved username handling**: Falls back to prefixed names or email-based lookup

## Test 1: create_project

**Session**: `d604588a-56e6-4ed0-b6c8-628f7ea416c9`
**Message**: "Create a simple hello world counter web app"

### Agent Pipeline (5 agents)

| Agent | Status | Notes |
|-------|--------|-------|
| router | completed | Routed to create_project flow |
| planner | completed | Created 5-step plan |
| architect | completed | Wrote architecture.md (1 approval: write_file) |
| developer | completed | Wrote index.html, styles.css, Dockerfile; committed and pushed |
| deployer | completed | Built from Gitea, deployed to port 9100 (2 approvals: build, run) |

### Results

- **Gitea repo**: `http://localhost:3100/gitea_admin/hello-world-counter-22320dce` - 4 commits on main
- **Deployed app**: `http://localhost:9100` - Counter with increment button, working correctly
- **Gitea username resolution**: "admin" reserved in Gitea, fell back to `gitea_admin` via email lookup
- **All MCP tools worked**: write_file, commit_and_push, create_branch, docker:build, docker:run

### Issues Found & Fixed During Test

- **Gitea reserved username "admin"**: Added 3-tier fallback in `ensure_user_exists` (original → prefixed → email lookup)
- **Keycloak brute force lockout**: Admin account locked from repeated auth. Cleared via KC admin API.

---

## Test 2: update_project

**Session**: `1c35ad13-cbad-470c-9b62-85260a6bcb1f`
**Message**: "Update the hello-world-counter project: add a decrement button and change the background color to light blue"

### Agent Pipeline (7 agents, 5-step plan)

| # | Agent | Status | Notes |
|---|-------|--------|-------|
| 0 | router | completed | Routed to update_project flow |
| 1 | planner | completed | Created 5-step plan with 2x developer+deployer cycles |
| 2 | architect | completed | Updated architecture.md |
| 3 | developer | completed | Created feature branch, implemented changes, committed and pushed |
| 4 | deployer | completed | Built preview from feature branch, deployed to port 9101 |
| 5 | developer (review) | completed | Asked HITL question about preview, created PR #1, merged it |
| 6 | deployer (final) | completed | Rebuilt from main (post-merge), deployed to port 9102 |

### Results

- **Feature branch**: `feature/add-decrement-button-and-light-blue-bg` created autonomously by developer
- **Preview deployment**: `http://localhost:9101` - Light blue background, both buttons working
- **PR #1**: "feat: implement working counter with light blue background" — merged into main
- **Feature branch deleted**: After merge, only main branch remains (1 branch on Gitea)
- **Final deployment**: `http://localhost:9102` - Production deployment from main, all features working
- **Gitea commits**: 7 total (4 from create + 3 from update including merge commit)
- **HITL question**: Developer asked for approval of preview, answered programmatically
- **Approvals**: 4 tool approvals auto-approved (merge_pull_request, docker:build, docker:run x1 each + write_file)

### Summary Relay Verification

The deployer correctly received branch name and context from the developer's done() summary, without relying on `session.branch_name` injection. The full pipeline:

1. Developer → done() summary includes branch name and push status
2. Deployer receives summary as `PREVIOUS AGENT SUMMARY:` prefix in its planned_prompt
3. Deployer extracts branch name from summary, passes it explicitly to docker:build
4. After merge, second deployer builds from main (reads summary saying "PR merged, branch deleted")

---

## What Works

- **Full create_project flow**: Chat → 5 agents → Gitea repo → deployed container
- **Full update_project flow**: Chat → 7 agents → feature branch → preview → HITL → PR → merge → production deploy
- **Summary relay**: Agents pass context (branch names, URLs, container names) via done() summaries
- **Autonomous branching**: Developer creates branches without set_intent pre-creating them
- **MCP coding tools**: write_file, batch_write_files, commit_and_push, create_branch, create_pull_request, merge_pull_request, get_git_status
- **MCP docker tools**: build (from Gitea URL), run, list
- **Gitea integration**: Repo creation, commits, branches, PRs, merge, branch deletion
- **HITL questions**: Agent pauses, user answers via API, workflow resumes
- **Tool approvals**: Pending approvals listed and approvable via API
- **Keycloak auth**: Token-based auth for all API calls

## Known Issues / Improvements

1. **Deployer summary**: First deployer's done() summary was just "Task completed" — should include more detail (container name, port, preview URL) for the review agent
2. **HITL auto-answer**: The auto-approve script needed to be enhanced to also handle HITL questions (separate from tool approvals)
3. **Keycloak brute force**: Aggressive auth polling can lock accounts; production should use service accounts or longer poll intervals
4. **Port management**: Each deployment gets a new port (9100 → 9101 → 9102); old containers aren't cleaned up automatically
