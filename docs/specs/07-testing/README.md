# 07 — Testing

Druppie's evaluation framework tests agents at three levels and stores results in a queryable schema.

## Files

- [evaluation-framework.md](evaluation-framework.md) — Runner, bounded orchestrator, replay executor
- [tool-tests.md](tool-tests.md) — YAML schema + flow for tool-level tests
- [agent-tests.md](agent-tests.md) — YAML schema + flow for agent-level tests
- [judge-system.md](judge-system.md) — LLM judge, judge eval, context extraction
- [hitl-simulator.md](hitl-simulator.md) — Persona-driven HITL answering
- [schemas.md](schemas.md) — Pydantic schemas for test definitions
- [e2e-tests.md](e2e-tests.md) — Frontend Playwright suite
- [pytest.md](pytest.md) — Backend unit tests

## Three evaluation tiers

1. **Tool tests** (`testing/tools/*.yaml`) — define a chain of tool calls; replay through real MCP servers (no LLM). Fastest feedback loop.
2. **Agent tests** (`testing/agents/*.yaml`) — run real agents with real LLMs + personas answering HITLs. Slower but faithful.
3. **Judge checks** (in both) — LLM evaluates agent output against natural-language criteria.

## Why this matters

Druppie's agents make high-stakes decisions (design approvals, code deploys). Evaluation has to exercise:
- Tool-call correctness (did the agent call the right MCP?).
- Pipeline integrity (did the right agents run in the right order?).
- Qualitative outputs (is the design comprehensive? Did the builder write good code?).

Traditional pytest catches none of this. The evaluation framework is the answer.
