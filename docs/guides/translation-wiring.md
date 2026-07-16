# Translation (Bilingual Support) — Reference

This is a **wiring reference**: what exists and where it lives. It does *not* record the design
rationale or the detailed guard behaviour.

## Related decisions

- **Functional service decision (ADR 006, accepted):** [`docs/adrs/006-translation-subsystem.md`](../adrs/006-translation-subsystem.md)
  — the architectural decision to add a backend translation service for bilingual support.
- **Product requirements (PRD 006, implemented):** [`docs/prds/006-translation-subsystem.md`](../prds/006-translation-subsystem.md)
  — the product requirements for the translation subsystem.
- **Translation policy & failure modes (ADR 018, proposed):** [`docs/adrs/018-translation-policy-and-failure-modes.md`](../adrs/018-translation-policy-and-failure-modes.md)
  — why agents are monolingual English, why the platform (not agents) translates, why language is
  locked early, and the fail-loud policy (including the known gaps as consequences).
- **Testable behaviour — happy path:** [`docs/specs/006-translation-subsystem.feature`](../specs/006-translation-subsystem.feature)
  — the core translation flow.
- **Testable behaviour — failure guards:** [`docs/specs/018-translation-guards.feature`](../specs/018-translation-guards.feature)
  — hallucination guard, label retry, `[NIET VERTAALD]` markers, fail-loud notices, ask-first
  fallback.

Druppie supports Dutch and English users while keeping every agent monolingual English internally.
All translation happens in the backend; the frontend does no translation (no i18n library) — it
only renders whatever the backend already translated.

## Model & provider ladder

Translation uses **LiteLLM** (`ChatLiteLLM`, temperature `0.1`, `max_tokens=16384`,
`timeout=120s`, `max_retries=2`). The provider/model is resolved by
`TranslationService._resolve_translation_config()` (`druppie/core/translation.py`) in this priority
order:

1. **Admin runtime override** — set per environment via the Model Management UI (`/models`),
   persisted in the `model_override` table (`target_type="translation"`), loaded into the singleton
   on startup (`druppie/api/main.py`) and applied immediately on change
   (`druppie/services/model_management_service.py`). Supports a configured fallback provider/model.
2. **Env vars** — `TRANSLATION_PROVIDER` + `TRANSLATION_MODEL` (used only if that provider has an
   API key).
3. **Legacy default** — if `DEEPINFRA_API_KEY` is set → `("deepinfra", "google/gemma-3-27b-it")`.
4. **Any available provider** — the first provider in `PROVIDER_CONFIGS` that has an API key, using
   that provider's `default_model` (e.g. `zai` → `glm-4.7`, `openrouter` → `google/gemma-3-27b-it`).
5. **None available** → raises `TranslationNotAvailableError`.

Translation is **not** hard-wired to DeepInfra/Qwen. With no DeepInfra key and no override it falls
through to the general LLM provider. (The `deepinfra_api_key_not_configured` startup warning in
`core/config.py` reflects the *legacy* assumption and is informational only.)

## Components (where it is wired)

| Component | File | Responsibility |
|-----------|------|----------------|
| `TranslationService` (singleton `get_translation_service()`) | `druppie/core/translation.py` | The translator. `translate_to_english()`, `translate_from_english()`, `translate_label()`, `_translate()` (LLM call), `_strip_thinking()`, config resolution, and session-notification dedup (`mark_notified()` / `clear_session()`, 24h TTL, in-memory → single-worker). Raises `TranslationNotAvailableError` / `TranslationError`. |
| `LanguageDetector` | `druppie/core/language_detection.py` | Detects the user's language (`detect_language()`; hybrid keyword + `langdetect`, threshold `0.6`, `MIN_TEXT_LENGTH=5`; `af`/`fy`/`de` treated as Dutch). |
| `HumanInput` | `druppie/execution/human_input.py` | Wraps user text + detection metadata. |
| Long-content chunking | `druppie/execution/tool_executor.py` → `_translate_long_content()` | Splits and translates long design docs. |
| Design/HITL/fallback seams | `druppie/execution/tool_executor.py` | `_translate_design_content()`, `DESIGN_TRANSLATION_PATHS`, HITL translation, `_notify_translation_unavailable()`. |
| Chat/summarizer translation | `druppie/agents/builtin_tools.py` → `create_message()` | Translates agent output for display. |
| English-only instruction | `druppie/agents/prompt_builder.py` | Injects the English-only block into every agent. |
| Orchestration seam | `druppie/execution/orchestrator.py` | Detects language; translates user input to English (`content` / `content_english`); catches `TranslationError` and switches to English. |

