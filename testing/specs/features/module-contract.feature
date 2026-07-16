# @status active
# @superseded_by
# @adr
# @prd docs/prds/008-module-system.md
# Linked research: docs/research/003-module-convention.md (Module Convention — design rationale & approach selection)
# Source reference: docs/reference/module-specification.md (full technical contract; behavioral layer superseded by this spec)

@prd docs/prds/008-module-system.md
Feature: Module contract
  # The Druppie Module contract: how a module is structured (MODULE.yaml),
  # versioned, called, authenticated, metered, and discovered. The "why" lives in
  # the linked research 003; the full technical contract lives in
  # docs/reference/module-specification.md. This spec holds only the acceptance
  # Scenarios below.

  Scenario: MODULE.yaml declares identity and active versions
    Given a module directory druppie/mcp-servers/module-<name>/
    When the module is packaged
    Then MODULE.yaml contains exactly the three required fields id, latest_version, and versions
    And MODULE.yaml is the only YAML manifest file in the module
    And the versions listed in MODULE.yaml match the vN directories mounted by server.py

  Scenario: Path-based version routing serves each major version
    Given a module whose MODULE.yaml declares latest_version "2.0.0" and versions ["1.0.0", "2.0.0"]
    When a request hits /v1/mcp
    Then it is served by v1/tools.py
    When a request hits /v2/mcp
    Then it is served by v2/tools.py
    When a request hits /mcp
    Then it is served by the latest version, v2

  Scenario: Adding a new major version leaves previous versions untouched
    Given a module already serving v1 at /v1/mcp
    When a v2 directory is added and MODULE.yaml latest_version is set to "2.0.0"
    Then v1 code and v1 schema remain unchanged
    And existing /v1/mcp clients keep receiving v1 responses
    And v2 is served independently at /v2/mcp

  Scenario: Breaking change requires a new major version directory
    Given a module at major version 1
    When a tool, parameter, or response field is removed or renamed, or a field type or semantics change
    Then the change is made in a new v2/ directory, not in v1/
    And the major bump creates v2/module.py and v2/tools.py
    But v1/ is not modified to introduce the breaking change

  Scenario: Non-breaking change updates the version in place
    Given a module at version 1.0.0
    When a new optional parameter with a default, a new response field, or a new tool is added
    Then the change is made in place inside v1/
    And the version is bumped to a higher minor or patch number within v1/
    And no new vN directory is created

  Scenario: Cross-version database changes are additive only
    Given multiple major versions of a module sharing one module database
    When a newer version adds a database column
    Then the new column is defined with a DEFAULT value
    And no DROP, RENAME, or ALTER TYPE is applied to any object an older version uses
    And every version's code selects explicit columns and never uses SELECT *

  Scenario: Standard arguments identify exactly one calling context
    Given a module or both-type MCP tool that receives the standard arguments
    When the caller is a Druppie agent, session_id is set and app_id is null
    When the caller is a generated application, app_id is set and session_id is null
    Then user_id is always required and present
    But when both session_id and app_id are set the module rejects the call
    And when neither session_id nor app_id is set the module rejects the call

  Scenario: Modules authenticate Keycloak JWTs themselves without a gateway
    Given an incoming module MCP request
    When the request arrives at the module container
    Then the shared root auth.py validates the Keycloak JWT against the JWKS endpoint
    And the accepted token audience is druppie-modules or druppie-backend
    And no gateway proxy performs token validation on behalf of the module

  Scenario: Module reports usage in _meta and the caller records it
    Given a successful module tool call
    When the module builds its response
    Then the response _meta contains module_id, module_version, and usage.cost_cents
    And the module itself does not write to the Druppie core database
    When the caller is Druppie core, a module_usage row is inserted into the Druppie database
    When the caller is the SDK, the usage is POSTed to /api/usage
    And the recorded usage carries user_id, project_id, and exactly one of session_id or app_id

  Scenario: Module-owned storage never touches Druppie's database
    Given a stateful module
    When the module persists its own data
    Then it writes to its own module database, never to Druppie's PostgreSQL
    And Druppie context such as user_id, session_id, and project_id is received via injected MCP arguments
    But the module never queries Druppie core tables

  Scenario: MCP server category bounds who can reach a module
    Given an MCP server entry of type "core"
    Then it is reachable by Druppie agents and invisible to the SDK
    Given an MCP server entry of type "module"
    Then it is reachable by generated applications via the SDK
    Given an MCP server entry of type "both"
    Then it is reachable by agents with injected arguments and by apps with explicit arguments

  Scenario: Agents discover modules via the list_druppie_modules builtin tool
    Given the Architect or Business Analyst agent
    When it calls list_druppie_modules with no arguments
    Then it receives a summary of every module: id, versions, latest version, type, and description
    When it calls list_druppie_modules with a module_id
    Then it receives the tool schemas for that module's latest version
    When it calls list_druppie_modules with a module_id and a specific version
    Then it receives the tool schemas for that specific version
