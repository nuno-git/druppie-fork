# @status active
# @superseded_by
# @adr docs/adrs/012-tool-schema-discovery.md
@adr docs/adrs/012-tool-schema-discovery.md
Feature: Tool Schema Discovery via MCP tools/list
  # The "why" (problem, goal, motivation) lives in the linked ADR (@adr).
  # This spec holds only the acceptance Scenarios below.

  Scenario: ToolRegistry discovers tools via tools/list at startup
    Given the MCP servers module-coding and module-docker are reachable
    When the backend starts up
    Then the ToolRegistry calls each server's tools/list endpoint
    And every @mcp.tool() defined in the module is present in the registry

  Scenario: The @mcp.tool() decorator is the single source of truth for schemas
    Given a module defines a tool with specific parameters in its v1/tools.py decorator
    When the ToolRegistry discovers that tool
    Then the ToolDefinition parameter schema equals the decorator-declared schema
    And the backend source contains no separate hardcoded copy of that schema

  Scenario: mcp_config.yaml does not contain tool schemas
    Given the druppie/core/mcp_config.yaml file
    When its contents are inspected
    Then it contains server URLs and approval rules and injection rules
    And it contains no tool parameter schemas

  Scenario: An unreachable server's tools are absent rather than mis-described
    Given an MCP server that is not reachable at startup
    When the ToolRegistry is built
    Then no tools from that server are registered
    And no stale schema for that server's tools is served to any agent

  Scenario: An agent receives only the tools permitted by its MCP permissions
    Given an agent definition that grants MCP access to "coding" and builtin tools "done" and "hitl_ask_question"
    When registry.get_tools_for_agent is called for that agent
    Then the returned tool set contains only coding-server tools plus the two builtin tools
    And no docker-server tools are present

  Scenario: Discovered schemas conform to OpenAI strict mode
    Given a discovered ToolDefinition for any MCP tool
    When it is converted via registry.to_openai_format()
    Then the function definition has strict set to true
    And every object schema has additionalProperties set to false
    And every property is listed in the required array
    And optional fields use the anyOf nullable pattern

  Scenario: Approval requirements are merged from mcp_config.yaml onto discovered tools
    Given a tool whose approval requirement is declared in mcp_config.yaml
    When the ToolRegistry discovers that tool via tools/list
    Then the resulting ToolDefinition carries the approval requirement from mcp_config.yaml
    And the approval requirement is not part of the decorator schema
