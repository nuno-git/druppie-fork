---
id: fs-template
name: fs-template
command: npx
args:
  - "-y"
  - "@modelcontextprotocol/server-filesystem"
  - "./.druppie/plans/{{plan_id}}"
transport: stdio
tools:
  - name: read_file
    description: Read contents of a file
  - name: write_file
    description: Write content to a file
  - name: list_directory
    description: List files in a directory
  - name: create_directory
    description: Create a new directory
  - name: move_file
    description: Move or rename a file
---
# Plan Filesystem Template

This definition acts as a template for per-plan filesystem access.
When a plan starts, Druppie looks for this template.
It creates a new ephemeral MCP server named `plan-<PLAN-ID>-fs`,
substituting `{{plan_id}}` in the arguments.
This allows agents to access the specific directory for the current plan.
