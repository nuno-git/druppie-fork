# Skills

`druppie/skills/*/SKILL.md` — markdown prompt modules agents load on demand via the `invoke_skill` builtin tool.

## Directory layout

```
druppie/skills/
├── architecture-principles/
│   └── SKILL.md
├── code-review/
│   └── SKILL.md
├── git-workflow/
│   └── SKILL.md
├── making-mermaid-diagrams/
│   └── SKILL.md
└── module-convention/
    └── SKILL.md
```

## SKILL.md frontmatter

Each file has a YAML frontmatter block:

```yaml
---
name: making-mermaid-diagrams
description: Mermaid syntax rules and validation checklist
allowed_tools: [coding:read_file, coding:make_design, coding:validate_design]
---

# Making Mermaid Diagrams

(Body with instructions, examples, common mistakes…)
```

Frontmatter fields:
- `name` (string) — matches the directory name.
- `description` (string) — shown in `get_skill()` results from the registry MCP.
- `allowed_tools` (list) — tools the skill's instructions are expected to reference. Purely documentary today; no enforcement.

Body is free-form markdown. It becomes the value the `invoke_skill` handler returns to the agent.

## The 5 skills

### `architecture-principles`
22 Water Authority architecture principles (from NORA / enterprise standards). Agent cites principles by number in `technical_design.md`. Used by architect.

### `code-review`
Code review checklist: quality, security, test coverage, NFRs, best practices. Used by reviewer and developer.

### `git-workflow`
Branch naming, commit conventions, PR creation, merge strategy, conflict resolution. Used by developer.

### `making-mermaid-diagrams`
Mermaid syntax cheat sheet for flowcharts, sequence, class, ER, state diagrams. Common pitfalls (labels with special chars, arrow variants). Used by architect and business_analyst for design docs.

### `module-convention`
Full MCP module creation spec. The authoritative source summarised in `04-mcp-servers/module-convention.md`. Used by architect when designing a new module and by update_core_builder when implementing one.

## Loading mechanism

`druppie/services/skill_service.py:SkillService.load(name)`:
1. Read `druppie/skills/{name}/SKILL.md`.
2. Parse frontmatter with PyYAML.
3. Return a `SkillDefinition(name, description, allowed_tools, body)`.

Cached at startup; reloading requires a backend restart.

## `invoke_skill` handler

When an agent calls `invoke_skill(skill_name="making-mermaid-diagrams")`:
1. Handler fetches the skill body via `SkillService.load`.
2. Returns the body string as the tool call result.
3. The agent's next LLM call includes the body as a `tool` message.

The skill is effectively a "mid-run prompt extension" — the agent asks for more guidance and gets a chunk of instructions injected into its context.

## Why skills vs embedding in system prompt

- Skills are loaded on-demand, keeping system prompts short.
- Agents that don't need a skill don't pay the token cost.
- Skills are shared across agents — changing `making-mermaid-diagrams` benefits everyone who calls it.
- Skills are discoverable via the registry MCP — agents that are curious can enumerate them before deciding which to invoke.

## Agents that can invoke skills

`approval_overrides` aside, only agents with `invoke_skill` in their builtin_tools list can call it:

| Agent | Skills typically invoked |
|-------|-------------------------|
| architect | architecture-principles, making-mermaid-diagrams, module-convention |
| business_analyst | making-mermaid-diagrams |
| developer | code-review, git-workflow |
| reviewer | code-review |

## Writing a new skill

1. Create `druppie/skills/<name>/SKILL.md` with frontmatter.
2. Update the `invoke_skill` tool schema's enum to include the new name (in `builtin_tools.py`).
3. Add `invoke_skill` to the relevant agents' `builtin_tools` list if missing.
4. Restart backend.
