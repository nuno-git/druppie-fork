# @status draft
# @superseded_by
# @adr 017-observability-strategy.md

@adr docs/adrs/017-observability-strategy.md
Feature: Observability Strategy
  # The "why" (problem, goal) lives in the linked ADR (@adr).
  # This spec holds only the acceptance Scenarios below.
  # Status draft: the ADR is `proposed` and not yet implemented; these scenarios
  # describe the intended behaviour once the three-pillar observability stack is in place.

  Scenario: All logging is structured through a single standard
    Given the LLM providers and the rest of the backend
    When logs are emitted during an agent execution
    Then every log line is emitted via structlog
    And no print() statements remain in the codebase

  Scenario: Logs are structured and joinable to traces and DB rows
    Given a running agent execution
    When a log event is emitted
    Then the log carries consistent fields session id, agent id, agent run id, tool call id, and LLM call id
    And the log is JSON-formatted so it can be aggregated and queried

  Scenario: Agent execution metrics are exposed in Prometheus format
    Given the backend is running with the observability stack
    When a metrics endpoint is scraped
    Then agent run duration histograms are available
    And tool-call counts and latencies are available
    And LLM call counts, latencies, token usage, and cost gauges are available
    And retry counts backed by the llm_retries table are available

  Scenario: An agent execution is traceable end-to-end
    Given an API request that triggers a multi-agent run
    When the request is processed through orchestrator, agent, MCP tool, and LLM call
    Then a single distributed trace spans all of those stages
    And each stage appears as a span with timing data

  Scenario: Cost and token usage are observable per session, agent, and project
    Given a session that has consumed LLM tokens across several agents
    When an operator inspects the observability dashboard
    Then aggregated token usage and cost are visible at session, agent, and project levels

  Scenario: Metrics avoid high-cardinality labels
    Given the defined metric set
    When metrics are labelled
    Then histograms do not carry per-session labels
    And label cardinality stays bounded

  Scenario: Observability stack runs in the dev environment
    Given the dev Docker Compose profile is started
    When an operator opens the dashboards
    Then metrics, structured logs, and traces are all reachable locally
    And no third-party SaaS account is required

  Scenario: The durable audit trail is preserved alongside live observability
    Given the observability stack is in place
    When an agent run completes
    Then the llm_retries and tool_call_normalizations audit rows are still written
    And live observability complements rather than replaces the durable record
