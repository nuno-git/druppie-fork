# Automated Translation (Bilingual Support)

The Druppie platform supports bilingual sessions: users interact in their own language while agents always work in English. The platform translates transparently at every boundary.

---

## Design Principles

1. **Agents are monolingual English.** Every agent receives a fixed English-only instruction block. This keeps prompts simple and avoids language-mixing in LLM output.
2. **The platform translates, not the agents.** Translation happens at the orchestrator and tool executor layers — agents never see non-English text.
3. **Session language is locked early.** The first user message sets the session language. HITL answers do not change it, preventing accidental language flips.
4. **Fail loudly on misconfiguration.** A missing `DEEPINFRA_API_KEY` raises `TranslationNotAvailableError` rather than silently serving untranslated text.

---

## Configuration

Set `DEEPINFRA_API_KEY` in `.env`:

```
DEEPINFRA_API_KEY=your_key_here
```

The translation service uses **Qwen/Qwen3-32B on DeepInfra** (`https://api.deepinfra.com/v1/openai`). This is independent of the main `LLM_PROVIDER` — even if your agents use Z.AI or Azure Foundry, translation always goes through DeepInfra.

If the key is not set:
- The backend logs a **warning** at startup (`deepinfra_api_key_not_configured`).
- The first translation attempt raises `TranslationNotAvailableError`, which propagates and fails the session with a clear error message.

---

## Components

### TranslationService (`druppie/core/translation.py`)

Singleton accessed via `get_translation_service()`. Two public methods:

- `translate_to_english(text, source_language)` — for user input.
- `translate_from_english(text, target_language)` — for agent output.

Both are no-ops when the source/target is English or the text is very short (< 5 chars). Uses `/no_think` prefix to suppress Qwen's chain-of-thought, and strips any `<think>` blocks from output.

Long markdown content (> 3000 chars) is split on heading boundaries and translated in parallel chunks via `asyncio.gather`.

### LanguageDetector (`druppie/core/language_detection.py`)

Hybrid detection combining:
- **Keyword heuristics** — Dutch and English word lists for fast classification.
- **`langdetect` library** — statistical fallback for ambiguous text.

Language mapping:
- `nl` → Dutch session (full translation support).
- `en` → English session (no translation).
- Afrikaans (`af`), Frisian (`fy`), German (`de`) → treated as Dutch aliases.
- All other detected languages → session defaults to `en`, but input is still translated to English for the agent.

### HumanInput (`druppie/execution/human_input.py`)

Wraps raw user text with detected language metadata. Used by the orchestrator to decide whether translation is needed.

---

## Data Flow

### User Message (Orchestrator)

```
1. User sends message (any language)
2. HumanInput detects language via LanguageDetector
3. Session language updated (only if detection succeeds; only nl/en stored)
4. If non-English: translate message to English via TranslationService
5. English message passed to Router → Planner → Agent pipeline
```

### HITL Question (Tool Executor)

```
1. Agent produces English HITL question (hitl_ask_question / hitl_ask_multiple_choice_question)
2. Tool executor checks session.language
3. If non-English: translate question text and all choice labels
4. Store translated text in Question record (shown to user)
```

### HITL Answer (Orchestrator)

```
1. User answers in their language
2. Detect language (do NOT update session language — it's locked)
3. If non-English: translate answer to English
4. Pass English answer to agent; preserve original for UI display
```

### Design Documents (Tool Executor)

```
1. Agent calls submit_design_for_review with English content and path (e.g., docs/functional-design.md)
2. Tool executor checks session.language and path against DESIGN_TRANSLATION_PATHS
3. If Dutch session + known path:
   a. Translate content (chunked for long documents)
   b. Inject translated_content and translated_path into tool call arguments
   c. Approval card shows Dutch version
4. After English MCP write_file succeeds:
   a. Second MCP write_file call writes the Dutch file (e.g., docs/functioneel-ontwerp.md)
```

Translation path mapping:

| English | Dutch |
|---------|-------|
| `docs/functional-design.md` | `docs/functioneel-ontwerp.md` |
| `docs/technical-design.md` | `docs/technisch-ontwerp.md` |
| `docs/technical-research.md` | `docs/technisch-onderzoek.md` |

### Summarizer Message (Builtin Tools)

```
1. Summarizer agent produces English completion message via create_message
2. Check session.language
3. If non-English: translate to user's language
4. Store translated message in chat timeline
```

---

## Agent Prompt Integration

`prompt_builder.py` injects a fixed English-only instruction block at the top of every agent's system prompt:

> You MUST write ALL artifacts (functional designs, technical designs, research documents, code, configuration) in **English**.
> The platform automatically translates documents for non-English users.

This block is the same regardless of session language — agents never know what language the user speaks.

Individual agent YAML files (`business_analyst.yaml`, `architect.yaml`) reinforce this in their "ARTIFACT LANGUAGE" sections, explicitly naming the English file paths and explaining that the platform handles localization.

---

## Error Handling

| Scenario | Behavior |
|----------|----------|
| `DEEPINFRA_API_KEY` not set | Startup warning + `TranslationNotAvailableError` on first translation attempt |
| DeepInfra API returns error (401, 500, timeout) | Warning logged, original English text returned (graceful degradation) |
| Empty translation response | Warning logged, original text returned |
| Language detection fails (text too short) | Session language unchanged, no translation attempted |

`TranslationNotAvailableError` is explicitly re-raised in all `except Exception` handlers (`tool_executor.py`, `builtin_tools.py`), ensuring that a missing API key is never silently swallowed.

---

## Database

| Table | Column | Type | Purpose |
|-------|--------|------|---------|
| `sessions` | `language` | VARCHAR(10), nullable | Detected session language (`nl`, `en`, or null) |

---

## Testing

Test agents in `testing/agents/`:
- `ba-bilingual-fd.yaml` — Dutch user triggers full pipeline: English FD + Dutch translation.
- `ba-english-fd-no-translation.yaml` — English session produces no translation fields.

Judge checks in `testing/checks/`:
- `ba-fd-bilingual.yaml` — Verifies `translated_content`/`translated_path` present for Dutch sessions.
- `ba-fd-english-only.yaml` — Verifies translation fields absent for English sessions.
- `ba-fd-in-english.yaml` — Verifies FD content is English regardless of session language.
- `architect-reads-english-fd.yaml` — Verifies architect reads `docs/functional-design.md`, not the Dutch path.

Unit tests in `druppie/tests/`:
- `test_translation_validation.py` — Tests `TranslationNotAvailableError` on missing key, startup warning.
