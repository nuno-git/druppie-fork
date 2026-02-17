---
name: making-mermaid-diagrams
description: >
  This skill should be used when creating a Mermaid diagram to visualize
  a process, architecture, data flow, component structure, or deployment
  view. It provides diagram type selection, syntax guidance, and styling
  conventions.
---

# Making Mermaid Diagrams

Create a diagram when a process has branching logic, multiple components
interact, or the text alone would be ambiguous. Do not create a diagram
for linear processes, trivial structures (2-3 nodes), or abstract
concepts better described in text.

## Diagram Type Selection

| What to visualize | Mermaid keyword |
|-------------------|-----------------|
| Process with decisions / user journey | `flowchart TD` |
| Component relationships | `graph TD` or `graph LR` |
| Data flow between systems | `flowchart LR` |
| Interaction sequence between actors | `sequenceDiagram` |
| System states and transitions | `stateDiagram-v2` |

Use **TD** (top-down) for processes and workflows. Use **LR**
(left-right) for data flows and component architectures.

## Style Conventions

**Node shapes:**

| Syntax | Use for |
|--------|---------|
| `A([Label])` | Start / end / terminal events |
| `A[Label]` | Process steps, actions, components |
| `A{Label}` | Decision points, conditions |
| `A((Label))` | Stop / end points |

**Labels and edges:**
- Short descriptive labels (3-6 words), verb-first for actions
- Always label decision edges with their condition
- Use quotes for special characters: `-- "Yes, approved" -->`

**Readability:**
- Maximum **15-20 nodes** per diagram — split if larger
- Use subgraphs to group distinct phases
- Minimize edge crossings by reordering nodes

## Functional vs Technical Diagrams

**Functional diagrams** visualize what happens from the user's
perspective. Include user actions, system responses, decision points, and
success/failure paths. Exclude implementation details — the diagram
should be solution-agnostic.

**Technical diagrams** visualize how the system is built. Include
components, data flows with direction and content, security boundaries,
and deployment topology. Exclude abstract reasoning better suited to text.

## Quality Checklist

- [ ] Diagram adds clarity beyond the surrounding text
- [ ] All decision edges are labeled
- [ ] 15 or fewer nodes (or split into parts)
- [ ] Start/end points use distinct shapes
- [ ] Diagram matches the text — no contradictions
- [ ] Consistent abstraction level throughout
