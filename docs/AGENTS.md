# Agents Reference

This document is a user-facing guide to every agent in the Druppie platform. It covers what each agent does, what tools it has access to, when it runs in the pipeline, and what it produces.

---

## Pipeline Overview

A typical session flows through agents in this order:

1. **Router** -- classifies user intent
2. **Planner** -- creates the execution plan
3. **Business Analyst** -- gathers requirements (writes `functional_design.md`)
4. **Architect** -- designs architecture (writes `architecture.md`)
5. **Developer** -- implements code, commits, pushes
6. **Deployer** -- builds Docker image and deploys container
7. **Summarizer** -- posts a user-friendly completion message

For update workflows, additional steps are inserted: a branch setup developer step, preview deploy, review/merge developer step, and final deploy.

---

## Router Agent

| Property | Value |
|---|---|
| **ID** | `router` |
| **Name** | Router Agent |
| **Model** | glm-4 |
| **Temperature** | 0.1 |
| **Max Tokens** | 4096 |
| **Max Iterations** | 10 |

### Purpose

Analyzes the user's request and classifies it into one of three intents:

- `create_project` -- the user wants to build or create something new
- `update_project` -- the user wants to modify an existing project
- `general_chat` -- questions, explanations, no project action needed

### Tools

**Builtin tools:**
- `done` -- signal completion
- `hitl_ask_question` -- ask the user a question (used for `general_chat`)
- `hitl_ask_multiple_choice_question` -- ask user to select from options
- `set_intent` -- declare the user's intent, create projects and Gitea repos

**MCP tools:** None (empty `mcps`)

### When It Runs

Always first in every session. It is the entry point.

### What It Produces

- Calls `set_intent` to set the session's intent type
- For `create_project`: creates a `Project` record and Gitea repository
- For `update_project`: links the session to an existing project
- For `general_chat`: answers the user's question via `hitl_ask_question`
- Calls `done` with a brief classification summary

---

## Planner Agent

| Property | Value |
|---|---|
| **ID** | `planner` |
| **Name** | Planner Agent |
| **Model** | glm-4 |
| **Temperature** | 0.1 |
| **Max Tokens** | 16384 |
| **Max Iterations** | 15 |

### Purpose

Creates an execution plan based on the intent classified by the Router. The plan is a sequence of agent steps that will be executed in order.

### Tools

**Builtin tools:**
- `done` -- signal completion
- `hitl_ask_question` -- available but should not be used (planner is not supposed to ask questions)
- `hitl_ask_multiple_choice_question` -- available but should not be used
- `make_plan` -- create an execution plan with agent steps

**MCP tools:** None (empty `mcps`)

### When It Runs

Immediately after the Router. Receives intent information injected at the top of its prompt.

### What It Produces

- Calls `make_plan` with a list of steps, each specifying an `agent_id` and a `prompt`
- For `create_project`: plans business_analyst, architect, developer, deployer, summarizer
- For `update_project`: plans branch setup, business_analyst, architect, developer, preview deploy, review/merge, final deploy, summarizer
- For `general_chat`: calls `done` immediately (no plan needed)

---

## Business Analyst Agent

| Property | Value |
|---|---|
| **ID** | `business_analyst` |
| **Name** | Business Analyst Agent |
| **Model** | glm-4 |
| **Temperature** | 0.2 |
| **Max Tokens** | 100000 |
| **Max Iterations** | 50 |

### Purpose

Gathers functional requirements from the user through collaborative questions and produces a clear functional design document.

### Tools

**Builtin tools:**
- `done` -- signal completion
- `hitl_ask_question` -- ask clarifying questions to the user
- `hitl_ask_multiple_choice_question` -- ask user to select from options

**MCP tools (coding server):**
- `read_file` -- read existing project files
- `write_file` -- write `functional_design.md` (requires approval from `business_analyst` role)
- `list_dir` -- browse workspace directory structure

### Approval Overrides

- `coding:write_file` requires approval from `business_analyst` role

### When It Runs

Third in the pipeline (after Router and Planner). For `update_project`, runs after the developer creates the feature branch.

### What It Produces

- Asks 1-3 clarifying questions to the user via HITL tools
- Writes `functional_design.md` containing:
  - Project Overview
  - Target Users
  - Functional Requirements (numbered)
  - User Stories
  - Constraints/Preferences
  - Out of Scope
- Does NOT commit (the developer handles that)

---

## Architect Agent

