# OpenCode Native Skills — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Deploy coding skills as native OpenCode skills in sandboxes instead of using Druppie's custom invoke_skill system.

**Architecture:** Generalize the `SANDBOX_AGENT_FILES` env var pipeline to `SANDBOX_OPENCODE_FILES`, supporting path-based keys that write to any `.opencode/` subdirectory. Load OpenCode skills per-agent from YAML definitions.

**Tech Stack:** Python (FastAPI, Pydantic), TypeScript (Cloudflare Workers), Python (Modal sandbox entrypoint)

---

### Task 1: Create OpenCode skills directory and move skill files

**Files:**
- Create: `druppie/opencode/__init__.py`
- Create: `druppie/opencode/skills/fullstack-architecture/SKILL.md`
- Create: `druppie/opencode/skills/project-coding-standards/SKILL.md`
- Create: `druppie/opencode/skills/standards-validation/SKILL.md`
- Delete: `druppie/skills/fullstack-architecture/SKILL.md`
- Delete: `druppie/skills/project-coding-standards/SKILL.md`
- Delete: `druppie/skills/standards-validation/SKILL.md`

**Step 1: Create directory structure**

```bash
mkdir -p druppie/opencode/skills/fullstack-architecture
mkdir -p druppie/opencode/skills/project-coding-standards
mkdir -p druppie/opencode/skills/standards-validation
touch druppie/opencode/__init__.py
```

**Step 2: Move skill files**

```bash
git mv druppie/skills/fullstack-architecture/SKILL.md druppie/opencode/skills/fullstack-architecture/SKILL.md
git mv druppie/skills/project-coding-standards/SKILL.md druppie/opencode/skills/project-coding-standards/SKILL.md
git mv druppie/skills/standards-validation/SKILL.md druppie/opencode/skills/standards-validation/SKILL.md
rmdir druppie/skills/fullstack-architecture
rmdir druppie/skills/project-coding-standards
rmdir druppie/skills/standards-validation
```

**Step 3: Strip `allowed-tools` from standards-validation frontmatter**

In `druppie/opencode/skills/standards-validation/SKILL.md`, remove the `allowed-tools` block from the YAML frontmatter. Change from:

```yaml
---
name: standards-validation
description: >
  Validation checklist for reviewing generated code against Druppie project
  coding standards and architecture patterns. Used by the Reviewer agent to
  ensure compliance.
allowed-tools:
  coding:
    - read_file
    - list_dir
---
```

To:

```yaml
---
name: standards-validation
description: >
  Validation checklist for reviewing generated code against Druppie project
  coding standards and architecture patterns. Used by the Reviewer agent to
  ensure compliance.
---
```

**Step 4: Commit**

```bash
git add druppie/opencode/
git add druppie/skills/fullstack-architecture/ druppie/skills/project-coding-standards/ druppie/skills/standards-validation/
git commit -m "refactor: move coding skills to druppie/opencode/skills for OpenCode native deployment"
```

---

### Task 2: Add `opencode_skills` field to AgentDefinition

**Files:**
- Modify: `druppie/domain/agent_definition.py:48`

**Step 1: Add the field**

In `druppie/domain/agent_definition.py`, add `opencode_skills` field after the existing `skills` field (line 48):

```python
    # Skills this agent can invoke (Druppie's own agent skill system)
    # List of skill names that match directories in druppie/skills/
    skills: list[str] = Field(default_factory=list)

    # OpenCode skills to deploy into sandbox for this agent
    # List of skill names that match directories in druppie/opencode/skills/
    opencode_skills: list[str] = Field(default_factory=list)
```

**Step 2: Commit**

```bash
git add druppie/domain/agent_definition.py
git commit -m "feat: add opencode_skills field to AgentDefinition"
```

---

### Task 3: Update builder.yaml to use opencode_skills

**Files:**
- Modify: `druppie/agents/definitions/builder.yaml:216-218`

**Step 1: Update the YAML**

In `builder.yaml`, change from:

```yaml
skills:
  - fullstack-architecture
  - project-coding-standards
```

To:

```yaml
opencode_skills:
  - fullstack-architecture
  - project-coding-standards
  - standards-validation
```

Note: `skills:` field is removed (these were the only skills assigned). `opencode_skills` now includes `standards-validation` as well since the builder should also have access to the validation checklist.

