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

module = AzureDevOpsModule()


@mcp.tool()
async def get_current_sprint() -> dict:
    """Get the current sprint (iteration) and all configured sprints.

    Returns the sprint that contains today's date as current_sprint, plus the
    full list of sprints with their date ranges. Use the sprint path (e.g.
    "AI-platform\\Sprint 11") as the iteration parameter in list_backlog_items
    to scope queries to a specific sprint.

    Returns:
        Dict with current_sprint (name, path, start/end dates) and all_sprints.
    """
    return await module.get_current_sprint()


@mcp.tool()
async def get_sprint_summary(iteration: str) -> dict:
    """Get an aggregated summary of a sprint: effort by person, board column
    distribution, completion percentage, and item counts by type and state.

    Use get_current_sprint() first to find the iteration path for the current sprint.

    Args:
        iteration: The iteration path, e.g. "AI-platform\\Sprint 11".

    Returns:
        Dict with total_items, by_state counts, by_board_column counts, by_type
        counts, effort_summary (total/done/remaining PBI effort + completion %),
        and by_person breakdown (effort and item counts per team member).
    """
    return await module.get_sprint_summary(iteration)


@mcp.tool()
async def list_backlog_items(
    work_item_type: str | None = None,
    state: str | None = None,
    board_column: str | None = None,
    iteration: str | None = None,
    assigned_to: str | None = None,
    limit: int = 100,
) -> dict:
    """List backlog / work items from the configured Azure DevOps project.

    Items are returned newest-changed first. Use get_work_item() for full detail
    including parent/child hierarchy and task progress.

    Args:
        work_item_type: Optional filter, e.g. "Product Backlog Item", "Bug", "Task", "Feature", "Epic".
        state: Optional state filter, e.g. "New", "Approved", "Committed", "In Progress", "Done".
        board_column: Optional board column filter (the lane on the board view), e.g. "New", "In Progress", "In Review", "Ready", "Done". Note: board_column can differ from state.
        iteration: Optional iteration/sprint path filter, e.g. "AI-platform\\Sprint 11". Use get_current_sprint() to find the current sprint path.
        assigned_to: Optional filter by assignee name (partial match), e.g. "Nuno" or "Kraljevic".
        limit: Maximum number of items to return (default 100).

    Returns:
        Dict with items (id, title, type, state, board_column, iteration, assigned_to, effort).
    """
    return await module.list_backlog_items(work_item_type, state, board_column, iteration, assigned_to, limit)


@mcp.tool()
async def get_work_item(item_id: int) -> dict:
    """Read full detail of one work item including its parent and children.

    The hierarchy in this project is: Epic → Feature → Product Backlog Item → Task.
    - Features span multiple sprints and describe high-level goals.
    - Product Backlog Items (PBIs) are the main board unit and contain implementation details.
    - Tasks are children of PBIs and track granular progress.

    The response includes:
    - parent: the parent work item (e.g. a PBI's parent Feature)
    - children: child work items (e.g. a PBI's Tasks or a Feature's PBIs)
    - children_summary: progress stats (total, done, in_progress, remaining, completion_pct)

    Args:
        item_id: The work item id.

    Returns:
        Dict with full item detail, parent, children, and children_summary.
    """
    return await module.get_work_item(item_id)


@mcp.tool()
async def search_work_items(text: str, limit: int = 50) -> dict:
    """Search work items in the configured project by title/description text.

    Args:
        text: Free text to match against title or description.
        limit: Maximum number of items to return (default 50).

    Returns:
        Dict with the project name and matching items.
    """
    return await module.search_work_items(text, limit)
