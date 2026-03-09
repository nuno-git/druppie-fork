# Replace Git Tools with Generic `run_git` Tool

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace four over-engineered git MCP tools (`commit_and_push`, `create_branch`, `get_git_status`, `merge_to_main`) with a single `run_git` tool that executes whitelisted git subcommands and returns raw terminal output — fixing the silent push failure bug by design.

**Architecture:** A single `run_git` tool accepts a free-form git command string, validates the subcommand against a whitelist (`add`, `commit`, `push`, `status`, `checkout`, `log`, `diff`), injects Gitea credentials transparently for network commands (`push`, `fetch`, `pull`), runs the command via subprocess, and returns `{success: bool, output: str}` based on exit code. Commit SHA is auto-captured from `git commit` output for revert service compatibility. PR tools (`create_pull_request`, `merge_pull_request`) remain unchanged.

**Tech Stack:** Python, subprocess, git, FastMCP

---

### Task 1: Add `run_git` tool implementation to server.py

**Files:**
- Modify: `druppie/mcp-servers/coding/server.py`

**Step 1: Add the `run_git` helper function**

Add after the existing `_do_commit_and_push` function (around line 925). This is the core implementation:

```python
async def _run_git(session_id: str, command: str, repo_name: str = None, repo_owner: str = None) -> dict:
    """Execute a whitelisted git command and return raw output."""
    ALLOWED_SUBCOMMANDS = {"add", "commit", "push", "status", "checkout", "log", "diff", "branch"}
    CREDENTIAL_SUBCOMMANDS = {"push", "fetch", "pull"}

    import shlex
    try:
        parts = shlex.split(command)
    except ValueError as e:
        return {"success": False, "error": f"Invalid command syntax: {e}"}

    if not parts:
        return {"success": False, "error": "Empty command"}

    # Strip leading "git" if provided
    if parts[0] == "git":
        parts = parts[1:]

    if not parts:
        return {"success": False, "error": "No git subcommand provided"}

    subcommand = parts[0]

    if subcommand not in ALLOWED_SUBCOMMANDS:
        return {
            "success": False,
            "error": f"Git subcommand '{subcommand}' is not allowed. Allowed: {', '.join(sorted(ALLOWED_SUBCOMMANDS))}",
        }

    # Block destructive flags
    BLOCKED_FLAGS = {"--force", "-f", "--hard"}
    if BLOCKED_FLAGS & set(parts):
        return {"success": False, "error": f"Destructive flags are not allowed: {BLOCKED_FLAGS & set(parts)}"}

    ws = get_or_create_workspace(session_id)
    work_dir = ws["path"]

    # Inject credentials for network commands
    env = os.environ.copy()
    if subcommand in CREDENTIAL_SUBCOMMANDS and repo_name and repo_owner:
        gitea_url = get_gitea_clone_url(repo_owner, repo_name)
        if gitea_url:
            # Ensure remote uses authenticated URL
            try:
                subprocess.run(
                    ["git", "remote", "set-url", "origin", gitea_url],
                    cwd=work_dir, capture_output=True, text=True, timeout=10
                )
            except Exception:
                pass  # Best effort — push will fail with auth error if this fails

    # Build and run the git command
    full_cmd = ["git"] + parts
    logger.info("run_git", command=full_cmd, work_dir=work_dir, session_id=session_id)

    try:
        result = subprocess.run(
            full_cmd,
            cwd=work_dir,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Command timed out after 120 seconds"}
    except Exception as e:
        return {"success": False, "error": f"Failed to execute command: {e}"}

    output = result.stdout.strip()
    error_output = result.stderr.strip()
    # Git sends some normal output to stderr (e.g. "Already up to date")
    combined = f"{output}\n{error_output}".strip() if error_output else output

    response = {
        "success": result.returncode == 0,
        "output": combined,
        "exit_code": result.returncode,
    }

    # Auto-capture commit SHA from git commit output
    if subcommand == "commit" and result.returncode == 0:
        import re
        sha_match = re.search(r'\[[\w/.-]+ ([a-f0-9]+)\]', output + " " + error_output)
        if sha_match:
            response["commit_sha"] = sha_match.group(1)

    # Update workspace branch tracking on checkout
    if subcommand == "checkout" and result.returncode == 0:
        try:
            branch_result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=work_dir, capture_output=True, text=True, timeout=10
            )
            if branch_result.returncode == 0:
                ws["branch"] = branch_result.stdout.strip()
                _save_workspace_state(ws)
        except Exception:
            pass

    if not response["success"]:
        response["error"] = error_output or "Command failed"

    return response
```

