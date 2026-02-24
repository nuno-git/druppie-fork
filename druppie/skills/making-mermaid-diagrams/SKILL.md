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
| Component relationships | `flowchart TD` or `flowchart LR` |
| Data flow between systems | `flowchart LR` |
| Interaction sequence between actors | `sequenceDiagram` |
| System states and transitions | `stateDiagram-v2` |

Use **TD** (top-down) for processes and workflows. Use **LR**
(left-right) for data flows and component architectures.

## Node Shapes

| Syntax | Shape | Use for |
|--------|-------|---------|
| `A["Label"]` | Rectangle | Process steps, actions, components |
| `A("Label")` | Rounded rectangle | General steps |
| `A(["Label"])` | Stadium | Start / end / terminal events |
| `A{"Label"}` | Diamond / rhombus | Decision points, conditions |
| `A{{"Label"}}` | Hexagon | Preparation steps |
| `A[["Label"]]` | Subroutine | Sub-processes |
| `A(("Label"))` | Circle | Stop / end points |
| `A[("Label")]` | Cylinder | Database / storage |

Always quote the label text inside the shape brackets to avoid syntax
<<<<<<< Updated upstream
errors: write `A["My label"]` not `A[My label]`.
=======
errors: write `A["My label"]` not `A[My label]`. Keep labels short:
3-6 words, verb-first for actions.
>>>>>>> Stashed changes

**NEVER nest shape characters.** Each node uses exactly one pair of shape
delimiters with a quoted label inside. Wrong examples:
- ~~`A([("Label")])`~~ — stadium `([` wrapping rounded `("` = broken
- ~~`A[("Label")]`~~ — rectangle `[` wrapping rounded `("` = broken
- ~~`A{("Label")}`~~ — diamond `{` wrapping rounded `("` = broken
<<<<<<< Updated upstream

Correct: pick the ONE shape you need from the table above and put the
quoted label directly inside it.

## Edges and Arrows

| Syntax | Type |
|--------|------|
| `A --> B` | Solid arrow |
| `A --- B` | Solid line (no arrow) |
| `A -.-> B` | Dotted arrow |
| `A -.- B` | Dotted line (no arrow) |
| `A ==> B` | Thick arrow |
| `A === B` | Thick line (no arrow) |
| `A <--> B` | Bidirectional arrow |

### Labeled edges

Two equivalent syntaxes — pick one and be consistent:

```
A -->|"Label text"| B
A -- "Label text" --> B
```

Always quote label text to avoid syntax errors with special characters.

## Subgraphs

```
subgraph sg1["Group Name"]
    direction LR  %% optional: override parent direction
    A["Step 1"] --> B["Step 2"]
end
```

## Critical Syntax Rules

1. **Never use `end` as a node ID or unquoted label.** The word `end`
   in lowercase is reserved and breaks the diagram. Always quote it:
   `A["End"]` or use a different ID like `finish["End"]`.

2. **Always quote labels.** Use `A["Label"]` instead of `A[Label]`.
   This prevents breakage from special characters like parentheses,
   colons, commas, and slashes.

3. **Do not start a node ID with `o` or `x` immediately after dashes.**
   `A---oB` creates a circle edge and `A---xB` creates a cross edge.
   Add a space: `A--- oB` or capitalize: `A---OB`.

4. **Use unique node IDs.** Every node must have a unique ID. Reuse the
   ID to reference the same node in multiple edges — do not create a
   new node with the same label but different ID.

5. **Line breaks in labels** use `<br/>` inside quoted labels:
   `A["First line<br/>Second line"]`. Only use this when a label would
   otherwise exceed 6 words on one line.

6. **Special characters in labels** require HTML entity codes:
   - `#35;` for `#`
   - `#34;` for `"`
   - `&amp;` for `&`

7. **Comments** use `%%`:
=======

Correct: pick the ONE shape you need from the table above and put the
quoted label directly inside it.

## Edges and Arrows

