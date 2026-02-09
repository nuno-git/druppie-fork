# Skills Integration Plan

## Phase 1: Simple Prompt Injection

Skills are markdown files that get injected into agent conversations when invoked. That's it.

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
```

### Skill Service

```python
# druppie/services/skill_service.py

class SkillService:
    def discover_skills(self) -> list[SkillSummary]:
        """Scan skills/ directory, return name + description"""

    def get_skill(self, name: str) -> SkillDetail:
        """Load full skill content"""

    def get_skills_for_agent(self, agent_id: str) -> list[SkillSummary]:
        """Get skills this agent can use (from agent YAML)"""
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

def invoke_skill(skill_name: str) -> str:
    """Load skill and return its content for injection"""
    skill = skill_service.get_skill(skill_name)
    return skill.prompt_content
```

### Integration

1. Agent system prompt includes list of available skills
2. Agent calls `invoke_skill` tool when relevant
3. Skill content returned and injected into conversation
4. Agent follows the injected instructions

---

## Possible Future Phases

- Argument substitution (`$ARGUMENTS`, `$0`, `$1`)
- `allowed-tools` for temporary auto-approval
- `scripts/` folder and `{baseDir}` expansion
- Dynamic injection (`!`command``)
- `context: fork` for subagent execution
- Hooks (before/after skill)
- Hot-reload via filesystem watchers
- Context budget management
