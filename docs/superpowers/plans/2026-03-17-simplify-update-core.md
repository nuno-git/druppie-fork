# Simplify update_core Flow — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the complex `switch_to_update_core` tool + intent-switching mechanism with a simple signal-based flow using a dedicated `update_core_builder` agent.

**Architecture:** Architect signals `DESIGN_APPROVED_CORE_UPDATE` in done(). Planner routes to `update_core_builder` agent. Repo routing is determined by agent_id check in `execute_coding_task`. Session intent never changes.

**Tech Stack:** Python/FastAPI, SQLAlchemy, YAML agent definitions, Playwright E2E tests.

---

### Task 1: Create `update_core_builder` Agent Definition

**Files:**
- Create: `druppie/agents/definitions/update_core_builder.yaml`

- [ ] **Step 1: Create the agent YAML**

```yaml
id: update_core_builder
name: Update Core Builder Agent
description: Implements changes to Druppie's own codebase and creates a PR for review
category: execution

system_prompt: |
  You are the Update Core Builder Agent for Druppie. You implement changes to
  Druppie's own codebase (the core platform).

  =============================================================================
  COMPLETION (CRITICAL — READ THIS FIRST!)
  =============================================================================

  When calling done(), your summary MUST be specific about what you did.
  Previous agent summaries are auto-prepended by the system. You only provide
  YOUR OWN "Agent update_core_builder:" line.

  IMPORTANT: Your done() call requires approval from a developer. The approval
  message will include your summary, so ALWAYS include the PR URL so the
  reviewer knows which PR to review and merge before approving.

  CORRECT:
    Call done with summary: "Agent update_core_builder: Implemented [description].
    Created PR #42: https://github.com/nuno-git/druppie-fork/pull/42
    targeting colab-dev. Please review and merge the PR before approving."

  WRONG:
    Calling done with summary "Task completed"
    Calling done with summary "Done"

  =============================================================================
  TASK
  =============================================================================

  You receive a CORE CHANGE task from the Planner (based on the Architect's
  technical design). Your job:

  1. Read functional_design.md and technical_design.md for context
  2. Call execute_coding_task with a prompt that:
     - Creates branch core/<short-description> from colab-dev
     - Implements the described change
     - Commits and pushes
     - Creates a PR targeting colab-dev (NOT main!)
     - Does NOT merge the PR
  3. Call done() with the PR URL in your summary

  IMPORTANT: Always include "Create a PR targeting colab-dev" in your
  execute_coding_task prompt.

  =============================================================================
  CODE QUALITY
  =============================================================================

  Include these standards in your task prompts:
  - Write clean, readable code with proper error handling
  - Follow existing code patterns in the Druppie codebase
  - Include appropriate tests where applicable

system_prompts:
  - tool_only_communication
  - summary_relay
  - done_tool_format
  - workspace_state

mcps:
  coding: [read_file, list_dir]

extra_builtin_tools:
  - execute_coding_task

# done() requires developer approval — reviewer must merge the PR first
approval_overrides:
  "builtin:done":
    requires_approval: true
    required_role: developer

llm_profile: standard
temperature: 0.1
max_tokens: 4096
max_iterations: 100
```

- [ ] **Step 2: Verify YAML parses correctly**

Run: `cd /home/nuno/Documents/cleaner-druppie/.worktrees/update-core-flow && python3 -c "import yaml; print(yaml.safe_load(open('druppie/agents/definitions/update_core_builder.yaml'))['id'])"`
Expected: `update_core_builder`

- [ ] **Step 3: Commit**

```bash
git add druppie/agents/definitions/update_core_builder.yaml
git commit -m "feat: add update_core_builder agent definition"
```

---

### Task 2: Update Architect — Replace `switch_to_update_core` with Signal

**Files:**
- Modify: `druppie/agents/definitions/architect.yaml`

- [ ] **Step 1: Remove `switch_to_update_core` references and add `DESIGN_APPROVED_CORE_UPDATE` signal**

In `architect.yaml`:

1. Replace the big comment block at lines 7-28 with a simpler instruction about using the `DESIGN_APPROVED_CORE_UPDATE` signal
2. Remove `switch_to_update_core` from general_chat section (line 210)
3. Remove `switch_to_update_core` from create_project section (line 219)
4. Remove `extra_builtin_tools: - switch_to_update_core` (line 585)

The new instruction (replacing lines 7-28):
```
  ############################################################################
  # DRUPPIE SELF-IMPROVEMENT — SIGNAL: DESIGN_APPROVED_CORE_UPDATE          #
  ############################################################################
  #                                                                          #
  # After completing your normal workflow (reading FD, architecture check,   #
  # writing technical_design.md, git commit+push), check:                    #
  #                                                                          #
  #   → Is this project about modifying DRUPPIE ITSELF?                      #
  #                                                                          #
  # Druppie keywords: druppie, core, router, planner, agent, prompt, skill,  #
  # MCP server, sandbox, workflow, architect, developer, tester, business    #
  # analyst, summarizer, deployer, builder, self-improvement                 #
  #                                                                          #
  # If YES → Use DESIGN_APPROVED_CORE_UPDATE instead of DESIGN_APPROVED     #
  #          in your done() summary. Write technical_design.md as normal.    #
  #                                                                          #
  # If NO  → Use DESIGN_APPROVED as normal.                                 #
  #                                                                          #
  ############################################################################
```

Add a new status signal section after DESIGN_REJECTED (after line 87):
```
  ### STATUS: DESIGN_APPROVED_CORE_UPDATE
  Use when the functional design passes all checks, you have written technical_design.md,
  AND the project involves modifying Druppie itself (its agents, prompts, skills, or codebase).

  CORRECT:
    Call done with summary: "Agent architect: DESIGN_APPROVED_CORE_UPDATE. Reviewed functional_design.md — passes all architecture checks. Wrote technical_design.md. This project requires changes to Druppie's core before the actual project can be built."
```

For general_chat SWITCHING TO UPDATE_CORE section (around line 207-211), replace with:
```
  ### SWITCHING TO UPDATE_CORE (Druppie self-improvement)

  If the user wants to CHANGE or IMPROVE Druppie itself during general_chat,
  use CHAT_ROUTE_CREATE_PROJECT (the normal project creation flow will handle it —
  the Architect will detect it's a core change and signal DESIGN_APPROVED_CORE_UPDATE).
```

For create_project section (around line 218-219), replace step 4 with:
```
  4. **AFTER writing technical_design.md:** If this project is about modifying
     Druppie itself, signal DESIGN_APPROVED_CORE_UPDATE instead of DESIGN_APPROVED.
```

- [ ] **Step 2: Verify YAML parses correctly**

Run: `cd /home/nuno/Documents/cleaner-druppie/.worktrees/update-core-flow && python3 -c "import yaml; d = yaml.safe_load(open('druppie/agents/definitions/architect.yaml')); print(d['id']); print('switch_to_update_core' not in d.get('extra_builtin_tools', []))"`
Expected: `architect` and `True`

- [ ] **Step 3: Commit**

```bash
git add druppie/agents/definitions/architect.yaml
git commit -m "refactor: architect uses DESIGN_APPROVED_CORE_UPDATE signal instead of switch_to_update_core tool"
```

---

### Task 3: Update Planner — Handle New Signal and Route to `update_core_builder`

**Files:**
- Modify: `druppie/agents/definitions/planner.yaml`

- [ ] **Step 1: Update the planner YAML**

Changes needed:

1. **Remove `update_core` from INTENT list** (line 15): Change to `create_project | update_project | general_chat`

2. **Remove MODE 1 section 3 (UPDATE_CORE)** (lines 75-82): Delete the entire `FOR UPDATE_CORE` section

3. **Add `update_core_builder` to AVAILABLE AGENTS** (after line 48):
   ```
   - update_core_builder: Implements changes to Druppie's own codebase. Creates a PR for developer review. Only used when the architect signals DESIGN_APPROVED_CORE_UPDATE.
   ```

4. **Remove CHAT_ROUTE_UPDATE_CORE** (lines 136-140): Delete this section

5. **Remove "developer completed CORE CHANGE"** (lines 144-147): Delete this section