**Step 2: Commit**

```bash
git add druppie/agents/definitions/builder.yaml
git commit -m "feat: assign opencode_skills to builder agent"
```

---

### Task 4: Generalize agent files loader to opencode files

This task modifies the sandbox `__init__.py` which exists on `colab-dev` but NOT in the PR84 worktree. This code will need to be added to colab-dev after the PR is merged, or the PR needs to be rebased onto colab-dev first.

**Files:**
- Modify: `druppie/sandbox/__init__.py` (on colab-dev branch)

**Step 1: Add OpenCode skills loader function**

Add after the `_load_agent_files()` function (around line 35):

```python
_OPENCODE_SKILLS_DIR = Path(__file__).parent.parent / "opencode" / "skills"


def _load_opencode_files(agent_name: str) -> dict[str, str]:
    """Load all OpenCode files (agents + skills) for a sandbox session.

    Agent files are keyed as 'agents/{name}' and skill files as
    'skills/{name}/SKILL'. The sandbox entrypoint writes each entry
    to .opencode/{key}.md.
    """
    files: dict[str, str] = {}

    # Load agent markdown files (existing behavior, now with path prefix)
    if _AGENTS_DIR.is_dir():
        for f in _AGENTS_DIR.glob("*.md"):
            files[f"agents/{f.stem}"] = f.read_text()

    # Load OpenCode skills for this agent from YAML definition
    from druppie.agents.definition_loader import load_agent_definition

    agent_def = load_agent_definition(agent_name)
    if agent_def and agent_def.opencode_skills:
        for skill_name in agent_def.opencode_skills:
            skill_file = _OPENCODE_SKILLS_DIR / skill_name / "SKILL.md"
            if skill_file.exists():
                files[f"skills/{skill_name}/SKILL"] = skill_file.read_text()
            else:
                logger.warning(
                    "opencode_skill_not_found",
                    skill_name=skill_name,
                    agent=agent_name,
                )

    return files
```

**Step 2: Update `create_and_start_sandbox()` to use new loader**

In `create_and_start_sandbox()`, change (around line 148):

```python
    create_body = {
        "repoOwner": repo_owner,
        "repoName": repo_name,
        "model": model,
        "agentModels": model_config.agents,
        "agentFiles": _load_agent_files(),
        "modelChains": get_raw_model_chains(),
```

To:

```python
    create_body = {
        "repoOwner": repo_owner,
        "repoName": repo_name,
        "model": model,
        "agentModels": model_config.agents,
        "opencodeFiles": _load_opencode_files(agent_name),
        "modelChains": get_raw_model_chains(),
```

**Step 3: Commit**

```bash
git add druppie/sandbox/__init__.py
git commit -m "feat: generalize agent files loader to include OpenCode skills"
```

---

### Task 5: Update control plane router to accept opencodeFiles

**Files:**
- Modify: `vendor/open-inspect/packages/local-control-plane/src/router.ts:186`

**Step 1: Update router.ts**

Change line 186 from:

```typescript
      agentFiles: body.agentFiles ?? null,
```

To:

```typescript
      opencodeFiles: body.opencodeFiles ?? body.agentFiles ?? null,
```

The fallback to `body.agentFiles` ensures backwards compatibility during rollout.

**Step 2: Commit in submodule**

```bash
cd vendor/open-inspect
git add packages/local-control-plane/src/router.ts
git commit -m "feat: accept opencodeFiles in session creation (backwards-compat with agentFiles)"
```

---

### Task 6: Update session-instance to use opencodeFiles

**Files:**
- Modify: `vendor/open-inspect/packages/local-control-plane/src/session/session-instance.ts`

**Step 1: Rename the field declaration (line 174)**

Change:

```typescript
  private agentFiles: Record<string, string> | null = null;
```

To:

```typescript
  private opencodeFiles: Record<string, string> | null = null;
```

**Step 2: Update handleInit (line 1368)**

Change:

```typescript
    this.agentFiles = body.agentFiles ?? null;
```

To:

```typescript
    this.opencodeFiles = body.opencodeFiles ?? null;
```

**Step 3: Update spawn env var (lines 1098-1099 and 1185-1186)**

