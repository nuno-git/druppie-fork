---
id: "031"
title: Hybrid ArchiMate + Mermaid diagramming strategy
status: accepted
date: 2026-07-17
deciders:
  - nuno
supersedes: null
superseded_by: null
linked_prd: docs/prds/021-archimate-v2-roadmap.md
linked_research: null
---

# ADR 031: Hybrid ArchiMate + Mermaid diagramming strategy

## Context

The architect agent produces technical designs (TDs) that include diagrams. Until PR #215, the only supported diagram format was Mermaid. Mermaid handles sequence diagrams, flowcharts, state diagrams, and ER diagrams well, but it cannot express layered architecture views. Water management systems need diagrams that show business processes, application components, technology infrastructure, and the cross-layer relationships between them. The architect agent had no way to produce these structural views, which limited the quality of technical designs for projects that span business, application, and technology layers.

## Decision

Adopt a hybrid diagramming strategy where the architect agent uses both ArchiMate and Mermaid, choosing the right tool per diagram type:

- **ArchiMate** for structural and cross-layer blueprints: application landscape diagrams, technology layer views, business-IT alignment views, and any diagram where the primary value is showing static structure and layered relationships.
- **Mermaid** for dynamic and relational diagrams: sequence diagrams, state machines, flowcharts, entity-relationship diagrams, and any diagram where the primary value is showing flow, state transitions, or process order.

Build a new MCP server (`module-archimate write-MCP`) that gives the architect agent tools to create and modify ArchiMate models. The server provides two categories of tools:

- **One-shot view-builders** (`add_layered_view`, `add_cooperation_view`) that produce a complete diagram in a single call. These are the primary interface for the architect agent.
- **Primitive create/add tools** for incremental edits to existing models.

Store each project's ArchiMate model as `docs/architecture.archimate` in the project's own repository. This keeps the model version-controlled alongside code, with the same access model as every other project artifact.

Render ArchiMate views inline in `docs/technical-design.md` via a view-id reference. The frontend TD viewer resolves the reference and renders the ArchiMate diagram alongside any Mermaid diagrams in the same document. SVG export uses real ArchiMate notation: proper shapes per element type, type icons, and color coding per layer.

Elements in ArchiMate models can reference pre-defined WILMA architectural elements via `wilma_id`, enabling reuse of the WILMA reference model across projects.

## Consequences

Positive: complete diagramming coverage for technical designs (structure via ArchiMate, flow via Mermaid). ArchiMate models are version-controlled in the project repo. WILMA reference model reuse ensures consistency across projects. Inline TD rendering gives the architect immediate visual feedback.

Negative: the architect agent must choose the right tool per diagram type, adding a decision step to diagram creation. Two different rendering engines must be maintained (Mermaid and the ArchiMate toolchain). ArchiMate XML is verbose, making model files larger than equivalent Mermaid definitions. SVG export quality depends on the ArchiMate toolchain implementation.
