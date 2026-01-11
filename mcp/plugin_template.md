---
id: plugin-template
name: plugin-template
command: npx
args:
  - "-y"
  - "@modelcontextprotocol/server-filesystem"
  - "./.druppie/plans/{{plan_id}}/builds/{{build_id}}"
transport: stdio
tools:
  - name: read_file
    description: Read contents of a plugin file
  - name: write_file
    description: Write content to a plugin file
  - name: list_directory
    description: List files in the plugin directory
  - name: execute_plugin
    description: Execute the plugin for testing
---
# Plan Plugin Testing Template

This definition acts as a template for testing plugins built within a plan.
When a converter build completes, Druppie creates an ephemeral MCP server named `plan-<PLAN-ID>-plugin`,
substituting `{{plan_id}}` and `{{build_id}}` in the arguments.

This allows agents to:
1. Inspect the built plugin code
2. Test the plugin functionality
3. Validate the plugin before promotion to core

Once validated, use the `promote_plugin` action to move the plugin to `.druppie/plugins/` where it becomes available as a system-wide MCP server.
