"""Azure DevOps v1 — MCP Tool Definitions.

Read-only access to backlog / work items of a SINGLE Azure DevOps project. The
project is fixed by server configuration (AZURE_DEVOPS_PROJECT) and is never a
tool argument, so an agent cannot read any other project in the organization.

There is deliberately NO list_projects tool and no project parameter anywhere.
"""

import logging

from fastmcp import FastMCP

from .module import AzureDevOpsModule

logger = logging.getLogger("azuredevops-mcp")

MODULE_ID = "azuredevops"
MODULE_VERSION = "1.0.0"

mcp = FastMCP(
    "Azure DevOps v1",
    version=MODULE_VERSION,
    instructions=(
        "Read-only access to the backlog and work items of a single, "
        "pre-configured Azure DevOps project. You cannot choose or list other "
        "projects — every tool operates on the one configured project."
    ),
)

# Built once at import; raises (and stops the server) if creds/project are unset.
module = AzureDevOpsModule()


@mcp.tool()
async def list_backlog_items(
    work_item_type: str | None = None,
    state: str | None = None,
    limit: int = 100,
) -> dict:
    """List backlog / work items from the configured Azure DevOps project.

    Items are returned newest-changed first. Use get_work_item() for full detail.

    Args:
        work_item_type: Optional filter, e.g. "User Story", "Bug", "Task", "Epic".
        state: Optional state filter, e.g. "New", "Active", "Closed".
        limit: Maximum number of items to return (default 100).

    Returns:
        Dict with the project name and a list of items (id, title, type, state).
    """
    return await module.list_backlog_items(work_item_type, state, limit)


@mcp.tool()
async def get_work_item(item_id: int) -> dict:
    """Read full detail of one work item in the configured project.

    Args:
        item_id: The work item id (from list_backlog_items / search_work_items).

    Returns:
        Dict with the item's title, type, state, description, assignee, tags,
        and timestamps. Ids that belong to another project return an error.
    """
    return await module.get_work_item(item_id)


@mcp.tool()
async def search_work_items(text: str, limit: int = 50) -> dict:
    """Search work items in the configured project by title/description text.

    Args:
        text: Free text to match against title or description.
        limit: Maximum number of items to return (default 50).

    Returns:
        Dict with the project name and matching items (id, title, type, state).
    """
    return await module.search_work_items(text, limit)
