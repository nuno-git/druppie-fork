# @status active
# @superseded_by
# @adr docs/adrs/019-module-system-architecture.md
# @prd docs/prds/008-module-system.md
# Linked research: docs/research/003-module-convention.md (Module Convention — design rationale & approach selection)
# Linked ADR: docs/adrs/019-module-system-architecture.md (full technical contract)

@prd docs/prds/008-module-system.md
@adr docs/adrs/019-module-system-architecture.md
Feature: Module contract
  # The Druppie Module contract: how a module is structured (MODULE.yaml),
  # versioned, called, authenticated, metered, and discovered. The "why" lives
  # in the linked research 003; the full technical contract lives in
  # docs/adrs/019-module-system-architecture.md. This spec holds only the
  # acceptance Scenarios below.

  # --- Module validation -------------------------------------------------

  Scenario: A valid MODULE.yaml is required at the module root
    Given a module directory druppie/mcp-servers/module-<name>/
    When the module is packaged
    Then MODULE.yaml contains exactly the three required fields id, latest_version, and versions
    And MODULE.yaml is the only YAML manifest file in the module
    And the versions listed in MODULE.yaml match the vN directories mounted by server.py

  Scenario: Module id follows the naming convention
    Given a module directory druppie/mcp-servers/module-<name>/
    When MODULE.yaml is read
    Then the id is lowercase and may contain hyphens, matching the directory suffix <name>
    And the docker-compose service is named module-<name>
    And the container is named druppie-module-<name>
    And the module listens on a port in the 9010-9099 range

  Scenario: latest_version must point to a listed version
    Given a MODULE.yaml with versions ["1.0.0", "2.0.0"]
    When latest_version is set to "2.0.0"
    Then requests to /mcp are served by v2/tools.py
    But when latest_version is set to a value not present in versions
    Then the module fails to start with a configuration error

  # --- Version system ----------------------------------------------------

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

  Scenario: Each major version has no translation layer to other versions
    Given a module serving v1 and v2 simultaneously
    When a v1 client calls /v1/mcp
    Then it receives a response produced by v1/module.py only
    And no transformer converts the response to or from the v2 shape
    When a v2 client calls /v2/mcp
    Then it receives a response produced by v2/module.py only

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

  Scenario: Significant tool description change is a breaking change
    Given a module tool whose description drives LLM tool selection
    When the description is changed significantly enough to break existing LLM callers
    Then the change requires a new major version directory
    But clarifying wording that does not change the intended use is a minor bump in place

  Scenario: Cross-version database changes are additive only
    Given multiple major versions of a module sharing one module database
    When a newer version adds a database column
    Then the new column is defined with a DEFAULT value
    And no DROP, RENAME, or ALTER TYPE is applied to any object an older version uses
    And every version's code selects explicit columns and never uses SELECT *

  Scenario: Fresh install and upgrade run migrations in version order
    Given a module with v1/schema and v2/schema migration files
    When the module database is created fresh
    Then v1/schema/current.sql runs before v2/schema/current.sql
    When an existing v1 install is upgraded by adding v2
    Then all v2/schema/00N_*.sql files run in numeric order on top of the v1 final state
    And the _migrations table records version_dir and filename for each applied migration

  Scenario: All versions run indefinitely with no sunset
    Given a version listed in MODULE.yaml
    When no deprecation action is taken
    Then the version continues to be served at /vN/mcp
    And no 410 Gone response is ever returned for a listed version

  # --- Module discovery --------------------------------------------------

  Scenario: Agents discover modules via the list_druppie_modules builtin tool
    Given the Architect or Business Analyst agent
    When it calls list_druppie_modules with no arguments
    Then it receives a summary of every module: id, versions, latest version, type, and description
    When it calls list_druppie_modules with a module_id
    Then it receives the tool schemas for that module's latest version
    When it calls list_druppie_modules with a module_id and a specific version
    Then it receives the tool schemas for that specific version

  Scenario: list_druppie_modules filters by MCP category
    Given modules of type core, module, and both are registered
    When list_druppie_modules is called with category "core"
    Then only core-type modules are returned
    When it is called with category "module"
    Then only module-type modules are returned
    When it is called with category "both"
    Then only both-type modules are returned

  Scenario: list_druppie_modules is available only to Architect and Business Analyst
    Given the Architect and Business Analyst agents
    Then they have the list_druppie_modules builtin in their tool sets
    Given the Developer agent
    Then it does not have list_druppie_modules because it reads module code directly

  Scenario: SDK calls a module tool directly without a gateway proxy
    Given a generated application with the Druppie SDK configured
    When the app calls druppie.modules.call("ocr", "extract_text", args)
    Then the SDK resolves the module URL and POSTs directly to the module MCP server
    And no gateway service sits between the app and the module

  Scenario: SDK version pinning routes to the chosen major version
    Given a module serving v1 and v2
    When the SDK is constructed with module_versions {"ocr": "v1"}
    Then calls are routed to /v1/mcp
    When the SDK is constructed with module_versions {"ocr": "v2"}
    Then calls are routed to /v2/mcp
    When the SDK is constructed without version pinning
    Then calls are routed to /mcp which serves the latest version

  # --- Authentication & standard arguments -------------------------------

  Scenario: Modules authenticate Keycloak JWTs themselves without a gateway
    Given an incoming module MCP request
    When the request arrives at the module container
    Then the shared root auth.py validates the Keycloak JWT against the JWKS endpoint
    And the accepted token audience is druppie-modules or druppie-backend
    And no gateway proxy performs token validation on behalf of the module

  Scenario: Standard arguments identify exactly one calling context
    Given a module or both-type MCP tool that receives the standard arguments
    When the caller is a Druppie agent, session_id is set and app_id is null
    When the caller is a generated application, app_id is set and session_id is null
    Then user_id is always required and present
    But when both session_id and app_id are set the module rejects the call
    And when neither session_id nor app_id is set the module rejects the call

  Scenario: project_id is required for apps and optional for core
    Given a module or both-type MCP tool
    When the caller is a generated application, project_id is required and read from DRUPPIE_PROJECT_ID
    When the caller is a Druppie agent without a project, such as a general_chat session, project_id is null
    When the caller is a Druppie agent with a project, project_id is injected from the session

  Scenario: Sandbox agents use a short-lived OBO module token
    Given an agent about to launch in a sandbox
    When the sandbox is prepared
    Then Druppie core requests a short-lived OBO token from Keycloak with audience druppie-modules and a 15-minute TTL
    And the token is injected into the sandbox as the DRUPPIE_MODULE_TOKEN environment variable
    And the token sub carries the original user's identity so usage is attributed correctly
    And the module validates the token as a normal Keycloak JWT with no special handling

  Scenario: Token proves identity, arguments prove context
    Given an authenticated module call
    Then the Keycloak JWT proves who the user is
    And the standard MCP arguments carry the calling context (session_id XOR app_id, project_id)
    And these two concerns are never conflated

  # --- Module-owned storage ----------------------------------------------

  Scenario: Module-owned storage never touches Druppie's database
    Given a stateful module
    When the module persists its own data
    Then it writes to its own module database, never to Druppie's PostgreSQL
    And Druppie context such as user_id, session_id, and project_id is received via injected MCP arguments
    But the module never queries Druppie core tables

  Scenario: Stateless modules need no database
    Given a module that wraps an external API and holds no state
    When the module is deployed
    Then it has no module-<name>-db container and no MODULE_DB_URL environment variable
    And it still serves tools at /mcp and /health

  # --- Usage tracking ----------------------------------------------------

  Scenario: Module reports usage in _meta and the caller records it
    Given a successful module tool call
    When the module builds its response
    Then the response _meta contains module_id, module_version, and usage.cost_cents
    And the module itself does not write to the Druppie core database
    When the caller is Druppie core, a module_usage row is inserted into the Druppie database
    When the caller is the SDK, the usage is POSTed to /api/usage
    And the recorded usage carries user_id, project_id, and exactly one of session_id or app_id

  Scenario: Resource metrics are declared in tool meta and interpreted via tools/list
    Given a module tool that reports resource usage
    When the tool is defined in vN/tools.py
    Then @mcp.tool(meta={...}) declares resource_metrics with name, type, and unit for each metric
    And the response _meta.usage.resources carries the measured values as an object
    But the module_usage.resources column stores them as a JSON-serialized TEXT string, never JSONB
    And the analytics layer calls MCP tools/list to obtain the metric definitions for labeling

  Scenario: SDK usage reporting is fire-and-forget
    Given a generated application making module calls via the SDK
    When the SDK fails to POST a usage record to /api/usage
    Then the failure is logged but does not affect the calling application
    And the original module result is still returned to the caller

  # --- MCP server categories --------------------------------------------

  Scenario: MCP server category bounds who can reach a module
    Given an MCP server entry of type "core"
    Then it is reachable by Druppie agents and invisible to the SDK
    Given an MCP server entry of type "module"
    Then it is reachable by generated applications via the SDK
    Given an MCP server entry of type "both"
    Then it is reachable by agents with injected arguments and by apps with explicit arguments

  # --- Module lifecycle --------------------------------------------------

  Scenario: Module lifecycle from acceptance to availability
    Given a new reusable capability is proposed
    When the Architect evaluates it against the acceptance criteria (reuse, genericity, independence, ownership, no overlap)
    Then the Architect writes MODULE_SPEC.md combining functional requirements from the BA's FD with technical requirements
    When the Architect triggers the update_core intent
    Then a branch and PR are created on the Druppie core repo targeting colab-dev
    When the PR is reviewed and merged by a human
    Then the module is available to all applications

  Scenario: Module registration adds compose service and mcp_config entry
    Given a developed module in druppie/mcp-servers/module-<name>/
    When the module is registered
    Then a docker-compose service block is added for module-<name>
    And an mcp_config.yaml entry is added with url, type, tools, and inject rules
    And agent YAML files are updated to include the new module tools

  Scenario: Module container health is reported per version and in aggregate
    Given a deployed module serving v1 and v2
    When a GET /health request is made
    Then the response reports module_id, latest_version, and the full active_versions list
    When a GET /v1/health request is made
    Then the response reports the per-version status for v1
    When a GET /v9/health request is made for a version that does not exist
    Then the response is 404 not_found

  Scenario: Removing a version is a manual operational action
    Given a module whose MODULE.yaml lists versions ["1.0.0", "2.0.0"]
    When an operator removes "1.0.0" from versions, deletes the v1 directory, and redeploys
    Then /v1/mcp is no longer served
    And no automatic deprecation or 410 Gone mechanism is involved

  # --- Application access control (RBAC) --------------------------------

  Scenario: Application roles live in the app's own database, not Druppie's
    Given a Druppie-built application
    When the app defines roles and assigns users to them
    Then roles and user_roles are stored in the application's own database via the project template
    And Druppie's core database contains no application_roles or application_user_roles tables
    And role checks are performed locally without a network call to Druppie

  Scenario: The project template ships a working app out of the box
    Given a new Druppie project created from druppie/templates/project/
    When the project is built before any builder-agent code is added
    Then Keycloak login, logout, token refresh, and session middleware are already wired up
    And an RBAC admin page and role tables are present
    And the DruppieClient is initialized and a /health endpoint exists
    And a production Dockerfile has the SDK pre-installed
    And the builder agent only adds business logic on top

  # --- Backend API -------------------------------------------------------

  Scenario: Druppie backend exposes module and usage API routes
    Given the Druppie backend
    Then GET /api/modules lists all registered modules, optionally filtered by category
    And GET /api/modules/{module_id}/info returns module metadata including active versions and tools
    And POST /api/usage records a module usage event from the SDK
    And GET /api/usage queries usage analytics filtered by module_id, app_id, user_id, or period
