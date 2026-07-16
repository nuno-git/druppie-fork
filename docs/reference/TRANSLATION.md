> **⚠️ SUPERSEDED** — This reference doc has been superseded by the formal translation subsystem ADR and PRD.
> - **ADR 006** (`docs/adrs/006-translation-subsystem.md`) — the architectural decision
> - **PRD 006** (`docs/prds/006-translation-subsystem.md`) — the product requirements
> Kept for historical reference.

# Translation (Bilingual Support)

Druppie supports Dutch and English users while keeping every agent **monolingual English**
internally. All translation happens in the **backend**; the frontend does no translation (no
i18n library) — it only renders whatever the backend already translated.

> This document describes the current implementation. Translation started as a fixed
> Qwen3-32B/DeepInfra service and has since evolved: the model is now configurable (legacy
> default `google/gemma-3-27b-it`), design approval is single-file, and several quality/error
> guards were added. See **History** at the bottom for the evolution.

## Design principles

1. **Agents are monolingual English.** Every agent gets a fixed English-only instruction block
   (`druppie/agents/prompt_builder.py`) — *"You MUST work entirely in ENGLISH"*. Agents never see
   or emit non-English text; this keeps prompts simple and avoids language-mixing.
2. **The platform translates, not the agents.** Translation runs at the orchestrator, tool
   executor and builtin-tools layers — never inside agent prompts.
3. **Session language is locked early.** The first user message sets `session.language`. HITL
   answers do **not** change it (a single English-sounding answer from a Dutch user no longer flips
   the whole session).
4. **Fail loudly on *misconfiguration*, degrade visibly on *runtime* errors.** A missing/invalid
   translation provider raises `TranslationNotAvailableError`, switches the session to English and
   posts a bilingual notice. Per-call runtime failures don't silently serve untranslated text
   either: design-doc chunks get a visible `[NIET VERTAALD / NOT TRANSLATED]` marker, and message
   failures post a bilingual "translation unavailable" notice. (One exception is documented under
   *Quality guards & known gaps*.)

## Language support & detection

- Only **Dutch (`nl`)** and **English (`en`)** are *conversational* languages. Any other detected
  language sets the session to English, but the user's input is still translated to English so
  agents can work with it.
- Detection: `druppie/core/language_detection.py` → `LanguageDetector.detect_language()`. Hybrid of
  Dutch/English keyword heuristics + the `langdetect` library (confidence threshold `0.6`). Returns
  `None` for text that is too short (`MIN_TEXT_LENGTH=5`) or uncertain, in which case the session
  language is **preserved** (not overwritten). Afrikaans/Frisian/German (`af`, `fy`, `de`) are
  treated as Dutch aliases.
- `druppie/execution/human_input.py` (`HumanInput`) wraps incoming text and runs detection.

## Provider & model configuration

Translation uses **LiteLLM** (`ChatLiteLLM`, temperature `0.1`, `max_tokens=16384`,
`timeout=120s`, `max_retries=2`). The provider/model is resolved by
`TranslationService._resolve_translation_config()` in this priority order:

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

So translation is **no longer hard-wired to DeepInfra/Qwen**. In a default deployment with no
DeepInfra key and no override, it falls through to the general LLM provider. (The
`deepinfra_api_key_not_configured` startup warning in `core/config.py` reflects the *legacy*
assumption and is informational only.)

## Components

| Component | File | Responsibility |
|-----------|------|----------------|
| `TranslationService` (singleton `get_translation_service()`) | `druppie/core/translation.py` | The translator. `translate_to_english()`, `translate_from_english()`, `translate_label()` (short choice labels), `_translate()` (the LLM call), `_strip_thinking()` (removes `<think>` blocks), config resolution, and session-notification dedup (`mark_notified()`/`clear_session()`, 24h TTL, in-memory → single-worker). Raises `TranslationNotAvailableError` / `TranslationError`. |
| `LanguageDetector` | `druppie/core/language_detection.py` | Detects the user's language. |
| `HumanInput` | `druppie/execution/human_input.py` | Wraps user text + detection metadata. |
| Long-content chunking | `druppie/execution/tool_executor.py` → `_translate_long_content()` | Splits and translates long design docs. |
| Design/HITL/fallback seams | `druppie/execution/tool_executor.py` | `_translate_design_content()`, `DESIGN_TRANSLATION_PATHS`, HITL translation, `_notify_translation_unavailable()`. |
| Chat/summarizer translation | `druppie/agents/builtin_tools.py` → `create_message()` | Translates agent output for display. |
| English-only instruction | `druppie/agents/prompt_builder.py` | Injects the English-only block into every agent. |

## Data flow

**User input → English (agents).** `druppie/execution/orchestrator.py`: detect language; if
non-English, `translate_to_english()`. The English text feeds the router/planner and all agents.
Both versions are stored on the message — `content` (translated, for display) and `content_english`
(for agents). HITL answers are translated the same way but do **not** change `session.language`.