**Step 2: Register the `run_git` MCP tool endpoint**

Add the tool registration near the other git tool registrations (around line 1036):

```python
@mcp.tool()
async def run_git(session_id: str, command: str, repo_name: str = None, repo_owner: str = None) -> str:
    """Execute a git command in the workspace. Allowed subcommands: add, commit, push, status, checkout, log, diff, branch."""
    result = await _run_git(session_id, command, repo_name, repo_owner)
    return json.dumps(result)
```

**Step 3: Commit**

```bash
cd /home/nuno/Documents/cleaner-druppie/.worktrees/fix-silent-push-failure
git add druppie/mcp-servers/coding/server.py
git commit -m "feat: add run_git tool to server.py — generic git command execution with whitelist"
```

---

### Task 2: Add `run_git` method to module.py

**Files:**
- Modify: `druppie/mcp-servers/coding/module.py`

**Step 1: Add `run_git` method to CodingModule class**

Add this method to the `CodingModule` class, near the other git methods (around line 670):

```python
    async def run_git(self, session_id: str, command: str) -> dict:
        """Execute a whitelisted git command and return raw output."""
        ALLOWED_SUBCOMMANDS = {"add", "commit", "push", "status", "checkout", "log", "diff", "branch"}
        CREDENTIAL_SUBCOMMANDS = {"push", "fetch", "pull"}

        import shlex
        try:
            parts = shlex.split(command)
        except ValueError as e:
            return {"success": False, "error": f"Invalid command syntax: {e}"}

        if not parts:
            return {"success": False, "error": "Empty command"}

        if parts[0] == "git":
            parts = parts[1:]

        if not parts:
            return {"success": False, "error": "No git subcommand provided"}

        subcommand = parts[0]

        if subcommand not in ALLOWED_SUBCOMMANDS:
            return {
                "success": False,
                "error": f"Git subcommand '{subcommand}' is not allowed. Allowed: {', '.join(sorted(ALLOWED_SUBCOMMANDS))}",
            }

        BLOCKED_FLAGS = {"--force", "-f", "--hard"}
        if BLOCKED_FLAGS & set(parts):
            return {"success": False, "error": f"Destructive flags are not allowed: {BLOCKED_FLAGS & set(parts)}"}

        ws = self.get_or_create_workspace(session_id)
        work_dir = ws["path"]

        # Inject credentials for network commands
        if subcommand in CREDENTIAL_SUBCOMMANDS and self.gitea_url:
            gitea_clone_url = self._get_gitea_clone_url()
            if gitea_clone_url:
                try:
                    subprocess.run(
                        ["git", "remote", "set-url", "origin", gitea_clone_url],
                        cwd=work_dir, capture_output=True, text=True, timeout=10
                    )
                except Exception:
                    pass

        full_cmd = ["git"] + parts
        logger.info("run_git", command=full_cmd, work_dir=work_dir)

        try:
            result = subprocess.run(
                full_cmd, cwd=work_dir,
                capture_output=True, text=True, timeout=120,
            )
        except subprocess.TimeoutExpired:
            return {"success": False, "error": "Command timed out after 120 seconds"}
        except Exception as e:
            return {"success": False, "error": f"Failed to execute command: {e}"}

        output = result.stdout.strip()
        error_output = result.stderr.strip()
        combined = f"{output}\n{error_output}".strip() if error_output else output

        response = {
            "success": result.returncode == 0,
            "output": combined,
            "exit_code": result.returncode,
        }

        if subcommand == "commit" and result.returncode == 0:
            import re
            sha_match = re.search(r'\[[\w/.-]+ ([a-f0-9]+)\]', output + " " + error_output)
            if sha_match:
                response["commit_sha"] = sha_match.group(1)

        if subcommand == "checkout" and result.returncode == 0:
            try:
                branch_result = subprocess.run(
                    ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                    cwd=work_dir, capture_output=True, text=True, timeout=10
                )
                if branch_result.returncode == 0:
                    ws["branch"] = branch_result.stdout.strip()
                    self._save_workspace_state(ws)
            except Exception:
                pass

        if not response["success"]:
            response["error"] = error_output or "Command failed"

        return response
```

