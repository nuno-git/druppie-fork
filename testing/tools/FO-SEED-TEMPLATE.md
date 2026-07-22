## FO Seed Template — "fake the whole Business Analyst, land on the FO approval gate"

**Purpose.** Given a Functioneel Ontwerp (FO), produce a `tool-test` seed that reproduces
the *entire* Business Analyst (BA) `create_project` run as a real session would have it —
context gathering, the full HITL elicitation with the user's answers, the mandatory mermaid
skill, and finally `coding:make_design` — and then **pauses on the session-owner approval
gate** for `docs/functional-design.md`.

When you (Claude) receive an FO, copy the template block below into
`testing/tools/setup-fo-<slug>.yaml`, fill every `<<PLACEHOLDER>>`, and tailor the
elicitation questions + answers and the FO body to that specific FO. Then run it (§4).

The golden, already-working reference for this pattern is
[`vg-assistent-fo-volledig-gesprek.yaml`](./vg-assistent-fo-volledig-gesprek.yaml) — when in
doubt, mirror it.

---

### 1. Why this specific shape (the re-run bug this avoids)

The reported problem — *"after I approve/give feedback the BA redoes steps it already did
(re-asks the elicitation questions)"* — has a single root cause in
`druppie/agents/runtime_v2.py::continue_run`:

```python
if not llm_calls:                 # no reconstructable history for this run
    messages = [system_prompt, user_prompt]
    ... _run_with_new_loop(start_iteration=0)   # RESTARTS the BA from scratch
messages = reconstruct_from_db(llm_calls, ...)  # otherwise: continue where it left off
```

On approve/reject, the platform **resumes the same paused BA run** and rebuilds its
conversation from the `LlmCall` rows in the DB. The replay engine writes **one `LlmCall`
per chain step**, so the fix is simply: *seed the whole BA conversation, not just the
`make_design` call.* A rich, coherent "requirements are settled, FO is written" history is
what makes the resumed BA:

- on **approve** → just `coding:push_changes` + `builtin:done` → the trailing planner runs →
  architect. No re-elicitation.
- on **reject with feedback** → **revise** the existing FO per the feedback (BA system-prompt
  Phase 10), not re-run discovery.

So: **completeness of the seeded conversation is the correctness guarantee.** Do not shorten it.

### 2. The invariants (must always hold — a checklist)

- [ ] `session_status: paused_approval` (NOT `paused`). `paused` rewrites the BA run to
      `paused_user` and the UI shows a generic "Continue" button; `paused_approval` keeps the
      real approval-gate state (session=`paused_approval`, BA run=`paused_tool`,
      `make_design`=`waiting_approval`) so the UI shows exactly the approve/reject card.
- [ ] The `coding:make_design` step carries `approval: { status: pending }` and is the
      **last** step of the chain. Nothing after it.
- [ ] The BA conversation is **complete and mocked**: context gathering + every elicitation
      Q&A + the summary validation + the mermaid skill, all `mock: true`. Deterministic, no LLM.
- [ ] The `make_plan` step lists **two** steps: `business_analyst` then a trailing
      `planner` ("Re-evaluate after business analyst completes"). The trailing planner is the
      pending run that carries the workflow to the architect *after* approval. (`make_plan`
      creates it as a pending `AgentRun`; you do **not** need a separate `pending_agents:` block.)
- [ ] Every elicitation **answer** (`mock_result`) is consistent with the FO body — each
      FR/NFR/BR in the FO should trace to something the user "said". Incoherent history is what
      makes a resumed BA think it still needs to ask.
- [ ] The FO goes verbatim into `coding:make_design.arguments.content` at
      `docs/functional-design.md`.

### 3. The template — copy, save as `testing/tools/setup-fo-<slug>.yaml`, fill `<<...>>`

