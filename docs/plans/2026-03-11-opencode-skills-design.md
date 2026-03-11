# OpenCode Native Skills for Sandbox Agents

**Date:** 2026-03-11
**Branch:** feature/project-coding-standards (PR #84)

## Problem

PR #84 added coding skills (fullstack-architecture, project-coding-standards, standards-validation) as Druppie "core skills" — loaded via a custom `invoke_skill` builtin tool and `SkillService`. But OpenCode has a native skill system (`.opencode/skills/<name>/SKILL.md`) that provides discovery, permissions, and on-demand loading. We should use that instead of reinventing it.

## Design

### Two Skill Systems

- **`druppie/skills/`** — Skills for Druppie's own agents (architect, builder, reviewer running in the LangGraph loop). These stay as-is and use the existing `invoke_skill` builtin tool.
- **`druppie/opencode/skills/`** — Skills for OpenCode coding agents running in sandboxes. These get deployed as `.opencode/skills/<name>/SKILL.md` and use OpenCode's native `skill` tool.

### Skill File Location

Move three skills from `druppie/skills/` to `druppie/opencode/skills/`:

```
druppie/opencode/
└── skills/
    ├── fullstack-architecture/SKILL.md
    ├── project-coding-standards/SKILL.md
    └── standards-validation/SKILL.md
```

Strip `allowed-tools` from frontmatter (OpenCode doesn't support it).

### Generalize `SANDBOX_AGENT_FILES` → `SANDBOX_OPENCODE_FILES`

Currently the pipeline is:

1. `druppie/sandbox/__init__.py` loads `.md` files from `sandbox-config/agents/`
2. Passes as `agentFiles: {"druppie-builder": "..."}` to control plane
3. Control plane sets `SANDBOX_AGENT_FILES` env var
4. Sandbox entrypoint writes to `.opencode/agents/{name}.md`

**Change:** Generalize this to support any `.opencode/` subdirectory. The env var becomes `SANDBOX_OPENCODE_FILES` with path-based keys:

```json
{
  "agents/druppie-builder": "# Builder instructions...",
  "agents/druppie-tester": "# Tester instructions...",
  "skills/fullstack-architecture/SKILL": "---\nname: fullstack-architecture\n...",
  "skills/project-coding-standards/SKILL": "---\nname: project-coding-standards\n..."
}
```

The entrypoint writes each entry to `.opencode/{key}.md`, creating subdirectories as needed.

### Loading Skills per Agent

Agent YAML definitions get an `opencode_skills` field:

```yaml
# builder.yaml
opencode_skills:
  - fullstack-architecture
  - project-coding-standards
  - standards-validation
```

When creating a sandbox session, `druppie/sandbox/__init__.py`:
1. Loads agent `.md` files (existing behavior, keys prefixed with `agents/`)
2. Reads the active agent's `opencode_skills` list from its YAML definition
3. Loads matching SKILL.md files from `druppie/opencode/skills/`
4. Adds them to the payload with keys like `skills/{name}/SKILL`

### OpenCode Config

Add skill permissions to the generated `opencode.json`:

```json
{
  "permission": {
    "*": { "*": "allow" },
    "skill": { "*": "allow" }
  }
}
```

### What Gets Removed from Core

From PR #84's additions, remove from `druppie/skills/`:
- `fullstack-architecture/SKILL.md` (moved to `druppie/opencode/skills/`)
- `project-coding-standards/SKILL.md` (moved)
- `standards-validation/SKILL.md` (moved)

Update `builder.yaml`: remove these from `skills:` field, add to `opencode_skills:` field.

The `invoke_skill` builtin tool and `SkillService` stay for Druppie's own agent skills.

## Changes Required

### Druppie Backend (PR #84 worktree)

1. **Create `druppie/opencode/skills/`** — move three SKILL.md files, strip `allowed-tools`
2. **Update `builder.yaml`** — remove skills from `skills:`, add `opencode_skills:` field
3. **Update `druppie/domain/agent_definition.py`** — add `opencode_skills: list[str]` field

### Druppie Backend (colab-dev, sandbox code)

4. **Update `druppie/sandbox/__init__.py`**:
   - New `_load_opencode_skills(skill_names: list[str])` function
   - Modify `_load_agent_files()` to prefix keys with `agents/`
   - Combine agent files + skill files into single `opencode_files` dict
   - Pass as `opencodeFiles` (renamed from `agentFiles`) in session creation body

### Control Plane (vendor/open-inspect)

5. **Update `session-instance.ts`** — rename `agentFiles` → `opencodeFiles`, env var → `SANDBOX_OPENCODE_FILES`
6. **Update `router.ts`** — pass `opencodeFiles` from request body

### Sandbox Entrypoint (vendor/open-inspect)

7. **Update `entrypoint.py`** — read `SANDBOX_OPENCODE_FILES`, write to `.opencode/{key}.md` with subdirectory creation
8. **Update config generation** — add `skill: {"*": "allow"}` to permissions

## Data Flow

```
druppie/opencode/skills/fullstack-architecture/SKILL.md
         │
         ▼
_load_opencode_skills(["fullstack-architecture", ...])
         │
         ▼
{"agents/druppie-builder": "...", "skills/fullstack-architecture/SKILL": "..."}
         │
         ▼  (POST /sessions body.opencodeFiles)
Control Plane session-instance.ts
         │
         ▼  (SANDBOX_OPENCODE_FILES env var)
Sandbox entrypoint.py
         │
         ▼  (writes to .opencode/{key}.md)
.opencode/agents/druppie-builder.md
.opencode/skills/fullstack-architecture/SKILL.md
         │
         ▼  (OpenCode discovers natively)
Agent calls: skill({ name: "fullstack-architecture" })