| Property | Value |
|---|---|
| **ID** | `architect` |
| **Name** | Architect Agent |
| **Model** | glm-4 |
| **Temperature** | 0.2 |
| **Max Tokens** | 100000 |
| **Max Iterations** | 50 |

### Purpose

Designs system architecture and creates comprehensive technical specifications that developers will implement.

### Tools

**Builtin tools:**
- `done` -- signal completion
- `hitl_ask_question` -- ask questions (rarely used)
- `hitl_ask_multiple_choice_question` -- ask user to select from options

**MCP tools (coding server):**
- `read_file` -- read `functional_design.md` and existing source files
- `write_file` -- write `architecture.md` (requires approval from `architect` role)
- `list_dir` -- browse workspace directory structure

### Approval Overrides

- `coding:write_file` requires approval from `architect` role

### When It Runs

Fourth in the pipeline, after the Business Analyst has written `functional_design.md`.

### What It Produces

- Reads `functional_design.md` for requirements
- For `update_project`: also reads existing source code to plan changes
- Writes `architecture.md` containing:
  - Overview
  - Components
  - File Structure
  - Technology Choices
- Does NOT commit (the developer handles that)

---

## Developer Agent

| Property | Value |
|---|---|
| **ID** | `developer` |
| **Name** | Developer Agent |
| **Model** | glm-4 |
| **Temperature** | 0.1 |
| **Max Tokens** | 163840 |
| **Max Iterations** | 100 |

### Purpose

Writes and modifies code in git-managed workspaces. The workhorse agent that produces all implementation files.

### Tools

**Builtin tools:**
- `done` -- signal completion
- `hitl_ask_question` -- ask user questions (used during review tasks)
- `hitl_ask_multiple_choice_question` -- ask user to select from options

**MCP tools (coding server):**
- `read_file` -- read source files and architecture docs
- `write_file` -- write individual files
- `batch_write_files` -- write multiple files atomically
- `commit_and_push` -- commit all changes and push to Gitea
- `create_branch` -- create or switch to a git branch
- `create_pull_request` -- create a PR from current branch to main
- `merge_pull_request` -- merge a PR and delete the source branch
- `get_git_status` -- check current branch and changed files
- `list_dir` -- browse workspace directory structure
- `delete_file` -- delete files from workspace

### When It Runs

The developer can appear multiple times in a single plan:

1. **Branch Setup** (update_project only): Creates a feature branch. Does not write files.
2. **Implementation**: Reads `architecture.md`, writes all source files, creates Dockerfiles, commits and pushes.
3. **Review** (update_project only): Shows the user the preview URL, asks for approval, creates and merges a PR.

### What It Produces

- Source code files (HTML, CSS, JS, Python, etc.)
- Configuration files (`package.json`, `vite.config.js`, etc.)
- `Dockerfile` for deployment
- Git commits pushed to Gitea
- Pull requests (created and merged during review phase)

### Task Types

- **BRANCH SETUP ONLY**: Creates a feature branch, calls `done` immediately
- **IMPLEMENTATION**: Reads architecture, writes files, commits and pushes
- **REVIEW TASK**: Shows preview to user, handles approval, creates/merges PR

---

## Deployer Agent

| Property | Value |
|---|---|
| **ID** | `deployer` |
| **Name** | Deployer Agent |
| **Model** | glm-4 |
| **Temperature** | 0.1 |
| **Max Tokens** | 100000 |
| **Max Iterations** | 100 |

### Purpose

Handles Docker image building and container deployment. Can deploy previews from feature branches and production builds from main.

### Tools

**Builtin tools:**
- `done` -- signal completion
- `hitl_ask_question` -- ask questions (rarely used)
- `hitl_ask_multiple_choice_question` -- ask user to select from options

**MCP tools (docker server):**
- `build` -- build Docker image from git repo (requires `developer` approval)
- `run` -- run Docker container (requires `developer` approval)
- `stop` -- stop a running container
- `logs` -- get container logs for verification
- `list_containers` -- list containers (with label filtering)
- `inspect` -- inspect container details

**MCP tools (coding server):**
- `read_file` -- read Dockerfile to find EXPOSE port
- `write_file` -- create Dockerfile if missing
- `list_dir` -- check if Dockerfile exists
- `get_git_status` -- check workspace state
- `commit_and_push` -- push Dockerfile changes before building

### When It Runs

- **Create project**: Once, after the developer commits code
- **Update project**: Twice -- once for preview deploy (from feature branch), once for final deploy (from main after PR merge)