```yaml
## Seeded session: full create_project conversation for "<<PROJECT TITLE>>",
## paused on the session-owner approval gate for the Functioneel Ontwerp
## (docs/functional-design.md).
##
## Reproduces the whole BA run — context gathering, full HITL elicitation with
## the user's answers, mermaid skill, then make_design on the PENDING gate.
## Every pre-gate step is mock: true → 100% deterministic seeding (no LLM).
## Only the post-gate resume (approve → push+done→architect, or reject → revise) is live.
##
## To test: run this from the evaluations page → green; log in as the session
## owner (admin); /tasks → pending approval for docs/functional-design.md on
## session "<<PROJECT_SLUG>>"; approve or reject-with-feedback, then resume.

tool-test:
  name: setup-fo-<<PROJECT_SLUG>>
  description: "Volledig geseed create_project-gesprek voor het <<PROJECT TITLE>> FO — gepauzeerd op de session-owner approval gate, klaar voor approve/feedback"
  tags: [seed, paused, business_analyst, approval-gate, fd, elicitation, full-conversation]
  session_status: paused_approval

  chain:
    # ===================== ROUTER =====================
    - agent: router
      tool: builtin:set_intent
      arguments:
        intent: create_project
        project_name: <<PROJECT_SLUG>>          # kebab-case, e.g. vg-assistent
        description: "<<ONE-SENTENCE PROJECT DESCRIPTION FROM THE FO>>"
      assert:
        result:
          - not_empty

    - agent: router
      tool: builtin:done
      arguments:
        summary: "Agent router: Classified as create_project for <<PROJECT_SLUG>>"
      assert:
        completed: true

    # ===================== PLANNER → BA =====================
    # This prompt becomes the BA run's planned_prompt. Keep the trailing planner —
    # it is the pending run that advances to the architect after approval.
    - agent: planner
      tool: builtin:make_plan
      arguments:
        steps:
          - agent_id: business_analyst
            prompt: |
              <<THE CREATE_PROJECT TASK IN THE USER'S WORDS — what they want built,
              and the instruction to elicit requirements and write the FO to
              docs/functional-design.md.>>
          - agent_id: planner
            prompt: "Re-evaluate after business analyst completes"

    - agent: planner
      tool: builtin:done
      arguments:
        summary: "Agent planner: Planned business_analyst to gather requirements and create the functional design"

    # ===================== BA: CONTEXT GATHERING (mocked) =====================
    # Mandatory similarity check + platform standards + data sources. Mocked → deterministic.
    - agent: business_analyst
      tool: registry:list_modules
      mock: true
      mock_result: |
        {"success": true, "count": 9, "modules": [{"id": "archimate", "type": "core"}, {"id": "coding", "type": "core"}, {"id": "dataaccess", "type": "module"}, {"id": "docker", "type": "core"}, {"id": "filesearch", "type": "core"}, {"id": "llm", "type": "both"}, {"id": "registry", "type": "core"}, {"id": "vision", "type": "module"}, {"id": "web", "type": "both"}]}

    - agent: business_analyst
      tool: registry:search_modules
      arguments:
        query: "<<2-5 KEYWORDS FROM THE PROJECT DOMAIN>>"
      mock: true
      mock_result: |
        {"success": true, "query": "<<SAME KEYWORDS>>", "count": 0, "results": []}

    - agent: business_analyst
      tool: registry:list_components
      mock: true
      mock_result: |
        {"success": true, "categories": {"agents": {"count": 15}, "skills": {"count": 13}, "builtin_tools": {"count": 9}}, "total": 37}

    - agent: business_analyst
      tool: coding:list_projects
      mock: true
      mock_result: |
        {"success": true, "count": 1, "projects": [{"name": "sample-project", "description": "Voorbeeldproject"}]}

    - agent: business_analyst
      tool: coding:read_file
      arguments:
        path: docs/platform-functional-standards.md
      mock: true
      mock_result: |
        {"success": true, "path": "docs/platform-functional-standards.md", "content": "# Platform Functionele Standaarden (rev 1)\n\nPlatformdefaults voor authenticatie (Keycloak), autorisatie, logging, dataretentie en privacy gelden automatisch. Schrijf alleen FR/NFR voor projectspecifieke afwijkingen (sectie 14)."}

    - agent: business_analyst
      tool: dataaccess:list_sources
      mock: true
      mock_result: |
        {"success": true, "sources": [], "count": 0}

    # ===================== BA: ELICITATION (mocked HITL Q&A) =====================
    # One completed HITL call per requirement area. Answers MUST match the FO body.
    # Use hitl_ask_question for open questions, hitl_ask_multiple_choice_question when
    # the FO implies a clear choice. Aim for ~6–10 questions covering: current situation,
    # who is affected, data/knowledge sources, access & roles, sensitive data, behaviour
    # on uncertainty, devices/NFRs, retention, and scope/success criterion.
    #
    # --- repeat one of the two blocks below per elicitation question ---
    - agent: business_analyst
      tool: builtin:hitl_ask_question
      arguments:
        question: "<<OPEN QUESTION>>"
        context: "<<WHY YOU'RE ASKING (one line)>>"
      mock: true
      mock_result: |
        <<THE USER'S ANSWER — must be consistent with the FO.>>

    - agent: business_analyst
      tool: builtin:hitl_ask_multiple_choice_question
      arguments:
        question: "<<CLOSED QUESTION>>"
        choices:
          - "<<CHOSEN ANSWER — consistent with the FO>>"
          - "<<PLAUSIBLE ALTERNATIVE>>"
          - "<<PLAUSIBLE ALTERNATIVE>>"
        context: "<<WHY YOU'RE ASKING (one line)>>"
      mock: true
      mock_result: "<<THE CHOSEN ANSWER — copy one of the choices verbatim>>"
    # --- end repeat ---

    # ===================== BA: SUMMARY VALIDATION (mocked) =====================
    # Present the settled requirements back; user confirms. Keeps the history coherent.
    - agent: business_analyst
      tool: builtin:hitl_ask_multiple_choice_question
      arguments:
        question: |
          <<PROBLEM SUMMARY + THE FR LIST + WHAT'S OUT OF SCOPE, condensed from the FO>>
        choices:
          - "Ja, dit beschrijft precies wat we nodig hebben"
          - "Gedeeltelijk, er missen nog een paar dingen"
          - "Nee, er zijn belangrijke punten die niet kloppen"
        context: "Validatie van de opgehaalde requirements voordat het FO wordt geschreven."
      mock: true
      mock_result: "Ja, dit beschrijft precies wat we nodig hebben"

    # ===================== BA: MERMAID SKILL (mocked, mandatory) =====================
    - agent: business_analyst
      tool: builtin:invoke_skill
      arguments:
        skill_name: making-mermaid-diagrams
      mock: true
      mock_result: |
        {"success": true, "skill_name": "making-mermaid-diagrams", "instructions": "Mermaid syntax rules loaded. Quote all labels; use flowchart TD; never use 'end' as a node id; verify every node before rendering. This is the full instruction — no further skill call is needed before coding_make_design."}

    # ===================== BA: WRITE FO — approval gate PENDING =====================
    # Last step. The session_owner resolves this approval through the UI.
    - agent: business_analyst
      tool: coding:make_design
      approval:
        status: pending
      arguments:
        path: docs/functional-design.md
        content: |
          <<THE FULL FO MARKDOWN, VERBATIM. Indent every line under content by the
          same amount. Keep the section structure the FO uses (Huidige vs Gewenste
          Situatie, Probleemsamenvatting, Functionele Eisen, Bedrijfsregels,
          Informatiebehoeften, Gebruikersreizen, Integratiepunten, NFR's, Beveiliging,
          Aannames, Buiten Scope, Procesflow (mermaid), Oplossingsrichting,
          Platformstandaardafwijkingen).>>

    # No steps after this — the chain ends on the pending approval.

  verify:
    - gitea_repo_exists: true
```

