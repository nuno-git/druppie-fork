# 05 — Agents

The agent system: how agents are defined, loaded, prompted, run, and coordinated.

## Files

- [lifecycle.md](lifecycle.md) — From user message to summarizer, session-level lifecycle
- [orchestrator.md](orchestrator.md) — `druppie/execution/orchestrator.py` responsibilities
- [tool-executor.md](tool-executor.md) — `druppie/execution/tool_executor.py`: approvals, HITL, injection, MCP dispatch
- [agent-loop.md](agent-loop.md) — `druppie/agents/loop.py` in-process LLM + tool loop
- [builtin-tools.md](builtin-tools.md) — 10 builtin tools with schemas
- [system-prompts.md](system-prompts.md) — The four prompt snippets every agent composes
- [llm-profiles.md](llm-profiles.md) — `cheap` / `standard` / `ollama` provider chains
- [skills.md](skills.md) — `druppie/skills/*/SKILL.md` prompt modules
- [templates.md](templates.md) — `druppie/templates/project/` stub
- [definitions/](definitions/) — one file per agent YAML

## Agent inventory (15)

| Agent | Category | LLM profile | Role |
|-------|----------|-------------|------|
| router | system | cheap | Classifies intent |
| planner | system | cheap | Creates + re-evaluates agent execution plan |
| build_classifier | system | cheap | CORE_UPDATE vs STANDALONE |
| business_analyst | execution | cheap | Functional design (functional_design.md) |
| architect | execution | standard | Technical design (technical_design.md) |
| builder_planner | execution | standard | Implementation plan (builder_plan.md) |
| test_builder | execution | standard | Generate tests (TDD red) |
| builder | execution | standard | Implement code (TDD green) |
| test_executor | execution | standard | Run tests, report PASS/FAIL |
| developer | execution | standard | Branch management, merges, improvements |
| deployer | deployment | standard | docker compose build/deploy |
| update_core_builder | execution | standard | Modifies Druppie itself, opens PR |
| reviewer | quality | standard | Produces REVIEW.md |
| summarizer | system | cheap | User-facing completion message |

(The `llm_profiles.yaml` file is not an agent.)
