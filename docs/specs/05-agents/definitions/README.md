# Agent Definitions

One doc per agent YAML in `druppie/agents/definitions/`. Each describes:
- Role, category, LLM profile.
- MCPs and builtin tools used.
- System prompt intent.
- Approval overrides.
- Unique behaviour (branching logic, routing decisions, modes).

## Index

### System (5)
- [router.md](router.md) — Intent classification
- [planner.md](planner.md) — Execution plan construction and re-evaluation
- [build_classifier.md](build_classifier.md) — CORE_UPDATE vs STANDALONE
- [summarizer.md](summarizer.md) — User-facing completion message

### Requirements & Design (2)
- [business_analyst.md](business_analyst.md) — Functional design
- [architect.md](architect.md) — Technical design + architecture review

### Implementation (5)
- [builder_planner.md](builder_planner.md) — Implementation plan
- [test_builder.md](test_builder.md) — TDD red phase
- [builder.md](builder.md) — TDD green phase
- [test_executor.md](test_executor.md) — Run + report
- [update_core_builder.md](update_core_builder.md) — Modify Druppie itself

### Deployment & Quality (2)
- [deployer.md](deployer.md) — Docker compose + ask user
- [developer.md](developer.md) — Branch mgmt + improvements
- [reviewer.md](reviewer.md) — Code review (REVIEW.md)

The planner orchestrates these agents. Three routing mechanisms exist:
1. **Default** — planner re-evaluates after each agent (90% of transitions).
2. **Deterministic `next_agent`** — architect → build_classifier, build_classifier → builder_planner or update_core_builder.
3. **Agent-specific mode** — business_analyst has 5 modes, architect has 4, deployer has 3.