**Step 2: Commit**

```bash
cd /home/nuno/Documents/cleaner-druppie/.worktrees/fix-silent-push-failure
git add druppie/mcp-servers/coding/module.py
git commit -m "feat: add run_git method to module.py CodingModule class"
```

---

### Task 3: Add `RunGitParams` and remove old param models

**Files:**
- Modify: `druppie/tools/params/coding.py`

**Step 1: Add `RunGitParams`, remove old models**

Replace `CommitAndPushParams`, `CreateBranchParams`, `MergeToMainParams`, and `GetGitStatusParams` with `RunGitParams`:

```python
class RunGitParams(BaseModel):
    command: str = Field(description="Git command to execute (e.g. 'add .', 'commit -m \"message\"', 'push')")
```

Remove these classes:
- `CommitAndPushParams`
- `CreateBranchParams`
- `MergeToMainParams`
- `GetGitStatusParams`

**Step 2: Commit**

```bash
cd /home/nuno/Documents/cleaner-druppie/.worktrees/fix-silent-push-failure
git add druppie/tools/params/coding.py
git commit -m "refactor: replace old git param models with RunGitParams"
```

---

### Task 4: Update `mcp_config.yaml` — replace tool definitions and injection rules

**Files:**
- Modify: `druppie/core/mcp_config.yaml`

**Step 1: Replace the 4 old tool definitions with `run_git`**

Remove these tool definitions:
- `commit_and_push` (around line 137-147)
- `create_branch` (around line 149-159)
- `merge_to_main` (around line 191-198)
- `get_git_status` (around line 231-237)

Add one new definition:

```yaml
  run_git:
    description: "Execute a git command in the workspace. Allowed subcommands: add, commit, push, status, checkout, log, diff, branch. Destructive flags (--force, -f, --hard) are blocked."
    parameters:
      command:
        type: string
        description: "Git command to execute (e.g. 'add .', 'commit -m \"feat: add login\"', 'push', 'status')"
```

**Step 2: Update injection rules**

In the `inject_params` section, update the `tools:` lists:
- Where `commit_and_push`, `create_branch`, or `get_git_status` appear, replace with `run_git`
- Where `merge_to_main` appears, remove it entirely
- Make sure `run_git` appears in the session_id, repo_name, and repo_owner injection lists

**Step 3: Commit**

```bash
cd /home/nuno/Documents/cleaner-druppie/.worktrees/fix-silent-push-failure
git add druppie/core/mcp_config.yaml
git commit -m "refactor: replace 4 git tool definitions with run_git in mcp_config.yaml"
```

---

### Task 5: Update `tool_registry.py` — imports and PARAMS_MODEL_MAP

**Files:**
- Modify: `druppie/core/tool_registry.py`

**Step 1: Update imports**

Replace imports of old param models:
```python
# Remove these imports:
CommitAndPushParams, CreateBranchParams, MergeToMainParams, GetGitStatusParams

# Add this import:
RunGitParams
```

**Step 2: Update PARAMS_MODEL_MAP**

Replace the 4 old entries:
```python
# Remove:
("coding", "commit_and_push"): CommitAndPushParams,
("coding", "create_branch"): CreateBranchParams,
("coding", "merge_to_main"): MergeToMainParams,
("coding", "get_git_status"): GetGitStatusParams,

# Add:
("coding", "run_git"): RunGitParams,
```

**Step 3: Commit**

```bash
cd /home/nuno/Documents/cleaner-druppie/.worktrees/fix-silent-push-failure
git add druppie/core/tool_registry.py
git commit -m "refactor: update tool_registry.py — RunGitParams replaces old git param models"
```

---

### Task 6: Remove old git tools from server.py

**Files:**
- Modify: `druppie/mcp-servers/coding/server.py`

**Step 1: Remove `_do_commit_and_push` function**

Delete the entire `_do_commit_and_push` function (around lines 856-925).

**Step 2: Remove old tool registrations**

