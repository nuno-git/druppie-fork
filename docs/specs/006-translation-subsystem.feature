@prd docs/prds/006-translation-subsystem.md
@adr docs/adrs/006-translation-subsystem.md
Feature: Bilingual Translation Subsystem
  # Acceptance criteria for the translation service.

  Scenario: Dutch input is translated to English
    Given the translation service is available
    And an agent output written in Dutch
    When the consumer requests translation to English
    Then the service returns the output translated to English
    And the meaning of the original Dutch text is preserved

  Scenario: English input is translated to Dutch
    Given the translation service is available
    And an agent output written in English
    When the consumer requests translation to Dutch
    Then the service returns the output translated to Dutch
    And the meaning of the original English text is preserved

  Scenario: Markdown formatting is preserved during translation
    Given the translation service is available
    And an agent output containing markdown headings and lists
    When the consumer requests translation to a target language
    Then the translated output preserves the markdown heading levels
    And the translated output preserves the list structure

  Scenario: Code blocks are not translated
    Given the translation service is available
    And an agent output containing a fenced code block
    When the consumer requests translation to a target language
    Then the prose around the code block is translated
    And the contents of the code block remain unchanged

  Scenario: File paths are not translated
    Given the translation service is available
    And an agent output containing file paths and directory references
    When the consumer requests translation to a target language
    Then the prose is translated
    And every file path and directory reference remains unchanged

  Scenario: Translation model is configurable via environment variable
    Given the translation model is set through an environment variable
    When the translation service initializes
    Then the service uses the configured translation model
    And swapping the environment value changes the active model without code changes

  Scenario: Translation is opt-in per request
    Given an agent output produced in a single language
    When the consumer does not request translation
    Then the service returns the original output without translation
    And no translation model call is made

  Scenario: Language is auto-detected when not specified
    Given the translation service is available
    And an agent output whose input language is not declared
    When the consumer requests translation to a target language
    Then the service auto-detects the input language using heuristic checks
    And the service translates from the detected language to the target language
