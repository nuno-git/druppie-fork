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
errors: write `A["My label"]` not `A[My label]`. Keep labels short:
3-6 words, verb-first for actions.

**Each node uses EXACTLY ONE shape from the table above.** Pick the shape
you need and place the quoted label directly inside it — never combine
or nest shape delimiters.

### Common mistakes — correct vs wrong

Stadium shape:
  CORRECT: `start(["Begin process"])`
  WRONG:   `start([("Begin process")])` — extra `("` inside `([` breaks it

Cylinder shape:
  CORRECT: `db[("My database")]`
  WRONG:   `db[(("My database"))]` — extra `((` inside `[(` breaks it

Circle shape:
  CORRECT: `stop(("End"))`
  WRONG:   `stop([(("End"))])` — mixed delimiters break it

Diamond shape:
  CORRECT: `check{"Valid?"}`
  WRONG:   `check{("Valid?")}` — extra `("` inside `{` breaks it

**Why this happens:** Delimiters like `([`, `[(`, and `((` each define ONE
shape. They cannot be combined. Two pairs of delimiters on one node is
always wrong.

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

After writing your Mermaid code, verify it node by node before including
it in your final output:

1. **Shape check:** For each node, confirm its delimiters match exactly
   one entry from the Node Shapes table:
   `[""]` `("")` `([""])` `{""}` `{{""}}` `[[""]]` `((""))` `[("")]`
   If a node has two or more pairs of shape delimiters, it is wrong.

2. **Quote check:** All labels use plain ASCII `"` — no `\"` escaping.

3. **Edge labels:** All decision edges are labeled: `-->|"label"|`

4. **Reserved words:** No node ID is the bare word `end`.

5. **IDs:** All node IDs are alphanumeric (`A-Z`, `a-z`, `0-9`, `_`).

6. **Size:** 15 or fewer nodes per diagram (split if larger).

7. **Consistency:** Diagram matches the surrounding text.

If any check fails, fix the node before outputting the diagram.