Delete these `@mcp.tool()` functions:
- `commit_and_push` (around line 1036-1074)
- `create_branch` (around line 1077-1153)
- `merge_to_main` (around line 1155-1219)
- `get_git_status` (around line 1221-1297)

**Step 3: Remove `auto_commit` from `delete_file`**

In `delete_file` (around line 749), remove:
- The `auto_commit` parameter
- The code block that calls `_do_commit_and_push` (around lines 800-810)

The function should just delete the file and return success.

**Step 4: Commit**

```bash
cd /home/nuno/Documents/cleaner-druppie/.worktrees/fix-silent-push-failure
git add druppie/mcp-servers/coding/server.py
git commit -m "refactor: remove old git tools and _do_commit_and_push from server.py"
```

---

### Task 7: Remove old git methods from module.py

**Files:**
- Modify: `druppie/mcp-servers/coding/module.py`

**Step 1: Remove `_do_commit_and_push` method**

Delete the entire `_do_commit_and_push` method (around lines 562-622).

**Step 2: Remove old git methods**

Delete these methods from `CodingModule`:
- `commit_and_push` (around line 674-676)
- `create_branch` (around line 678-697)
- `merge_to_main` (around line 699-722)
- `get_git_status` (around line 724-760)

**Step 3: Remove `auto_commit` from `batch_write_files`**

In `batch_write_files` (around line 640), remove:
- The `auto_commit` parameter
- The code block that calls `_do_commit_and_push` (around line 664)

**Step 4: Commit**

```bash
cd /home/nuno/Documents/cleaner-druppie/.worktrees/fix-silent-push-failure
git add druppie/mcp-servers/coding/module.py
git commit -m "refactor: remove old git methods and _do_commit_and_push from module.py"
```

---

### Task 8: Update `delete_file` tool definition in mcp_config.yaml

**Files:**
- Modify: `druppie/core/mcp_config.yaml`

**Step 1: Remove `auto_commit` parameter from `delete_file` tool definition**

Find the `delete_file` tool definition and remove the `auto_commit` parameter and its `commit_message` parameter if present.

**Step 2: Commit**

```bash
cd /home/nuno/Documents/cleaner-druppie/.worktrees/fix-silent-push-failure
git add druppie/core/mcp_config.yaml
git commit -m "refactor: remove auto_commit param from delete_file tool definition"
```

---

### Task 9: Update revert_service.py — query by `run_git` instead of `commit_and_push`

**Files:**
- Modify: `druppie/services/revert_service.py`

**Step 1: Update `_analyze_git_side_effects`**

At line 219, change:
```python
# BEFORE:
if tc.tool_name == "commit_and_push" and tc.result:
    result = self._parse_tool_result(tc.result)
    if result and result.get("commit_sha"):
        commit_shas.append(result["commit_sha"])

# AFTER:
if tc.tool_name == "run_git" and tc.result:
    result = self._parse_tool_result(tc.result)
    if result and result.get("commit_sha"):
        commit_shas.append(result["commit_sha"])
```

**Step 2: Commit**

```bash
cd /home/nuno/Documents/cleaner-druppie/.worktrees/fix-silent-push-failure
git add druppie/services/revert_service.py
git commit -m "fix: update revert_service to query run_git instead of commit_and_push"
```

---

### Task 10: Update execution_repository.py — query by `run_git`

**Files:**
- Modify: `druppie/repositories/execution_repository.py`

**Step 1: Update `get_last_commit_before_sequence`**

At line 641, change:
```python
# BEFORE:
ToolCall.tool_name == "commit_and_push",

# AFTER:
ToolCall.tool_name == "run_git",
```

**Step 2: Update `get_first_commit_in_session`**

At line 658, change:
```python
# BEFORE:
ToolCall.tool_name == "commit_and_push",

# AFTER:
ToolCall.tool_name == "run_git",
```

**Step 3: Commit**

```bash
cd /home/nuno/Documents/cleaner-druppie/.worktrees/fix-silent-push-failure
git add druppie/repositories/execution_repository.py
git commit -m "fix: update execution_repository to query run_git instead of commit_and_push"
```

---

### Task 11: Update git-workflow skill

**Files:**
- Modify: `druppie/skills/git-workflow/SKILL.md`

**Step 1: Update allowed-tools**