### 4. Run it

```bash
# From CLAUDE.md — load ports + token
KEYCLOAK_PORT=${KEYCLOAK_PORT:-8180}; BACKEND_PORT=${BACKEND_PORT:-8100}
TOKEN=$(curl -s -X POST "http://localhost:${KEYCLOAK_PORT}/realms/druppie/protocol/openid-connect/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=password&client_id=druppie-frontend&username=admin&password=Admin123!" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# Run the seed
curl -s -X POST "http://localhost:${BACKEND_PORT}/api/evaluations/run-tests" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"test_name": "setup-fo-<<PROJECT_SLUG>>"}'
# Poll /api/evaluations/run-status/<run_id> until "completed" → "1/1 passed".
```

Then log in to the frontend as `admin` / `Admin123!`, open **/tasks** → you'll see the
pending approval for `docs/functional-design.md` on session `<<PROJECT_SLUG>>`.

### 5. Verify approve AND feedback both continue (no re-elicitation)

The whole point — prove both paths move forward without the BA re-asking questions.

- **Approve path.** In /tasks, approve the FO. Resume the session. Expected: the BA does
  **not** re-ask anything — it runs `push_changes` + `done()`, then the trailing planner runs
  and plans the **architect** (technical-design.md). Confirm in the session timeline that the
  `business_analyst` run went `paused_tool → completed` (it was *not* recreated) and that an
  `architect` run appears next.

- **Feedback path.** Re-seed a fresh copy (the seed is deterministic/idempotent per test
  user), and this time **reject with a reason** (e.g. "FR-03 mist een acceptatiecriterium").
  Resume. Expected: the **same** BA run resumes and **revises** `docs/functional-design.md`
  per the feedback — it does not re-run the elicitation.

API equivalents (find the pending approval on the session, then):
```bash
# approve:  POST /api/approvals/{approval_id}/approve
# feedback: POST /api/approvals/{approval_id}/reject   -d '{"reason": "<<your feedback>>"}'
# then resume: POST /api/sessions/{session_id}/resume
```
Get `{approval_id}` and `{session_id}` from the session detail
(`GET /api/sessions` → match on title `<<PROJECT_SLUG>>` → `GET /api/sessions/{id}`; the
pending `Approval` is linked to the `make_design` tool call on the BA run).

**Green light:** the `business_analyst` run keeps its id across the resume (status
`paused_tool → completed`/`running`), and no second `business_analyst` run with fresh
elicitation appears. That is the guarantee the "full conversation" seeding buys you.

### 6. Filling checklist (FO → seed)

| From the FO, extract… | Fill into… |
|---|---|
| Project title + kebab slug | `name`, `project_name`, session title, comments |
| One-sentence description | `set_intent.arguments.description` |
| The build request in the user's words | `make_plan` → `business_analyst.prompt` |
| Domain keywords | `registry:search_modules.arguments.query` |
| Each requirement area (current situation, stakeholders, sources, roles/access, sensitive data, uncertainty behaviour, devices/NFRs, retention, scope) | one elicitation Q&A each, answers consistent with the FO |
| Problem summary + FR list + out-of-scope | the summary-validation question |
| The entire FO markdown | `coding:make_design.arguments.content` |

Keep answers and FO mutually consistent; that coherence is what prevents the resumed BA from
re-eliciting. When unsure about the exact operational steps, diff against
`vg-assistent-fo-volledig-gesprek.yaml`, which is the fully-worked instance of this template.
