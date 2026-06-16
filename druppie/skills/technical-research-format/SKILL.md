---
name: technical-research-format
description: >
  Format template for docs/technical-research.md. Use this skill when writing
  the technical research document during the architect phase.
---

# Technical Research

## Introduction

### Subject
[Brief description of what is being researched — summarized from the FD.]

### Research Question
[Which architectural decision must this research support? Formulate as a question.]

### Assumptions
[Relevant platform standards, NORA layers, Water Authority principles and
hard constraints (legislation, existing systems, PII) that every solution
must respect.]

## Considered Approaches

Consider at least 2, preferably 3 substantially different approaches.
Repeat the block below for each approach.

### Approach A — [name]
* **Description:** [how does this approach solve the problem?]
* **Reuse:** [which Druppie modules, components or template parts?]
* **Pros and cons:**
    | Aspect | Score | Explanation |
    |--------|-------|-------------|
    | Complexity | + / - | ... |
    | Reusability | + / - | ... |
    | Operational costs | + / - | ... |
    | Risk | + / - | ... |
    | Fit with principles | + / - | ... |
* **When suitable:** [in which scenario would you choose this?]

### Approach B — [name]
[same as above]

### Approach C — [name]
[same as above — skip only if there is demonstrably no meaningful third variant]

## External System Connections (MANDATORY)

Within Druppie, connections to external systems are in principle
implemented as **MCP modules**, so they are reusable for
future projects. Deviating from this principle is allowed, but requires
an explicit justification.

### Connection inventory
| # | External system | Category | Direction | Protocol / auth | Sync/Async | Data (brief) |
|---|----------------|-----------|----------|------------------|-----------|-------------|
| 1 | ... | organizational / other | in / out / both | ... | ... | ... |
| 2 | ... | ... | ... | ... | ... | ... |

The **Category** column is binding: `organizational` for water authority/HHR
systems (source systems, case management, DMS, archive system, reference data,
water authority auth, …), `other` for 3rd-party SaaS, public APIs, etc.

### Per connection: reuse analysis
Repeat for each connection from the table above:

#### Connection 1 — [external system]
* **Category:** organizational / other
* **Existing module checked:** [search queries via registry_search_modules
  and registry_list_modules + result]
* **Decision (choose exactly one):**
    - [ ] REUSE — existing module `<module_id>` covers the need
    - [ ] EXTEND — existing module `<module_id>` will be extended with
          tools: [names + brief description]
    - [ ] NEW MODULE — new module `<proposed_name>` with tools:
          [names + brief description]
    - [ ] PROJECT-SPECIFIC — no module (**only allowed for category
          `other`** — for `organizational` this option is not valid)
* **Justification:** [why this choice; reference principles such as
  reuse, loose coupling and standardization.]
* **Direct integration rationale** (MANDATORY if you choose PROJECT-SPECIFIC,
  otherwise omit):
    - (a) Why is this connection not reusable for future projects?
    - (b) Why would a module create disproportionate overhead here?
    - (c) Which future reuse risk do you explicitly accept?
* **Impact on TD:** [what changes in the component structure /
  integration points of the TD as a result?]

#### Connection 2 — [external system]
[same as above]

### Summary of new/extended modules
| Module | Type | Tools | Reason |
|--------|------|-------|--------|
| ... | new / extend | ... | ... |

Rows in this table mean BUILD_PATH=CORE_UPDATE (see Step 2b).

## Recommendation

* **Chosen approach:** [A / B / C]
* **Rationale:** [reference the trade-off tables and the
  external connections analysis.]
* **Derived decisions for TD:** [which research choices become
  architectural decisions in docs/technical-design.md?]
* **Derived Technical Requirements:** [which research outcomes
  must appear as TR-xx in the TD?]
* **Outstanding assumptions/risks:** [points that must be validated
  during build/test or in a later iteration.]
