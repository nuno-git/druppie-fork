# architect

File: `druppie/agents/definitions/architect.yaml` (734 lines).

## Role

Technical design authoring and architecture review. Takes the BA's `functional_design.md` and produces `technical_design.md` — the second approval-gated artifact.

## Config

| Field | Value |
|-------|-------|
| category | execution |
| llm_profile | standard |
| temperature | 0.2 |
| max_tokens | 100000 |
| max_iterations | 50 |
| builtin tools | `invoke_skill`, `execute_coding_task` (explore only), + default |
| MCPs | `coding`, `registry`, `archimate` |
| skills | making-mermaid-diagrams, architecture-principles, module-convention |
| approval_overrides | `coding:make_design` → `architect` role |

## Four modes

1. **general_chat** — architecture questions, NORA principles, workflow visualization. May route to business_analyst or summarizer.
2. **create_project** — integral architecture check → approve / feedback / reject.
3. **update_project** — two sub-modes:
   - If BA returned NO_FD_CHANGE → technical-fix review (validate existing code against architecture).
   - If DESIGN_APPROVED with updated FD → update existing technical_design.md.
4. **Re-review** — after BA revision, check if feedback items resolved.

## Three context levels

The agent prompt describes three tiers of discovery:

1. **Level 1 — instant** — `registry_list_modules()`, `registry_get_module(id)`. Use first, always.
2. **Level 2 — instant** — `coding_list_projects()`, `coding_read_project_file(path, repo_name)`. Cross-project lookups.
3. **Level 3 — sandbox** — `execute_coding_task(agent="explore", task="...")`. For deep code exploration of Druppie core or large projects. MANDATORY for CORE_UPDATE + complex reuse decisions.

## `technical_design.md` structure

Written in Dutch. Sections:
1. Introduction
2. Solution overview
3. Applied NORA principles per layer (Business / Application / Information / Technology)
4. Requirements table (FR/NFR/TR) mapped to FD items
5. Component Structure (modules, services, APIs)
6. Data Architecture (schema, retention, privacy)
7. Infrastructure (containers, networks, DB, scaling)
8. Security by Design (auth, permissions, secrets)
9. Compliance by Design (GDPR, audit logs, retention)
10. Visualisation (ArchiMate-inspired diagrams in Mermaid)
11. Module Samenvatting (if creating a new MCP module)

## Approval gate

Override: `coding:make_design` → `architect` role. Another architect (or admin) approves the TD before implementation begins.

## Deterministic routing

After the TD is approved, the architect emits:
```
done(summary="Agent architect: wrote technical_design.md … DESIGN_APPROVED",
     next_agent="build_classifier")
```

Bypasses the planner. The build_classifier then routes to builder_planner or update_core_builder.

If feedback (from another architect's rejection or from the session_owner), the architect emits `DESIGN_FEEDBACK` in the summary with a concrete revision list, and the planner routes back to business_analyst (for functional changes) or queues another architect run (for technical revisions).

## ArchiMate integration

For projects that touch enterprise architecture, the architect queries the `archimate` MCP:
- `archimate:list_models` — available models in `/models` volume.
- `archimate:search_model` — find elements by name/description.
- `archimate:get_impact` — downstream change analysis.

Cited elements are referenced by ID in `technical_design.md`.

## Module creation

If the functional design implies a new module, the architect writes a "Module Samenvatting" in the TD specifying:
- Module ID and name.
- Public API (tool signatures).
- Internal design.
- Version strategy.

The `update_core_builder` agent uses this spec verbatim when implementing the module (following `module-convention` skill).