Both occurrences, change from:

```typescript
      if (this.agentFiles) {
        userEnvVars["SANDBOX_AGENT_FILES"] = JSON.stringify(this.agentFiles);
      }
```

To:

```typescript
      if (this.opencodeFiles) {
        userEnvVars["SANDBOX_OPENCODE_FILES"] = JSON.stringify(this.opencodeFiles);
      }
```

**Step 4: Commit in submodule**

```bash
cd vendor/open-inspect
git add packages/local-control-plane/src/session/session-instance.ts
git commit -m "feat: rename agentFiles to opencodeFiles with SANDBOX_OPENCODE_FILES env var"
```

---

### Task 7: Update sandbox entrypoint to write generalized opencode files

**Files:**
- Modify: `vendor/open-inspect/packages/modal-infra/src/sandbox/entrypoint.py:332-344`

**Step 1: Replace agent files deployment block**

Change lines 332-344 from:

```python
        # Deploy agent definition .md files into .opencode/agents/
        agent_files_json = os.environ.get("SANDBOX_AGENT_FILES", "")
        agent_files = json.loads(agent_files_json) if agent_files_json else {}
        if agent_files:
            agents_dir = opencode_dir / "agents"
            agents_dir.mkdir(parents=True, exist_ok=True)
            for name, content in agent_files.items():
                (agents_dir / f"{name}.md").write_text(content)
            self.log.info(
                "opencode.agent_files_deployed",
                count=len(agent_files),
                agents=list(agent_files.keys()),
            )
```

To:

```python
        # Deploy OpenCode files (.opencode/{key}.md) — agents, skills, etc.
        opencode_files_json = os.environ.get("SANDBOX_OPENCODE_FILES") or os.environ.get("SANDBOX_AGENT_FILES", "")
        opencode_files = json.loads(opencode_files_json) if opencode_files_json else {}
        if opencode_files:
            for key, content in opencode_files.items():
                target = opencode_dir / f"{key}.md"
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content)
            self.log.info(
                "opencode.files_deployed",
                count=len(opencode_files),
                keys=list(opencode_files.keys()),
            )
```

The `SANDBOX_AGENT_FILES` fallback ensures backwards compatibility. The key insight: `agents/druppie-builder` → `.opencode/agents/druppie-builder.md` (same as before), `skills/fullstack-architecture/SKILL` → `.opencode/skills/fullstack-architecture/SKILL.md` (new).

**Step 2: Commit in submodule**

```bash
cd vendor/open-inspect
git add packages/modal-infra/src/sandbox/entrypoint.py
git commit -m "feat: generalize opencode file deployment to support skills subdirectory"
```

---

### Task 8: Add skill permissions to OpenCode config

**Files:**
- Modify: `vendor/open-inspect/packages/modal-infra/src/sandbox/entrypoint.py:277-284`

**Step 1: Add skill permission**

Change lines 277-284 from:

```python
        opencode_config = {
            "model": model,
            "permission": {
                "*": {
                    "*": "allow",
                },
            },
        }
```

To:

```python
        opencode_config = {
            "model": model,
            "permission": {
                "*": {
                    "*": "allow",
                },
                "skill": {
                    "*": "allow",
                },
            },
        }
```

**Step 2: Commit in submodule**

```bash
cd vendor/open-inspect
git add packages/modal-infra/src/sandbox/entrypoint.py
git commit -m "feat: add skill permissions to OpenCode config"
```

---

### Task 9: Verify end-to-end

**Step 1: Check skill file contents are valid OpenCode format**

Verify each SKILL.md in `druppie/opencode/skills/` has valid frontmatter with only `name` and `description` (no `allowed-tools`):

```bash
head -10 druppie/opencode/skills/*/SKILL.md
```

**Step 2: Verify agent YAML loads correctly**

```bash
cd druppie && python -c "
from agents.definition_loader import load_agent_definition
d = load_agent_definition('builder')
print('opencode_skills:', d.opencode_skills)
print('skills:', d.skills)
"
```

Expected: `opencode_skills: ['fullstack-architecture', 'project-coding-standards', 'standards-validation']`, `skills: []`

**Step 3: Final commit with all changes**

```bash
git add -A
git status
# Review, then push
git push origin feature/project-coding-standards
```
