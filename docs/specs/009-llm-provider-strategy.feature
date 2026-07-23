# @status active
# @superseded_by
# @adr 009-llm-provider-strategy.md
# @prd docs/prds/012-llm-provider-management.md
@adr docs/adrs/009-llm-provider-strategy.md
@prd docs/prds/012-llm-provider-management.md
Feature: LLM provider strategy with cross-provider fallback
  # The "why" (problem, goal, user journey) lives in the linked ADR (@adr).
  # This spec holds only the acceptance Scenarios below.

  Scenario: All providers go through the LiteLLM abstraction
    Given a configured LLM provider that is OpenAI-compatible
    When an agent calls the LLM
    Then the call is routed through LiteLLM
    And the response is normalized into a single LLMResponse shape regardless of provider

  Scenario: Agent resolves its provider from a named LLM profile
    Given an agent YAML with llm_profile set to "standard"
    And a profile defining an ordered list of provider and model pairs
    When the agent run starts
    Then the model resolver filters the profile by API-key availability
    And the first available entry becomes the primary provider
    And the second available entry becomes the fallback provider

  Scenario: Forced provider override takes precedence over the profile
    Given the LLM_FORCE_PROVIDER and LLM_FORCE_MODEL environment variables are set
    When any agent resolves its model
    Then the resolver uses the forced provider and model for all agents
    And the profile is ignored

  Scenario: Primary provider failure triggers the fallback provider
    Given an agent with a profile that has a primary and a fallback provider available
    When the primary provider raises an LLMError
    Then FallbackLLM retries the request on the fallback provider
    And the agent run continues without surfacing the primary failure

  Scenario: Invalid primary auth key still allows fallback to a different provider
    Given a primary provider whose API key is invalid
    When the primary raises an AuthenticationError
    Then the fallback provider (a different service) is attempted
    And the request succeeds if the fallback provider is healthy

  Scenario: Resolution decisions are observable
    Given one or more agents resolving their providers
    When a model is resolved
    Then a structured model_resolved event is logged
    And the /api/status endpoint exposes the loaded profiles and their provider chains

  Scenario: Agent with no profile falls back to the global default
    Given an agent YAML with no llm_profile set
    When the agent resolves its model
    Then the resolver falls back to the global LLM_PROVIDER environment variable
