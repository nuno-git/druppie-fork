"""Azure DevOps v1 — MCP Tool Definitions.

Access to backlog / work items of a SINGLE Azure DevOps project. The project is
fixed by server configuration (AZURE_DEVOPS_PROJECT) and is never a tool
argument, so an agent cannot access any other project in the organization.

Write tools (create_work_item, update_work_item) are gated by HITL approval in
the Druppie orchestration layer — they require human confirmation before executing.

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
        "Access to the backlog and work items of a single, pre-configured "
        "Azure DevOps project. You cannot choose or list other projects — "
        "every tool operates on the one configured project. Write operations "
        "(create, update, add comment) require human approval before execution."
    ),
)

module = AzureDevOpsModule()


@mcp.tool()
async def get_current_sprint(user_token: str | None = None) -> dict:
    """Get the current sprint (iteration) and all configured sprints.

    Returns the sprint that contains today's date as current_sprint, plus the
    full list of sprints with their date ranges. Use the sprint path (e.g.
    "AI-platform\\Sprint 11") as the iteration parameter in list_backlog_items
    to scope queries to a specific sprint.

    Returns:
        Dict with current_sprint (name, path, start/end dates) and all_sprints.
    """
    return await module.get_current_sprint(user_token=user_token)


@mcp.tool()
async def get_sprint_summary(iteration: str, user_token: str | None = None) -> dict:
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
    return await module.get_sprint_summary(iteration, user_token=user_token)


@mcp.tool()
async def list_backlog_items(
    work_item_type: str | None = None,
    state: str | None = None,
    board_column: str | None = None,
    iteration: str | None = None,
    assigned_to: str | None = None,
    limit: int = 100,
    user_token: str | None = None,
) -> dict:
    """List backlog / work items from the configured Azure DevOps project.

    Items are returned newest-changed first. Use get_work_item() for full detail
    including parent/child hierarchy and task progress.

    Args:
        work_item_type: Optional filter, e.g. "Product Backlog Item", "Bug", "Task", "Feature", "Epic".
        state: Optional state filter, e.g. "New", "Approved", "Committed", "In Progress", "Done".
        board_column: Optional board column filter (the lane on the board view), e.g. "New", "In Progress", "In Review", "Ready", "Done". Note: board_column can differ from state.
        iteration: Optional iteration/sprint path filter, e.g. "AI-platform\\Sprint 11". Use get_current_sprint() to find the current sprint path.
        assigned_to: Optional filter by assignee name (partial match), e.g. "Jane" or "Doe".
        limit: Maximum number of items to return (default 100).

    Returns:
        Dict with items (id, title, type, state, board_column, iteration, assigned_to, effort).
    """
    return await module.list_backlog_items(work_item_type, state, board_column, iteration, assigned_to, limit, user_token=user_token)


@mcp.tool()
async def get_work_item(item_id: int, user_token: str | None = None) -> dict:
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
    return await module.get_work_item(item_id, user_token=user_token)


@mcp.tool()
async def search_work_items(text: str, limit: int = 50, user_token: str | None = None) -> dict:
    """Search work items in the configured project by title/description text.

    Args:
        text: Free text to match against title or description.
        limit: Maximum number of items to return (default 50).

    Returns:
        Dict with the project name and matching items.
    """
    return await module.search_work_items(text, limit, user_token=user_token)


@mcp.tool()
async def get_work_item_comments(item_id: int, top: int = 50, user_token: str | None = None) -> dict:
    """Get comments on a work item, newest first.

    Args:
        item_id: The work item id.
        top: Maximum number of comments to return (default 50).

    Returns:
        Dict with comments (id, text, created_by, created_date, modified_date)
        and total_count.
    """
    return await module.get_work_item_comments(item_id, top, user_token=user_token)


@mcp.tool()
async def add_work_item_comment(item_id: int, text: str, user_token: str | None = None) -> dict:
    """Add a comment to a work item.

    This tool requires human approval before execution. The approver will
    see the comment text you provide.

    Args:
        item_id: The work item id to comment on.
        text: The comment text (plain text or HTML).

    Returns:
        Dict with success status and created comment (id, work_item_id, text,
        created_by, created_date).
    """
    return await module.add_work_item_comment(item_id, text, user_token=user_token)


@mcp.tool()
async def create_work_item(
    work_item_type: str,
    title: str,
    description: str | None = None,
    state: str | None = None,
    assigned_to: str | None = None,
    iteration: str | None = None,
    area_path: str | None = None,
    effort: float | None = None,
    tags: str | None = None,
    parent_id: int | None = None,
    user_token: str | None = None,
) -> dict:
    """Create a new work item in the configured Azure DevOps project.

    This tool requires human approval before execution. The approver will
    see all the fields you provide, so include a clear title and description.

    The hierarchy is: Epic > Feature > Product Backlog Item > Task > Bug.
    Use parent_id to place the new item under an existing parent (e.g., set
    parent_id to a Feature's id when creating a Product Backlog Item).

    Args:
        work_item_type: Type of work item. One of: "Epic", "Feature",
            "Product Backlog Item", "Task", "Bug".
        title: Title of the work item (required).
        description: HTML description of the work item.
        state: Initial state, e.g. "New", "Approved". Defaults to "New".
        assigned_to: Display name of the assignee, e.g. "Jane Doe".
        iteration: Iteration/sprint path, e.g. "AI-platform\\Sprint 11".
            Use get_current_sprint() to find available paths.
        area_path: Area path for classification. Defaults to project root.
        effort: Story points (numeric). Typically used on PBIs.
        tags: Semicolon-separated tags, e.g. "backend; api; urgent".
        parent_id: Work item id of the parent to link under.

    Returns:
        Dict with success status and created item (id, title, type, state, url).
    """
    return await module.create_work_item(
        work_item_type=work_item_type,
        title=title,
        description=description,
        state=state,
        assigned_to=assigned_to,
        iteration=iteration,
        area_path=area_path,
        effort=effort,
        tags=tags,
        parent_id=parent_id,
        user_token=user_token,
    )


@mcp.tool()
async def update_work_item(
    item_id: int,
    title: str | None = None,
    description: str | None = None,
    state: str | None = None,
    board_column: str | None = None,
    assigned_to: str | None = None,
    iteration: str | None = None,
    area_path: str | None = None,
    effort: float | None = None,
    tags: str | None = None,
    parent_id: int | None = None,
    user_token: str | None = None,
) -> dict:
    """Update an existing work item in the configured Azure DevOps project.

    This tool requires human approval before execution. The approver will
    see which fields you are changing, so only include fields you want to
    modify — omitted fields are left unchanged.

    Use get_work_item(item_id) first to see the current values before
    making changes.

    Prefer board_column over state when moving items on the board — Azure
    DevOps will automatically set the matching state. Setting state alone
    may not move the item to the expected board column when multiple columns
    share the same state.

    Args:
        item_id: The id of the work item to update.
        title: New title (omit to keep current).
        description: New HTML description (omit to keep current).
        state: New state, e.g. "New", "Approved", "Committed", "Done"
            (omit to keep current). Prefer board_column instead.
        board_column: New board column, e.g. "New", "Ready", "In Progress",
            "In Review", "Done" (omit to keep current). Azure DevOps
            automatically updates the state to match. This is the
            recommended way to move items on the board.
        assigned_to: New assignee display name (omit to keep current).
        iteration: New iteration/sprint path (omit to keep current).
        area_path: New area path (omit to keep current).
        effort: New effort/story points (omit to keep current).
        tags: New semicolon-separated tags. This REPLACES all existing
            tags (omit to keep current).
        parent_id: Add a parent link to this work item id. Note: this
            adds a NEW parent link; it does not remove existing parents.

    Returns:
        Dict with success status and updated item (id, title, type, state, url).
    """
    return await module.update_work_item(
        item_id=item_id,
        title=title,
        description=description,
        state=state,
        board_column=board_column,
        assigned_to=assigned_to,
        iteration=iteration,
        area_path=area_path,
        effort=effort,
        tags=tags,
        parent_id=parent_id,
        user_token=user_token,
    )