> Behaviour of the guards in these components (hallucination guard, label retry, `[NIET VERTAALD]`
> markers, fail-loud notices) is specified in the linked spec, not here.

## Design documents (dual-file, English = source of truth)

Only for `make_design`, only for a Dutch session, and only for a known path in
`DESIGN_TRANSLATION_PATHS`:

| English (source of truth) | Dutch (auto-generated copy) |
|---------------------------|-----------------------------|
| `docs/functional-design.md` | `docs/functioneel-ontwerp.md` |
| `docs/technical-design.md` | `docs/technisch-ontwerp.md` |
| `docs/technical-research.md` | `docs/technisch-onderzoek.md` |

`_translate_design_content()` injects `translated_content` / `translated_path` into the tool-call
arguments. On MCP execution the **English** file is written first, and only after it succeeds a
**second `write_file` MCP call** writes the Dutch copy. The approval card shows a **single file** —
the session-language version (the English original is still saved in the background).

## Persistence

- **No translation cache** — every translation is a fresh LLM call.
- **Config** lives in the `model_override` table (`target_type="translation"`), loaded at startup.
- **Translated artifacts are stored inline** with what they belong to, not as a cache:
  `messages.content` (translated) + `messages.content_english`; `make_design` tool-call args
  (`translated_content` / `translated_path`) + the dual EN/NL files on disk; HITL
  `english_question` / `english_choices`.
- `_notified_sessions` is an in-memory dict (24h TTL, process-local → assumes a single worker).
- There is **no** dedicated translation table/repository/domain layer.

## Frontend

No i18n library (`i18next` / `react-i18next` are absent). Components only consume backend fields:
`ChatHelpers.jsx` shows the translated design file when `translated_content` / `translated_path`
are present; `SessionDetail.jsx` renders `translated_path`. For Dutch sessions the approval card
shows a single (translated) file.

## Database

| Table.column | Notes |
|--------------|-------|
| `sessions.language` | `VARCHAR(10)`, nullable — `nl` / `en` / `null` |
| `model_override` (`target_type="translation"`) | Admin translation-model override |
| `messages.content` / `messages.content_english` | Display (translated) vs agent-facing (English) |

## Known gaps

Tracked as negative consequences in [ADR 018](../adrs/018-translation-policy-and-failure-modes.md):

- No hallucination/truncation guard on `translate_from_english()` (EN→NL); only NL→EN has one
  (issues #275/#278).
- No structural protection for frontmatter / IDs / code — translation is prompt-only. Only
  `DESIGN_TRANSLATION_PATHS` documents are translated, so decision docs (ADR/PRD/…) are unaffected,
  but design-doc quality depends on the prompt (issues #269/#240/#73).

## Testing

- Agent tests: `testing/agents/ba-bilingual-fd.yaml` (full Dutch bilingual pipeline),
  `testing/agents/ba-english-fd-no-translation.yaml` (English, no translation).
- Judge checks: `testing/checks/ba-fd-bilingual.yaml`, `ba-fd-english-only.yaml`,
  `ba-fd-in-english.yaml`, `architect-reads-english-fd.yaml`.
- Unit: `druppie/tests/test_translation_validation.py`.
- Behaviour spec: `docs/specs/018-translation-guards.feature`.

## History (evolution — why older docs are stale)

- **#232** — foundation: bilingual agents/designs/chat, session locking, English-only prompts,
  Qwen3-32B via DeepInfra, two-file design approval.
- **#272 (fixes #269)** — switched to Mistral-Small-24B, `timeout` 15s→120s, `max_tokens`
  4096→16384, `max_retries` 1→2; `TranslationError` raised instead of silent English;
  `[NIET VERTAALD]` chunk markers; heading preservation; **single-file** approval card;
  `_strip_thinking` fix.
- **#275** — model → `google/gemma-3-27b-it`; NL→EN hallucination guard; `translate_label` with
  English-detection retry.
- **#281** — runtime Model Management (`/models`, `model_override` table), configurable provider
  ladder, ask-first fallback (`FallbackAvailableError` / `FallbackModal`), `TranslationError`
  propagation + `mark_notified()` dedup, Azure Foundry Claude routing, `clean_llm_error()`.