6. **Add new re-evaluation: After ARCHITECT signals DESIGN_APPROVED_CORE_UPDATE** (after the DESIGN_APPROVED section around line 212):
   ```
     If DESIGN_APPROVED_CORE_UPDATE:
     The architect has determined this project requires changes to Druppie's own
     codebase before the actual project can be built. Route to update_core_builder.
     Call make_plan with 2 steps:
     - Step 1: agent_id="update_core_builder", prompt="CORE CHANGE: Implement the approved design. Read functional_design.md and technical_design.md. Create a PR targeting colab-dev."
     - Step 2: agent_id="planner", prompt="Update core builder completed. Evaluate output and decide next step."
   ```

7. **Add new re-evaluation: After UPDATE_CORE_BUILDER completed** (new section):
   ```
     ### After UPDATE_CORE_BUILDER completed:

     The core changes have been merged (developer approved). Now route back to the
     architect to design the actual project with the core changes in place.
     Call make_plan with 2 steps:
     - Step 1: agent_id="architect", prompt="Core changes have been merged into Druppie. Now design the actual project. Read functional_design.md. Update or create technical_design.md for the project implementation (not the core changes). Signal DESIGN_APPROVED when ready."
     - Step 2: agent_id="planner", prompt="Architect completed post-core-update design. Evaluate output and decide next step."
   ```

8. **Update MANDATORY SEQUENCES** (lines 346-361):
   - Remove the `UPDATE_CORE sequence` line (358-359)
   - Add: `**CORE UPDATE variant** (when architect signals DESIGN_APPROVED_CORE_UPDATE): ... → architect (DESIGN_APPROVED_CORE_UPDATE) → update_core_builder → architect (run 2, DESIGN_APPROVED) → normal flow`

9. **Update architect prompt in DESIGN_APPROVED first-time** (line 183): Remove the `IMPORTANT: After writing technical_design.md, if this project is about modifying Druppie itself...call switch_to_update_core` instruction. Replace with: `IMPORTANT: If this project is about modifying Druppie itself, signal DESIGN_APPROVED_CORE_UPDATE instead of DESIGN_APPROVED.`

10. **Update planner self-prompt after architect** (line 184): Remove `INTENT: [repeat the current intent: create_project, update_project, or update_core].` — just leave: `Evaluate output and decide next step.`

- [ ] **Step 2: Verify YAML parses correctly**

Run: `cd /home/nuno/Documents/cleaner-druppie/.worktrees/update-core-flow && python3 -c "import yaml; d = yaml.safe_load(open('druppie/agents/definitions/planner.yaml')); print(d['id']); print('update_core' not in d['system_prompt'][:200])"`
Expected: `planner` and `True`

- [ ] **Step 3: Commit**

```bash
git add druppie/agents/definitions/planner.yaml
git commit -m "refactor: planner routes DESIGN_APPROVED_CORE_UPDATE to update_core_builder, removes update_core intent"
```

---

### Task 4: Update `execute_coding_task` — Agent-Based Repo Routing

**Files:**
- Modify: `druppie/agents/builtin_tools.py:1030-1046`

- [ ] **Step 1: Replace intent-based routing with agent_id-based routing**

Replace lines 1030-1046 in `execute_sandbox_coding_task()`:

```python
    # Determine git provider and repo context based on calling agent
    agent_run = execution_repo.get_by_id(agent_run_id)
    calling_agent_id = agent_run.agent_id if agent_run else None

    if calling_agent_id == "update_core_builder":
        # update_core_builder: use GitHub App credentials for Druppie's own repo
        repo_owner = os.getenv("DRUPPIE_REPO_OWNER", "nuno-git")
        repo_name = os.getenv("DRUPPIE_REPO_NAME", "druppie-fork")
        git_provider = "github"
    else:
        # create_project / update_project: use Gitea credentials
        repo_owner = os.getenv("GITEA_ORG", "druppie")
        repo_name = ""
        if session.project_id:
            project_repo = ProjectRepository(db)
            project = project_repo.get_by_id(session.project_id)
            if project:
                repo_owner = project.repo_owner or repo_owner
                repo_name = project.repo_name or ""
        git_provider = "gitea"
```

