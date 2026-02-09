# Skills Integration Plan

## Phase 1: Prompt Injection with Tool Access ✅ IMPLEMENTED

Skills are markdown files that get injected into agent conversations when invoked.
Skills can also grant temporary access to MCP tools.

### File Structure

```
druppie/
└── skills/
    ├── code-review/
    │   └── SKILL.md
    └── git-workflow/
        └── SKILL.md
```

### SKILL.md Format

```yaml
---
name: code-review
description: Reviews code for quality and security
allowed-tools:
  coding:
    - read_file
    - list_dir
  bestand-zoeker:
    - read_file
    - search_files
---
# Code Review Instructions

You are performing a code review. Follow these steps:

1. Read the files to be reviewed
2. Check for security issues
3. Check for code quality
4. Provide actionable feedback
```

### Domain Model

```python
# druppie/domain/skill.py

class SkillSummary(BaseModel):
    name: str
    description: str

class SkillDetail(SkillSummary):
    prompt_content: str  # Markdown body
    allowed_tools: dict[str, list[str]] = {}  # mcp -> [tools]
```

### Skill Service

```python
# druppie/services/skill_service.py

class SkillService:
    def discover_skills(self) -> list[SkillSummary]:
        """Scan skills/ directory, return name + description"""

    def get_skill(self, name: str) -> SkillDetail:
        """Load full skill content including allowed_tools"""

    def get_skills_for_agent(self, agent_skills: list[str]) -> list[SkillSummary]:
        """Get skills available to an agent"""
```

### Agent YAML

```yaml
# druppie/agents/definitions/developer.yaml
id: developer
skills:
  - code-review
  - git-workflow
```

### Builtin Tool

```python
# druppie/agents/builtin_tools.py

async def invoke_skill(skill_name: str, ...) -> dict:
    """Load skill and return content + tool descriptions"""
    skill = skill_service.get_skill(skill_name)
    result = {
        "instructions": skill.prompt_content,
        "allowed_tools": skill.allowed_tools,
    }
    if skill.allowed_tools:
        result["available_tools"] = generate_tool_descriptions(skill.allowed_tools)
    return result
```

### Tool Access Check

```python
# druppie/execution/tool_executor.py

# When executing a tool:
# 1. Check if agent has direct access via agent.yaml mcps
# 2. If not, check if any previously invoked skill grants access
# 3. Approval rules from agent.yaml still apply!
```

### Integration Flow

1. Agent system prompt includes list of available skills
2. Agent calls `invoke_skill("code-review")`
3. Response includes: instructions + tool descriptions for allowed-tools
4. Agent can now use tools from allowed-tools (e.g., `coding:read_file`)
5. ToolExecutor checks: direct access? No. Skill access? Yes. Execute.
6. Approval rules from agent.yaml still apply (skills don't bypass approvals)

---

## Possible Future Phases

- Argument substitution (`$ARGUMENTS`, `$0`, `$1`)
- `scripts/` folder and `{baseDir}` expansion
- Dynamic injection (`!`command``)
- `context: fork` for subagent execution
- Hooks (before/after skill)
- Hot-reload via filesystem watchers
- Context budget management