### What It Produces

- Docker images (tagged as `<project>:latest` or `<project>:preview`)
- Running Docker containers with Druppie ownership labels
- The deployment URL (e.g., `http://localhost:9101`)

### Deployment Workflow

1. List existing containers to discover naming conflicts
2. Read workspace to find Dockerfile and EXPOSE port
3. Create Dockerfile if missing, commit and push
4. Call `docker:build` (requires approval) -- clones from git and builds
5. Call `docker:run` (requires approval) -- starts container with auto-assigned host port
6. Check `docker:logs` to verify container health
7. Call `done` with URL, container name, and branch info

---

## Reviewer Agent

| Property | Value |
|---|---|
| **ID** | `reviewer` |
| **Name** | Reviewer Agent |
| **Model** | glm-4 |
| **Temperature** | 0.1 |
| **Max Tokens** | 100000 |
| **Max Iterations** | 50 |

### Purpose

Reviews code for quality, security, and best practices. Currently not included in the default pipeline plans but available for custom workflows.

### Tools

**Builtin tools:**
- `done` -- signal completion
- `hitl_ask_question` -- ask questions
- `hitl_ask_multiple_choice_question` -- ask user to select from options

**MCP tools (coding server):**
- `read_file` -- read source files for review
- `list_dir` -- browse project structure
- `write_file` -- write `REVIEW.md` with findings

### When It Runs

Not currently included in default plans. Available for inclusion in custom execution plans.

### What It Produces

- `REVIEW.md` containing:
  - Summary (pass/fail/needs work)
  - Issues found (by severity)
  - Recommendations
  - Positive observations

---

## Tester Agent

| Property | Value |
|---|---|
| **ID** | `tester` |
| **Name** | Tester Agent |
| **Model** | glm-4 |
| **Temperature** | 0.1 |
| **Max Tokens** | 100000 |
| **Max Iterations** | 30 |

### Purpose

Runs tests and validates implementations. Auto-detects test frameworks (pytest, jest, go test, cargo test). Currently not included in the default pipeline plans but available for custom workflows.

### Tools

**Builtin tools:**
- `done` -- signal completion
- `hitl_ask_question` -- ask questions
- `hitl_ask_multiple_choice_question` -- ask user to select from options

**MCP tools (coding server):**
- `read_file` -- read test files
- `list_dir` -- browse project structure to find tests
- `run_tests` -- auto-detect framework and run tests

### When It Runs

Not currently included in default plans. Available for inclusion in custom execution plans.

### What It Produces

- Test execution report with:
  - Tests found: Yes/No
  - Framework detected
  - Total / Passed / Failed / Skipped counts
  - Failed test names
  - Recommendations

---

## Summarizer Agent

| Property | Value |
|---|---|
| **ID** | `summarizer` |
| **Name** | Summarizer Agent |
| **Model** | glm-4 |
| **Temperature** | 0.3 |
| **Max Tokens** | 2048 |
| **Max Iterations** | 5 |

### Purpose

Creates a user-friendly completion message that summarizes what the entire team of agents accomplished. This is always the final agent in a pipeline.

### Tools

**Builtin tools:**
- `done` -- signal completion
- `hitl_ask_question` -- available but not used
- `hitl_ask_multiple_choice_question` -- available but not used
- `create_message` -- post a visible message in the chat timeline

**MCP tools:** None (empty `mcps`)

### When It Runs

Always last in every execution plan. Receives the accumulated `PREVIOUS AGENT SUMMARY` containing one-line summaries from every agent that ran.

### What It Produces

- A user-facing message posted to the chat timeline via `create_message`
- The message is conversational, uses bullet points, and highlights key outputs (URLs, what was built)
- Does not include internal technical details unless relevant to the user

---

## Common Model Settings

All agents currently use the `glm-4` model. Temperature settings vary by role:

| Agent | Temperature | Rationale |
|---|---|---|
| Router | 0.1 | Needs deterministic intent classification |
| Planner | 0.1 | Plans should be consistent and predictable |
| Business Analyst | 0.2 | Slightly more creative for gathering requirements |
| Architect | 0.2 | Slightly more creative for design decisions |
| Developer | 0.1 | Code generation should be precise |
| Deployer | 0.1 | Deployment commands must be exact |
| Reviewer | 0.1 | Reviews should be consistent |
| Tester | 0.1 | Test analysis should be precise |
| Summarizer | 0.3 | More creative for user-friendly language |