```yaml
# BEFORE:
allowed-tools:
  coding:
    - create_branch
    - commit_and_push
    - create_pull_request
    - merge_pull_request
    - get_git_status

# AFTER:
allowed-tools:
  coding:
    - run_git
    - create_pull_request
    - merge_pull_request
```

**Step 2: Update the workflow instructions**

Update the instructions body to reference `run_git` instead of the individual tools. Replace references to `commit_and_push` with examples using `run_git`:
- `run_git("status")` instead of `get_git_status()`
- `run_git("checkout -b feature/name")` instead of `create_branch("feature/name")`
- `run_git("add . && commit -m 'message'")` — note: one command at a time, so `run_git("add .")` then `run_git("commit -m 'message'")` then `run_git("push")`

Remove references to `merge_to_main` — merging is done through PRs only.

**Step 3: Commit**

```bash
cd /home/nuno/Documents/cleaner-druppie/.worktrees/fix-silent-push-failure
git add druppie/skills/git-workflow/SKILL.md
git commit -m "docs: update git-workflow skill to use run_git tool"
```

---

### Task 12: Update agent YAML definitions — mcps sections

**Files:**
- Modify: `druppie/agents/definitions/developer.yaml`
- Modify: `druppie/agents/definitions/builder.yaml`
- Modify: `druppie/agents/definitions/architect.yaml`
- Modify: `druppie/agents/definitions/business_analyst.yaml`
- Modify: `druppie/agents/definitions/reviewer.yaml`
- Modify: `druppie/agents/definitions/tester.yaml`
- Modify: `druppie/agents/definitions/deployer.yaml`

**Step 1: Update mcps sections in all agent YAMLs**

In each agent's `mcps:` section under `coding:`:
- Replace `commit_and_push` with `run_git`
- Replace `create_branch` with `run_git` (if not already listed)
- Replace `get_git_status` with `run_git` (if not already listed)
- Remove `merge_to_main` entirely
- Deduplicate — only one `run_git` entry per agent

**Step 2: Commit**

```bash
cd /home/nuno/Documents/cleaner-druppie/.worktrees/fix-silent-push-failure
git add druppie/agents/definitions/
git commit -m "refactor: replace old git tools with run_git in all agent YAML mcps sections"
```

---

### Task 13: Update agent YAML definitions — system prompt references

**Files:**
- Same agent YAML files as Task 12
- Also: `druppie/agents/definitions/planner.yaml`

**Step 1: Update system prompt references**

Search for references to old tool names in the `system_prompt:` sections of each agent YAML and update them:

- Replace `commit_and_push` with `run_git` in all prompt text
- Replace instructions like "use commit_and_push to save your work" with "use run_git to save your work (e.g. `run_git add .`, `run_git commit -m "message"`, `run_git push`)"
- Replace `create_branch` references with `run_git checkout -b <branch>` examples
- Replace `get_git_status` references with `run_git status`
- Remove references to `merge_to_main` — merging is done through PRs
- Update `planner.yaml` step templates that reference `create_branch`

**Step 2: Commit**

```bash
cd /home/nuno/Documents/cleaner-druppie/.worktrees/fix-silent-push-failure
git add druppie/agents/definitions/
git commit -m "docs: update system prompts in all agent YAMLs to reference run_git"
```

---

### Task 14: Verify — lint check

**Step 1: Run ruff check**

```bash
cd /home/nuno/Documents/cleaner-druppie/.worktrees/fix-silent-push-failure
cd druppie && ruff check mcp-servers/coding/server.py mcp-servers/coding/module.py core/tool_registry.py tools/params/coding.py services/revert_service.py repositories/execution_repository.py
```

Expected: No errors (or only pre-existing ones).

**Step 2: Fix any issues found, then commit**

```bash
git add -A
git commit -m "fix: resolve lint issues from run_git refactor"
```

---

### Task 15: Final review and push

**Step 1: Review all changes**

```bash
cd /home/nuno/Documents/cleaner-druppie/.worktrees/fix-silent-push-failure
git log --oneline origin/colab-dev..HEAD
git diff origin/colab-dev..HEAD --stat
```

**Step 2: Push the branch**

```bash
git push -u origin fix/commit-and-push-silent-failure
```
