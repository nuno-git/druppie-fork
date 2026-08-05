# business_analyst

File: `druppie/agents/definitions/business_analyst.yaml` (1001 lines — longest YAML in the repo).

## Role

Requirements elicitation, root-cause analysis, and functional design authoring. The **business_analyst (BA)** uncovers the real problem, translates vague user intent into solution-agnostic functional requirements, and produces `functional_design.md` — the approval-gated artifact that seeds downstream technical work.

## Config

| Field | Value |
|-------|-------|
| category | execution |
| llm_profile | cheap |
| temperature | 0.2 |
| max_tokens | 100000 |
| max_iterations | 50 |
| builtin tools | `invoke_skill` + default HITL + `done` |
| MCPs | `coding` (read_file, make_design, list_dir, run_git, list_projects, list_project_files, read_project_file), `registry` (list_modules, get_module, search_modules, list_components) |
| system prompts | tool_only_communication, summary_relay, done_tool_format, workspace_state |
| skills | making-mermaid-diagrams |
| approval_overrides | `coding:make_design` → `session_owner` |

## Five modes

### 1. `general_chat`
Advises on business topics. May route to architect or summarizer at end.

### 2. `create_project`
Full elicitation in 9 phases:
1. **Intake** — restate the ask.
2. **Solution Unpacking** — tease apart what the user is proposing vs what they need.
3. **Root Cause Analysis** — 5 whys / problem tree.
4. **Elicitation** — HITL questions to fill gaps.
5. **Stakeholder Mapping** — users, approvers, consumers.
6. **Requirement Structuring** — FR / BR / IR / UJ / IP / NFR / Security / Compliance / Assumptions / Out-of-scope.
7. **FD Synthesis** — draft `functional_design.md`.
8. **Bias Check** — does the FD assume a solution? If yes, revise.
9. **Diagram** — process flow in Mermaid.

### 3. `update_project`
Assess whether the change is functional (new requirements → new FD) or purely technical (NO_FD_CHANGE signal). If functional, revise the existing FD.

### 4. Revision mode
Architect sent `DESIGN_FEEDBACK` — targeted fix to addressed feedback items.

### 5. Reject-then-approve cycle
User rejected the first FD via `session_owner` approval gate. BA revises to address the concrete feedback and calls `make_design` again for a second approval attempt.

## `functional_design.md` structure

13 sections, written in Dutch (per project convention):
1. Current vs Desired (Huidige vs Gewenste situatie)
2. Problem Summary (Probleemsamenvatting)
3. Functional Requirements (Functionele eisen)
4. Business Rules (Bedrijfsregels)
5. Information Requirements (Informatiebehoeften)
6. User Journeys (Gebruikerstrajecten)
7. Integration Points (Integratiepunten)
8. Non-Functional Requirements (Niet-functionele eisen)
9. Security & Compliance (Beveiliging & Compliance)
10. Assumptions (Aannames)
11. Out of Scope (Buiten scope)
12. Process Flow Diagram (Procesdiagram) — Mermaid
13. Possible Solution Direction (Mogelijke oplossingsrichting) — high-level, not prescriptive

## Language

`functional_design.md` is ALWAYS in Dutch regardless of user's language (enforced in the agent prompt). This is a business-domain decision — the target business users are Dutch water authorities.

HITL questions and summaries can be in the user's language (detected at session level and stored in `session.language`).

## Approval gate

`coding:make_design` is overridden to require `session_owner` approval. The business owner (session starter) reviews the FD content before it proceeds to the architect. On reject + revision, the gate fires again for the revised version.

## Output (summary relay line)

Typical `done()` summary:
```
Agent business_analyst: wrote /workspace/docs/functional_design.md covering
[Jan Pieter's water-authority permit locator: FR1-FR8, NFRs for <500ms lookup,
integration with BAG + IMBAG, process flow via Mermaid]. DESIGN_APPROVED.
```

The word `DESIGN_APPROVED` is the signal that downstream agents can proceed. `DESIGN_FEEDBACK` means the approver left a comment; BA revises.

## Registry usage

Before writing the FD, BA typically calls:
- `registry:list_modules` — is there an existing module for this capability?
- `registry:search_modules` — keyword search.
- `coding:list_projects` / `list_project_files` — is a similar project already built?

This discovery keeps the ecosystem from growing duplicate modules.

## HITL personas

Often the BA asks a mix of:
- Factual questions ("what's your user base size?")
- Clarifying questions ("when you say X, do you mean Y or Z?")
- Multiple-choice stakeholder mapping ("who are the primary stakeholders?")

See `testing/profiles/hitl.yaml` for personas used in evaluation.
