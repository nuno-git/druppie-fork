# Open questions for review

This file collects points from the PR 162 doc review where the docs and the code disagree in ways that are **not obviously a doc bug** — either the doc describes a planned/missing behaviour, or the code looks unintentional. Please answer inline (leave text directly under each question) so I can apply the right fix.

## 1. `reviewer` agent and the `code-review` skill

The doc `05-agents/definitions/reviewer.md` and `05-agents/skills.md` both describe `reviewer` as loading the `code-review` SKILL via `invoke_skill("code-review")`. But `druppie/agents/definitions/reviewer.yaml` has no `skills:` block, so the runtime never grants it `invoke_skill` and the review checklist lives inline in the system prompt instead.

**Question:** Should reviewer gain `skills: [code-review]` (and stop duplicating the checklist in its system prompt)? Or is the in-prompt checklist the intended design and the doc was aspirational?

I currently annotated both docs with a cautious "not configured today" note. Let me know which way to go and I'll either:
- revert the docs to original wording and add `skills: [code-review]` to `reviewer.yaml`, or
- leave the code alone and keep my "not configured" note.

**Your answer:**

---

## 2. `invoke_skill` schema — enum or free-form?

`docs/specs/05-agents/builtin-tools.md` originally encoded an enum constraint on `skill_name` listing the five current skills. The actual tool definition in `druppie/agents/builtin_tools.py` has no enum — it is just `"type": "string"` — and `SkillService` validates at runtime.

I removed the enum from the doc because the doc claimed something the code doesn't do.

**Question:** Was the enum intentional (should we add it to the code so agents get static validation) or is free-form the intended design?

**Your answer:**

---

## 3. `test_report` `error_classification` values

`docs/specs/05-agents/builtin-tools.md` previously listed `["code_bug", "test_bug", "env_bug", "flaky"]` as the enum for `error_classification`. The actual tool definition in `druppie/agents/builtin_tools.py:275` has no enum and describes the allowed values as `assertion_failure, missing_function, import_error, type_error, syntax_error, configuration_error, environment_error, test_error`.

I updated the doc to match the code.

**Question:** Which taxonomy is correct? If the shorter 4-value taxonomy is the intended target, the code description needs to change. If the longer 8-value taxonomy is correct, no action needed.

**Your answer:**

---

## 4. Sandbox webhook payload schema

The sandbox integration doc claimed the control plane POSTs:
```
{ status, completed_at, reason?, events_url?, artifacts? }
```
signed with `X-Druppie-Signature`. The actual webhook handler in `druppie/api/routes/sandbox.py:150` declares `SandboxCompletePayload` as `{ sessionId, messageId, success, timestamp }` signed with `X-Signature`, and pulls the full event list separately via `GET {control_plane_url}/sessions/{id}/events`.

I updated the doc to match the code — the Druppie side clearly only reads those four fields.

**Question:** Does the control plane actually send the richer `{ status, completed_at, reason, events_url, artifacts }` body too (just ignored by Druppie), or is it strictly the minimal ping shape? If richer, I can note both in the doc.

**Your answer:**

---

## 5. Coding MCP `user_id` injection

`04-mcp-servers/mcp-config.md` listed `user_id` among the coding module's injected params. In `druppie/core/mcp_config.yaml` the `coding.inject` block today only declares `session_id`, `project_id`, `repo_name`, `repo_owner` (no `user_id`).

I removed `user_id` from the coding inject list in the doc and added a note.

**Question:** Was the omission intentional (coding tools don't need per-user scoping beyond project ownership) or is `user_id` supposed to be injected for coding tools too? If the latter, I'll add it to `mcp_config.yaml` instead of editing the doc.

**Your answer:**

---

## 6. `docker:stop` approval

`04-mcp-servers/mcp-config.md` claimed `docker:stop` requires `developer` approval (alongside `build, run, compose_up, compose_down, remove, exec_command`). The actual `mcp_config.yaml:144-145` has `stop: requires_approval: false`.

I updated the doc to move `stop` into the read-only/low-risk category.

**Question:** Is the current config (no approval on `stop`) intentional? If `stop` should gate on `developer` too, I'll flip the config instead of patching the doc.

**Your answer:**

---

## 7. Deployments ownership label

`02-backend/api-routes.md` said non-admin deployment listings are filtered by the `druppie.user_id` container label. The actual deployment service uses the `druppie.project_id` label and then resolves ownership via the project table.

I updated the doc to match the code.

**Question:** Purely confirming this is the current design (project-scoped ownership, not user-scoped). Any plans to add a direct `druppie.user_id` label too?

**Your answer:**

---

## 8. `SessionService` conflict exception type

The `02-backend/errors.md` doc describes a `ConflictError` raised by services. `SessionService.lock_for_retry` and `lock_for_resume` actually raise plain `ValueError`, which route handlers catch and convert to HTTP 409.

I added a caveat in `errors.md` and `services.md` and did not change behaviour.

**Question:** Is the plan to converge on `ConflictError` (the class already exists in `druppie/api/errors.py:196`) or is `ValueError` + route-level mapping intentional? If the former, converting the couple of sites is a small cleanup I can do.

**Your answer:**

---

## 9. `/api/status` vs `/health/ready`

`startup.md` describes two health endpoints plus `/api/status` as a "richer probe". I have not exhaustively traced what `/api/status` actually checks — just leaving the section as-is.

**Question:** Is anything explicitly probed in `/api/status` that we want the spec to name (Keycloak connectivity, Gitea connectivity, LLM config presence, agent count)? If yes, I'll update the doc to match the actual probe list.

**Your answer:**

---

## 10. `JudgeProfile.temperature` / strict-vs-default judge profiles

`testing/profiles/judges.yaml` today defines three profiles (`default`, `strict`, `fast`) that all use the same model (`glm-4.5-air`, provider `zai`) with no temperature override. The schema class `JudgeProfile` does not have a `temperature` field at all. The docs had claimed the `strict` profile used `claude-sonnet-4-6` with `temperature: 0.0`.

I updated the doc to match the real YAML.

**Question:** Is the "three identical profiles" state temporary (were `strict` / `fast` meant to be differentiated) and the schema/YAML should grow a `temperature` field back? If so I'll revert the doc.

**Your answer:**

---

## 11. `docs/specs/questions.md` itself

I placed this file under `docs/specs/` so it ships with the PR. If you'd rather keep it out of the merge, we can move it to a scratch location (or delete after you answer). No action needed until we decide.

**Your answer:**

---

## 12. Non-findings worth flagging

Things I noticed but did **not** change:
- `druppie/agents/definitions/reviewer.yaml` system prompt contains the line `"CRITICAL: You can ONLY act through MCP tools."` — slightly at odds with the fact that `done()` and `hitl_*` are builtins, not MCP tools. Cosmetic; doc isn't affected.
- `druppie/requirements.txt:8` still lists `langgraph>=0.2.0`, but nothing imports it. The overview used to call the orchestrator "LangGraph-style"; I corrected the doc to "custom tool-calling loop". Worth removing the dep on a future cleanup.
- `frontend/src/pages/Plans.jsx` exists but isn't routed from `App.jsx`. Dead code or WIP? Not mentioned in the docs I edited.
- `/api/sandbox-sessions/{id}/complete` responds with 403 for signature mismatch OR missing session (same route) — `integration.md` now says "403" (was "401"), but you may want 401 for signature failures and 404 for missing sessions for cleaner client debugging.

**Your answer:**