- [ ] **Step 2: Commit**

```bash
git add druppie/agents/builtin_tools.py
git commit -m "refactor: execute_coding_task routes repo by agent_id instead of session intent"
```

---

### Task 5: Update Sandbox Retry — Agent-Based Repo Routing

**Files:**
- Modify: `druppie/api/routes/sandbox.py:240-260`

- [ ] **Step 1: Replace intent-based routing with agent_id lookup via tool_call**

Replace lines 241-259 in `_retry_sandbox_with_next_model()`:

```python
    # Get repo info and git provider — trace back to the calling agent via tool_call
    repo_owner = os.getenv("GITEA_ORG", "druppie")
    repo_name = ""
    git_provider = "gitea"

    # Determine if this was a core update by checking the originating agent
    calling_agent_id = None
    if tool_call_id:
        from druppie.repositories import ExecutionRepository
        execution_repo = ExecutionRepository(db)
        tool_call = execution_repo.get_tool_call(tool_call_id)
        if tool_call and tool_call.agent_run_id:
            agent_run = execution_repo.get_by_id(tool_call.agent_run_id)
            if agent_run:
                calling_agent_id = agent_run.agent_id

    if calling_agent_id == "update_core_builder":
        repo_owner = os.getenv("DRUPPIE_REPO_OWNER", "nuno-git")
        repo_name = os.getenv("DRUPPIE_REPO_NAME", "druppie-fork")
        git_provider = "github"
    elif sandbox_mapping.session_id:
        from druppie.repositories import SessionRepository, ProjectRepository
        session_repo = SessionRepository(db)
        session = session_repo.get_by_id(sandbox_mapping.session_id)
        if session and session.project_id:
            project_repo = ProjectRepository(db)
            project = project_repo.get_by_id(session.project_id)
            if project:
                repo_owner = project.repo_owner or repo_owner
                repo_name = project.repo_name or ""
```

- [ ] **Step 2: Commit**

```bash
git add druppie/api/routes/sandbox.py
git commit -m "refactor: sandbox retry routes repo by agent_id instead of session intent"
```

---

### Task 6: Remove `switch_to_update_core` Tool

**Files:**
- Modify: `druppie/agents/builtin_tools.py`

- [ ] **Step 1: Remove tool definition from BUILTIN_TOOL_DEFS**

Delete the `"switch_to_update_core"` entry (lines 194-217) from `BUILTIN_TOOL_DEFS` dict.

- [ ] **Step 2: Remove implementation function**

Delete the `switch_to_update_core()` function (lines 560-632) and its section comment.

- [ ] **Step 3: Remove dispatch case in `execute_builtin()`**

Delete lines 1209-1215 (the `elif tool_name == "switch_to_update_core"` case).

- [ ] **Step 4: Remove from `is_builtin_tool()`**

Remove `"switch_to_update_core"` from the tuple in `is_builtin_tool()` (line 1257).

- [ ] **Step 5: Update module docstring**

Remove the reference to `switch_to_update_core` from the comment at line 10.

- [ ] **Step 6: Commit**

```bash
git add druppie/agents/builtin_tools.py
git commit -m "refactor: remove switch_to_update_core tool entirely"
```

---

### Task 7: Remove Session Repo Fields

**Files:**
- Modify: `druppie/db/models/session.py`
- Modify: `druppie/repositories/session_repository.py`

- [ ] **Step 1: Remove `repo_owner` and `repo_name` from Session model**

In `druppie/db/models/session.py`:
- Delete lines 26-28 (the `repo_owner` and `repo_name` columns and comment)
- Update `intent` comment on line 23 to remove `update_core`: `# create_project, update_project, general_chat`
- Remove `"repo_owner"` and `"repo_name"` from `to_dict()` (lines 50-51)

- [ ] **Step 2: Remove `update_repo_context()` from SessionRepository**

In `druppie/repositories/session_repository.py`:
- Delete the `update_repo_context()` method (lines 188-198)

- [ ] **Step 3: Commit**

```bash
git add druppie/db/models/session.py druppie/repositories/session_repository.py
git commit -m "refactor: remove repo_owner/repo_name from Session model, remove update_repo_context"
```

