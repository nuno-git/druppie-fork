@adr docs/adrs/002-platform-mediated-translation.md
Feature: Platform translation quality and error guards
  # The decision and rationale live in the linked ADR (@adr). This spec holds only the
  # testable behaviour of the translation guards and fail-loud fallbacks.

  Scenario: Hallucination guard rejects an over-long NL to EN translation
    Given a short Dutch input of N characters
    When translate_to_english produces output longer than N * 3 + 50 characters
    Then the guard logs "translation_hallucination_detected"
    And the original untranslated input is returned instead of the hallucinated output

  Scenario: Label translation retries when the output is still English
    Given a short Dutch choice label is translated with translate_label
    When the result is an exact match or has more than 60% word overlap with the English input
    Then the label is detected as untranslated
    And translate_label retries once with the full translation prompt

  Scenario: A failed chunk in a long document is marked, not fatal
    Given a design document longer than 3000 characters split into markdown-heading chunks
    When one chunk fails to translate while the others succeed
    Then that chunk is wrapped in a visible "> **[NIET VERTAALD / NOT TRANSLATED]**" marker
    And the event "translation_partially_failed" is logged
    And the document is still delivered with the successfully translated chunks

  Scenario: Missing translation provider fails loud and switches to English
    Given a Dutch session with no configured translation provider or API key
    When a translation is attempted
    Then a TranslationNotAvailableError is raised
    And the session language is switched to "en"
    And a bilingual "Vertaling niet beschikbaar / Translation unavailable" notice is posted once per session

  Scenario: A runtime translation error propagates instead of serving untranslated text
    Given a configured translation provider that returns a runtime API error or empty response
    When translation of a message is attempted
    Then a TranslationError propagates to the orchestrator call site
    And the session is switched to English with a bilingual notice
    And no untranslated text is served as if it were translated

  Scenario: Ask-first fallback offers a switch when a general LLM provider fails
    Given a general LLM provider that fails during an agent run
    When FallbackLLM raises FallbackAvailableError
    Then the UI shows a FallbackModal with "Switch this agent", "Switch all agents" and "Cancel"
    And no agent output is produced until the user chooses an option