| Syntax | Type |
|--------|------|
| `A --> B` | Solid arrow |
| `A --- B` | Solid line (no arrow) |
| `A -.-> B` | Dotted arrow |
| `A -.- B` | Dotted line (no arrow) |
| `A ==> B` | Thick arrow |
| `A === B` | Thick line (no arrow) |
| `A <--> B` | Bidirectional arrow |

### Labeled edges

Two equivalent syntaxes — pick one and be consistent:

```
A -->|"Label text"| B
A -- "Label text" --> B
```

Always quote label text to avoid syntax errors with special characters.

## Subgraphs

```
subgraph sg1["Group Name"]
    direction LR  %% optional: override parent direction
    A["Step 1"] --> B["Step 2"]
end
```

## Critical Syntax Rules

1. **Never use `end` as a node ID or unquoted label.** The word `end`
   in lowercase is reserved and breaks the diagram. Always quote it:
   `A["End"]` or use a different ID like `finish["End"]`.

2. **Always quote labels with plain ASCII double quotes.** Use
   `A["Label"]` instead of `A[Label]`. Mermaid does not support
   backslash escaping — the `\` character has no meaning in mermaid
   syntax and `A[\"Label\"]` is a parse error. For literal double
   quotes inside a label, use the HTML entity `#quot;`.

3. **Node IDs must be alphanumeric.** Use only `A-Z`, `a-z`, `0-9`,
   and `_` in node IDs. Put all display text in the quoted label:
   `myNode["Display text with spaces"]`.

4. **Use ASCII characters only.** Do not use smart quotes (`""''`),
   em dashes (`—`), or unicode arrows (`→`). Use plain `"`, `--`,
   and `-->`.

5. **Use unique node IDs.** Every node must have a unique ID. Reuse the
   ID to reference the same node in multiple edges — do not create a
   new node with the same label but different ID.

6. **Line breaks in labels** use `<br/>` inside quoted labels:
   `A["First line<br/>Second line"]`. Only use this when a label would
   otherwise exceed 6 words on one line.

7. **Special characters in labels** require HTML entity codes:
   - `#35;` for `#`
   - `#quot;` for `"`
   - `&amp;` for `&`

8. **Comments** use `%%`:
>>>>>>> Stashed changes
   ```
   %% This is a comment
   A["Start"] --> B["End point"]
   ```

## Functional vs Technical Diagrams

**Functional diagrams** visualize what happens from the user's
perspective. Include user actions, system responses, decision points, and
success/failure paths. Exclude implementation details — the diagram
should be solution-agnostic.

**Technical diagrams** visualize how the system is built. Include
components, data flows with direction and content, security boundaries,
and deployment topology. Exclude abstract reasoning better suited to text.

## Styling

Apply styles directly or via classes:

```
style A fill:#f9f,stroke:#333,stroke-width:2px
```

Or define reusable classes:

```
classDef highlight fill:#f9f,stroke:#333,stroke-width:2px
A:::highlight
```

<<<<<<< Updated upstream
## Readability

- Maximum **15 nodes** per diagram — split into multiple diagrams if
  larger
- Use subgraphs to group distinct phases or components
- Minimize edge crossings by reordering node declarations
- Keep labels short: 3-6 words, verb-first for actions
- Always label decision edges with their condition

=======
>>>>>>> Stashed changes
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

## Quality Checklist

Before outputting a diagram, verify:

<<<<<<< Updated upstream
- [ ] Diagram renders without syntax errors
- [ ] All node labels are quoted
- [ ] No nested shape characters (e.g. ~~`([("Label")])`~~)
=======
- [ ] All node labels are quoted with plain ASCII `"`
- [ ] No backslash escaping (`\"`) anywhere in the diagram
- [ ] No nested shape characters (e.g. ~~`([("Label")])`~~)
- [ ] Node IDs are alphanumeric only (no spaces or special characters)
>>>>>>> Stashed changes
- [ ] No node uses `end` as an unquoted ID or label
- [ ] All decision edges are labeled
- [ ] 15 or fewer nodes (or split into parts)
- [ ] Start/end points use distinct shapes
- [ ] Node IDs are unique
- [ ] Diagram matches the surrounding text — no contradictions