---

### Task 8: Clean Up Developer Agent

**Files:**
- Modify: `druppie/agents/definitions/developer.yaml`

- [ ] **Step 1: Remove CORE CHANGE task type**

In `developer.yaml`, remove the "CORE CHANGE" section (lines 48-56). The developer agent no longer handles core changes — that's the `update_core_builder`'s job.

- [ ] **Step 2: Commit**

```bash
git add druppie/agents/definitions/developer.yaml
git commit -m "refactor: remove CORE CHANGE task type from developer agent (moved to update_core_builder)"
```

---

### Task 9: Update Comments and Config References

**Files:**
- Modify: `druppie/core/config.py` (update comments referencing update_core)
- Modify: `druppie/services/github_app_service.py` (update comment)

- [ ] **Step 1: Update config.py comments**

Update any comments that reference `update_core` intent to mention `update_core_builder` agent instead.

- [ ] **Step 2: Update github_app_service.py comment**

Line 3: Change "Used by update_core to authenticate..." to "Used by update_core_builder agent to authenticate..."
Line 150: Update comment similarly.

- [ ] **Step 3: Add env vars to .env.example if not present**

Add `DRUPPIE_REPO_OWNER` and `DRUPPIE_REPO_NAME` to `.env.example`.

- [ ] **Step 4: Commit**

```bash
git add druppie/core/config.py druppie/services/github_app_service.py .env.example
git commit -m "chore: update comments and config for update_core_builder agent"
```

---

### Task 10: Handle `done` Approval for `update_core_builder`

**Files:**
- Modify: `druppie/execution/tool_executor.py` (if needed)
- Modify: `druppie/core/mcp_config.py` (if needed)

- [ ] **Step 1: Verify builtin tool approval works with `approval_overrides`**

The `update_core_builder.yaml` has:
```yaml
approval_overrides:
  "builtin:done":
    requires_approval: true
    required_role: developer
```

Check that the approval system handles the `"builtin:done"` key correctly. The `needs_approval()` method in `mcp_config.py` receives `server` and `tool` — for builtins, the server is `"builtin"`. Verify this works by reading `tool_executor.py` to see how approval is checked for builtin tools.

- [ ] **Step 2: If needed, add approval check for builtin tools**

If the current code doesn't check `approval_overrides` for builtin tools (it likely only checks for MCP tools), add the check in `tool_executor.py` `execute()` method, similar to the MCP approval check.

- [ ] **Step 3: Commit**

```bash
git add druppie/execution/tool_executor.py druppie/core/mcp_config.py
git commit -m "feat: support approval_overrides for builtin tools (done requires developer approval for update_core_builder)"
```

---

### Task 11: Rebuild and Reset DB

- [ ] **Step 1: Stop services**

```bash
cd /home/nuno/Documents/cleaner-druppie/.worktrees/update-core-flow
docker compose --profile dev down
```

- [ ] **Step 2: Reset DB**

```bash
docker compose --profile infra --profile reset-hard run --rm reset-hard
```

- [ ] **Step 3: Rebuild and start**

```bash
docker compose --profile dev --profile init up -d --build
```

- [ ] **Step 4: Verify services are healthy**

```bash
docker compose --profile dev ps
docker compose logs druppie-backend-dev --tail=50
```

---

### Task 12: E2E Verification

- [ ] **Step 1: Run existing Playwright tests to verify no regression**

```bash
cd /home/nuno/Documents/cleaner-druppie/.worktrees/update-core-flow/frontend
npx playwright test
```

- [ ] **Step 2: Manual E2E test of update_core flow**

Using the chat UI:
1. Login as admin
2. Send a message like "I want to improve Druppie's router to better detect update requests"
3. Verify: Router classifies as `create_project`
4. Verify: BA asks requirements questions
5. Verify: Architect writes TD and signals `DESIGN_APPROVED_CORE_UPDATE`
6. Verify: `update_core_builder` agent runs, calls `execute_coding_task`
7. Verify: Sandbox uses GitHub repo (not Gitea)
8. Verify: `done()` pauses for developer approval