**Agent output → user's language.** Agents emit English; it is translated back at three seams:
- **Chat / summarizer messages** — `builtin_tools.create_message()` → `translate_from_english()`
  (stores translated as `content`, English as `content_english`).
- **HITL questions** — `tool_executor` translates the question via `translate_from_english()`, each
  choice via `translate_label()`, plus the context. English originals are preserved
  (`english_question` / `english_choices`).
- **Approval-gate design cards** — `_translate_design_content()` runs before the approval is
  created, so the reviewer sees the Dutch version.

**Design documents (dual-file, English = source of truth).** Only for `make_design`, only for a
Dutch session, and only for a known path in `DESIGN_TRANSLATION_PATHS`:

| English (source of truth) | Dutch (auto-generated copy) |
|---------------------------|-----------------------------|
| `docs/functional-design.md` | `docs/functioneel-ontwerp.md` |
| `docs/technical-design.md` | `docs/technisch-ontwerp.md` |
| `docs/technical-research.md` | `docs/technisch-onderzoek.md` |

`_translate_design_content()` translates the content and injects `translated_content` /
`translated_path` into the tool-call arguments. On MCP execution the **English** file is written
first, and only after it succeeds a **second `write_file` MCP call** writes the Dutch copy. The
approval card shows a **single file** — the session-language version (the English original is still
saved in the background).

**Language locking.** Set from the first user message (only `nl`/`en` stored; other languages →
`en`). HITL answers never flip it. It can be force-switched to `en` on translation failure.

## Long-document translation (chunking)

`_translate_long_content()` (`tool_executor.py`):
- `< 3000` chars → one `translate_from_english()` call.
- Otherwise split on markdown heading boundaries (`^#{1,3}`), group each heading with its body, and
  translate all chunks **concurrently** (`asyncio.gather`).
- Heading prefixes (`##`, `###`) are re-attached if the model dropped them.
- A failed chunk does **not** fail the whole document: it is wrapped in a visible
  `> **[NIET VERTAALD / NOT TRANSLATED]**` marker and logged (`translation_partially_failed`).

## Quality guards & known gaps

- **Hallucination guard (NL→EN only)** — `translate_to_english()` rejects output longer than
  `len(input) * 3 + 50` chars (logs `translation_hallucination_detected`) and returns the original
  text. This was added after the translator hallucinated a whole fake document when a short filename
  was misdetected as another language.
- **Label untranslated-retry** — `translate_label()` uses `_looks_untranslated()` (still English:
  exact match or >60 % word overlap) and retries with the full prompt.
- **`<think>` stripping** — `_strip_thinking()` removes reasoning blocks (including unclosed tags
  from truncated output).
- **Known gap — no hallucination/truncation guard on `translate_from_english()`.** The EN→NL path
  (design docs, HITL questions, chat messages) has **no** length/hallucination guard — only the
  NL→EN direction does. This is a tracked gap (issues #275/#278).
- **Known gap — no structural protection for frontmatter / IDs / code.** Translation is
  prompt-only ("preserve markdown, code blocks, headings…"); there is no code that strips or skips
  YAML frontmatter, element IDs, or fenced code before translating. Only documents in
  `DESIGN_TRANSLATION_PATHS` are ever translated, so decision docs (ADR/PRD/…) are not affected —
  but design-doc quality still depends on the prompt (issues #269/#240/#73).

## Error handling & fallback

- **`TranslationNotAvailableError`** (no provider/key): propagates through all handlers →
  `_notify_translation_unavailable()` / `_notify_translation_failed()` switch the session to English
  (`session_repo.update_language(..., "en")`) and inject a **bilingual** system message
  ("Vertaling niet beschikbaar / Translation unavailable"), **once** per session
  (`TranslationService.mark_notified()` dedup, shared across orchestrator + tool executor).
- **`TranslationError`** (runtime API error / empty response): now **propagates** (no silent English
  fallback). Orchestrator call sites catch it, post the bilingual notice and switch to English.
- **Ask-first LLM fallback** — separate but related: when a general LLM provider fails,
  `FallbackLLM` raises `FallbackAvailableError` and the UI shows a `FallbackModal`
  ("Switch this agent" / "Switch all agents" / "Cancel"). The translation model itself is
  overridable via `/models`. Verbose LiteLLM errors are shortened by `clean_llm_error()`
  (`druppie/llm/base.py`) and shown as inline red banners.

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

## Testing

- Agent tests: `testing/agents/ba-bilingual-fd.yaml` (full Dutch bilingual pipeline),
  `testing/agents/ba-english-fd-no-translation.yaml` (English, no translation).
- Judge checks: `testing/checks/ba-fd-bilingual.yaml`, `ba-fd-english-only.yaml`,
  `ba-fd-in-english.yaml`, `architect-reads-english-fd.yaml`.
- Unit: `druppie/tests/test_translation_validation.py`.

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
