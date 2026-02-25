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

## Critical Rule: One Shape Per Node

Each Mermaid node has EXACTLY ONE shape defined by ONE delimiter pair.
Count the delimiter pairs around the label — if you count two or more,
the node is broken.

How to count: each of `[`, `(`, `{` that is part of the shape syntax
counts as one opening delimiter. The matching closing delimiter completes
the pair. A valid node has exactly ONE pair (or one double like `((`
which is a single shape).

Valid — one delimiter pair each:
```
A["Label"]     %% [ ] = rectangle — 1 pair
B(["Label"])   %% ([ ]) = stadium — 1 pair
C[("Label")]   %% [( )] = cylinder — 1 pair
D(("Label"))   %% (( )) = circle — 1 pair
E{"Label"}     %% { } = diamond — 1 pair
```

**BROKEN** — two delimiter pairs combined:
```
X[(("Label"))]   %% [( + (( = 2 pairs — BROKEN
Y([("Label")])   %% ([ + ( = 2 pairs — BROKEN
Z([["Label"]])   %% ([ + [[ = 2 pairs — BROKEN
```

**The fix is always the same:** look up the ONE shape you want from the
table below and use ONLY that delimiter. Remove any extra delimiters.

## Node Shapes — Complete Reference

| Syntax | Shape | Use for |
|--------|-------|---------|
| `A["Label"]` | Rectangle | Process steps, actions, components |
| `A("Label")` | Rounded rectangle | General steps |
| `A(["Label"])` | Stadium | Start / end / terminal events |
| `A{"Label"}` | Diamond | Decision points, conditions |
| `A{{"Label"}}` | Hexagon | Preparation steps |
| `A[["Label"]]` | Subroutine | Sub-processes |
| `A(("Label"))` | Circle | Stop / end points |
| `A[("Label")]` | Cylinder | Database / storage |

These eight shapes are the ONLY valid options. Copy the delimiter pattern
exactly from this table. Do not invent new combinations.

## Node Planning (do this BEFORE writing diagram code)

Before writing any Mermaid code, plan each node in a list:

```
Nodes:
- start: stadium (["Label"])
- validate: diamond {"Label"}
- process: rectangle ["Label"]
- db: cylinder [("Label")]
- finish: stadium (["Label"])
```

Then write the diagram using ONLY the delimiters from your plan. This
prevents mixing shapes during writing.

## Diagram Type Selection

| What to visualize | Mermaid keyword |
|-------------------|-----------------|
| Process with decisions / user journey | `flowchart TD` |
| Component relationships | `flowchart TD` or `flowchart LR` |
| Data flow between systems | `flowchart LR` |
| Interaction sequence between actors | `sequenceDiagram` |
| System states and transitions | `stateDiagram-v2` |

Use **TD** (top-down) for processes and workflows. Use **LR**
(left-right) for data flows and component architectures.

## Edges and Arrows

| Syntax | Type |
|--------|------|
| `A --> B` | Solid arrow |
| `A --- B` | Solid line (no arrow) |
| `A -.-> B` | Dotted arrow |
| `A ==> B` | Thick arrow |
| `A <--> B` | Bidirectional arrow |

Label edges with `A -->|"Label text"| B`. Always quote the label text.

## Subgraphs

```
subgraph sg1["Group Name"]
    A["Step 1"] --> B["Step 2"]
end
```

## Syntax Rules

1. **Never use `end` as a node ID.** It is reserved. Use `finish` or
   similar instead.

2. **Always quote labels** with plain ASCII double quotes: `A["Label"]`.
   Mermaid does not support backslash escaping — `\"` is a parse error.

3. **Node IDs must be alphanumeric** (`A-Z`, `a-z`, `0-9`, `_`).

4. **Use ASCII characters only.** No smart quotes, em dashes, or unicode
   arrows.

5. **Unique node IDs.** Reuse the same ID to reference a node in
   multiple edges.

6. **Line breaks** in labels: use `<br/>` inside quoted labels.

7. **Max 15 nodes** per diagram. Split into multiple diagrams if larger.

## Functional vs Technical Diagrams

**Functional diagrams** visualize what happens from the user's
perspective. Include user actions, system responses, decision points, and
success/failure paths. Exclude implementation details — the diagram
should be solution-agnostic.

**Technical diagrams** visualize how the system is built. Include
components, data flows with direction and content, security boundaries,
and deployment topology. Exclude abstract reasoning better suited to text.

## Complete Example

```mermaid
flowchart TD
    start(["Start"]) --> input["Receive request"]
    input --> validate{"Valid request?"}
    validate -->|"Yes"| process["Process data"]
    validate -->|"No"| reject["Return error"]
    process --> store[("Save to database")]
    store --> notify["Send notification"]
    notify --> finish(["Done"])
    reject --> finish
```

## Self-Verification (do this before outputting any diagram)

After writing your Mermaid code, verify EVERY node before including it
in your output:

1. **Delimiter count:** For each node, count delimiter pairs. If any
   node has more than one pair, it is BROKEN — fix it by looking up the
   correct shape from the Node Shapes table.
   Valid delimiters: `[""]` `("")` `([""])` `{""}` `{{""}}` `[[""]]`
   `((""))` `[("")]`

2. **Quote check:** All labels use plain ASCII `"` — no `\"` escaping.

3. **Edge labels:** All decision edges have labels: `-->|"label"|`

4. **Reserved words:** No node ID is the bare word `end`.

5. **Node IDs:** All alphanumeric (`A-Z`, `a-z`, `0-9`, `_`).

If any check fails, fix the node before outputting the diagram.
