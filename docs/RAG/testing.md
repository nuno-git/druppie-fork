# RAG Testing

## Automated E2E: deploy an app and prove the RAG pipeline works

The `rag-app-deploy-e2e` tool test deploys the bare project template
(which includes `app/rag.py` + pgvector) and validates the full
index → embed → store → search loop against real Dutch policy documents.

Run it from the Evaluations page or via the API:

```bash
# From the evaluations UI: pick "rag-app-deploy-e2e" and run.
```

What it proves:
- `docker:compose_up` deploys the template with a working pgvector database
- `POST /api/rag/index` chunks text, calls `module-llm` embed, stores vectors
- `POST /api/rag/search` embeds the query, runs cosine similarity, returns ranked chunks
- Source metadata (`source_name`, `source_page`, `score`) is preserved through the pipeline
- Two different queries return the correct documents (not just the same chunk every time)

Related tool tests:
- `rag-embed-pipeline` — validates `module-llm` embed in isolation
- `platform-standards-rag-defaults` — validates the seeded standards contain §5 RAG defaults

---

## Manual E2E: RAG Detection by the Architect

> Validates Story A end-to-end: an FD that obviously needs RAG triggers
> the Architect's `rag-patterns` skill in Step 1 and lands a RAG choices
> subsection plus TR-RAG-XX NFRs in the produced TD.

## 1. Prepare the core

The test exercises three things we just landed: the architect's Step 1
detection trigger, the `rag-patterns` skill, and the TD-format's RAG
choices subsection. None of these are code changes — only YAML and
markdown — so a restart of the affected services is enough.

```bash
# From the repo root, with the dev profile already up.
docker compose --profile dev restart druppie-backend-dev module-registry
```

If the dev stack is not running:

```bash
docker compose --profile dev --profile init up -d
```

The `module-registry` exposes agent definitions and skills to other
services. Restarting it ensures the new `rag-patterns` skill is
discoverable and the updated `architect.yaml` is loaded.

## 2. Seed the test

1. Open the frontend at <http://localhost:5273>.
2. Log in as **admin** (`admin` / `Admin123!`).
3. Go to the **Evaluations** page (admin tests UI).
4. Expand the **Seed Setup** section.
5. Pick the **`architect-fd-rag-pending`** seed setup.
6. In "Seed as user", pick **`analyst`** (so the FD-approval gate is
   in your queue when you switch role).
7. Click **Seed**.

What this does:
- Creates a Gitea repo for project `beleidsdocument-assistent`.
- Replays Router → Planner → Business Analyst calls.
- The Business Analyst's `make_design` for `docs/functional-design.md`
  is **paused on the analyst-role approval gate**.

## 3. Approve the FD

1. Switch user (or log out and back in) as **analyst**
   (`analyst` / `Analyst123!`).
2. Go to **Tasks**.
3. Find the pending approval for `docs/functional-design.md` on the
   session named `beleidsdocument-assistent`.
4. Click **View file** and skim the FD — verify it describes a
   doc-heavy use case: knowledge-base search over 50+ page policy
   documents, mandatory citations with page numbers, multi-document
   corpus.
5. Click **Approve**.

After approval, the Business Analyst resumes:
- commits and pushes `docs/functional-design.md`,
- calls `done()`,

The planner re-evaluates and schedules the Architect.

## 4. What to look for — Architect run

Open the session detail page for `beleidsdocument-assistent` and
watch the Architect's tool calls in real time.

### ✅ Expected, in this order:

1. **`coding:read_file`** on `docs/functional-design.md` — intake.
2. **`coding:read_file`** on `docs/platform-technical-standards.md`
   (and/or `platform-functional-standards.md`).
3. **`registry:list_modules`** / **`registry:search_modules`** —
   capability scan.
4. **`builtin:invoke_skill`** with `skill_name="rag-patterns"`.
   **This is the primary signal that the Step 1 trigger fired.**
5. Likely `builtin:invoke_skill` for `architecture-principles` and
   `technical-research-format` as well.
6. `coding:make_design` for `docs/technical-research.md` — research
   document. Review for an RAG-patterns axis (chunking, retrieval,
   embedding, vector store, rerank, citations) with the choices
   motivated.
7. Approval gate fires for the research; approve as **architect**
   (switch user to `architect` / `Architect123!`).
8. `builtin:invoke_skill` for `technical-design-format`.
9. `coding:make_design` for `docs/technical-design.md`.
10. Approval gate fires for the TD; review the TD content (see §5),
    then approve.

### ❌ Red flags (the trigger did not fire correctly):

- The Architect skips `invoke_skill("rag-patterns")` entirely — Step 1
  detection trigger missed the doc-heavy signal in the FD.
- The Architect bounces the FD back to the BA with `DESIGN_FEEDBACK` —
  the FD is intentionally complete; if this happens, log the feedback
  and check whether a required section is missing for the architect's
  current expectations.

## 5. What to look for — Technical Design content

Open `docs/technical-design.md` (via the file viewer or directly in
Gitea). The Architectural Solution section must contain a
subsection like:

> #### 3. RAG choices

That subsection should state, per layer, whether the design follows
the platform default or deviates (with trigger):

- Chunking
- Retrieval
- Embedding
- Vector store
- Re-ranking
- Query transformation
- Advanced patterns
- Citation strategy

The **Requirements table** must contain at least the mandatory
TR-RAG-XX rows from the `rag-patterns` skill, with archetype
targets (`LS` / `HS` / `B`). At minimum expect to see:

- `TR-RAG-01/02` — retrieval-latency P95/P99
- `TR-RAG-03/04/05` — recall@10, nDCG@5, MRR
- `TR-RAG-06` — faithfulness
- `TR-RAG-07` — citation precision
- `TR-RAG-08` — hallucination rate
- `TR-RAG-09/10/11` — freshness SLA
- `TR-RAG-12` — named content owner
- `TR-RAG-13/14` — end-to-end latency / TTFT
- `TR-RAG-15` — pipeline uptime
- `TR-RAG-19` — CI gate on faithfulness regression
- `TR-RAG-21` — PII tagging before indexing
- `TR-RAG-22` — lineage per chunk

The TD should reference **app-local pgvector** (`app/rag.py`) as the
storage + retrieval building block and **`module-llm`**'s
`embed` tool for embeddings. If the TD mentions `module-rag`, it
should be framed as "Story B orchestrator — not yet implemented".
The TD must cite **platform-standards §5 RAG defaults**.

## 6. Cleanup

To re-run the test from scratch:

```bash
docker compose --profile reset-db run --rm reset-db
docker compose --profile dev restart druppie-backend-dev module-registry
```

Then repeat from §2.

## 7. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Seed test not visible in Evaluations UI | YAML failed to parse; backend hasn't reloaded | `docker compose logs druppie-backend-dev --tail 50` for the parse error |
| `invoke_skill("rag-patterns")` is not in the skill picker | `rag-patterns` not in architect's `skills:` list, or skill file not loaded | Check `druppie/agents/definitions/architect.yaml` skills block and restart `module-registry` |
| Architect bounces FD back to BA | The FD is missing a section the Architect expects | Compare the seeded FD's sections against the Architect's intake checklist |
| TD has no RAG choices subsection | TD-format skill not loaded by Architect | Verify `druppie/skills/technical-design-format/SKILL.md` has the `#### 3. RAG choices` block and restart `module-registry` |
| Test fails to seed (Gitea error) | Gitea not healthy yet | `docker compose ps` — wait for `gitea` to report healthy |
