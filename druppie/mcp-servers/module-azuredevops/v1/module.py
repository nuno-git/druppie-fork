"""Azure DevOps module — orchestrates backlog access for one project.

Reads service-principal credentials and the single allowed project from the
environment, builds an AzureDevOpsClient, and exposes high-level read operations
consumed by the MCP tools. The project is fixed here; no operation accepts a
caller-supplied project.
"""

import logging
import os
from datetime import datetime, timezone

import httpx

from .client import AzureDevOpsClient

logger = logging.getLogger("azuredevops-mcp")

_SUMMARY_FIELDS = [
    "System.Id",
    "System.Title",
    "System.WorkItemType",
    "System.State",
    "System.BoardColumn",
    "System.IterationPath",
    "System.AssignedTo",
    "Microsoft.VSTS.Scheduling.Effort",
]
_DETAIL_FIELDS = _SUMMARY_FIELDS + [
    "System.Description",
    "System.CreatedDate",
    "System.ChangedDate",
    "System.Tags",
    "System.BoardColumnDone",
]

VALID_WORK_ITEM_TYPES = {"Epic", "Feature", "Product Backlog Item", "Task", "Bug"}

_FIELD_MAP = {
    "title": "System.Title",
    "description": "System.Description",
    "state": "System.State",
    "assigned_to": "System.AssignedTo",
    "iteration": "System.IterationPath",
    "area_path": "System.AreaPath",
    "effort": "Microsoft.VSTS.Scheduling.Effort",
    "tags": "System.Tags",
}


def _wiql_escape(value: str) -> str:
    return value.replace("'", "''")


def _display_name(field_value) -> str | None:
    if isinstance(field_value, dict):
        return field_value.get("displayName")
    return field_value


class AzureDevOpsModule:
    """High-level backlog operations for the configured project."""

    def __init__(self) -> None:
        self._project = os.getenv("AZURE_DEVOPS_PROJECT", "").strip()
        org_url = os.getenv("AZURE_DEVOPS_ORG_URL", "").strip()
        tenant_id = os.getenv("AZURE_DEVOPS_TENANT_ID", "").strip()
        client_id = os.getenv("AZURE_DEVOPS_CLIENT_ID", "").strip()
        client_secret = os.getenv("AZURE_DEVOPS_CLIENT_SECRET", "").strip()

        missing = [
            name
            for name, val in [
                ("AZURE_DEVOPS_ORG_URL", org_url),
                ("AZURE_DEVOPS_PROJECT", self._project),
                ("AZURE_DEVOPS_TENANT_ID", tenant_id),
                ("AZURE_DEVOPS_CLIENT_ID", client_id),
                ("AZURE_DEVOPS_CLIENT_SECRET", client_secret),
            ]
            if not val
        ]
        if missing:
            raise ValueError(
                "Azure DevOps MCP is misconfigured; missing env vars: "
                + ", ".join(missing)
            )

        self._client = AzureDevOpsClient(
            org_url=org_url,
            project=self._project,
            tenant_id=tenant_id,
            client_id=client_id,
            client_secret=client_secret,
        )
        logger.info("Azure DevOps MCP bound to project '%s'", self._project)

    @property
    def project(self) -> str:
        return self._project

    def _project_clause(self) -> str:
        return f"[System.TeamProject] = '{_wiql_escape(self._project)}'"

    @staticmethod
    def _summary(item: dict) -> dict:
        f = item.get("fields", {})
        return {
            "id": item.get("id"),
            "title": f.get("System.Title"),
            "type": f.get("System.WorkItemType"),
            "state": f.get("System.State"),
            "board_column": f.get("System.BoardColumn"),
            "iteration": f.get("System.IterationPath"),
            "assigned_to": _display_name(f.get("System.AssignedTo")),
            "effort": f.get("Microsoft.VSTS.Scheduling.Effort"),
        }

    def _extract_id_from_url(self, url: str) -> int | None:
        try:
            return int(url.rstrip("/").split("/")[-1])
        except (ValueError, IndexError):
            return None

    async def get_current_sprint(self) -> dict:
        """Return info about the current sprint (iteration) based on today's date."""
        try:
            iterations = await self._client.get_team_iterations()
            now = datetime.now(timezone.utc)
            current = None
            all_sprints = []
            for it in iterations:
                attrs = it.get("attributes", {})
                start = attrs.get("startDate")
                end = attrs.get("finishDate")
                sprint_info = {
                    "name": it.get("name"),
                    "path": it.get("path"),
                    "start_date": start,
                    "end_date": end,
                }
                all_sprints.append(sprint_info)
                if start and end:
                    start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
                    end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
                    if start_dt <= now <= end_dt:
                        current = sprint_info
            return {
                "success": True,
                "project": self._project,
                "current_sprint": current,
                "all_sprints": all_sprints,
            }
        except Exception as exc:
            logger.warning("get_current_sprint failed: %s", exc)
            return {"success": False, "error": str(exc)}

    async def list_backlog_items(
        self,
        work_item_type: str | None = None,
        state: str | None = None,
        board_column: str | None = None,
        iteration: str | None = None,
        assigned_to: str | None = None,
        limit: int = 100,
    ) -> dict:
        """List work items in the configured project, newest first."""
        clauses = [self._project_clause()]
        if work_item_type:
            clauses.append(
                f"[System.WorkItemType] = '{_wiql_escape(work_item_type)}'"
            )
        if state:
            clauses.append(f"[System.State] = '{_wiql_escape(state)}'")
        if board_column:
            clauses.append(
                f"[System.BoardColumn] = '{_wiql_escape(board_column)}'"
            )
        if iteration:
            clauses.append(
                f"[System.IterationPath] = '{_wiql_escape(iteration)}'"
            )
        if assigned_to:
            clauses.append(
                f"[System.AssignedTo] CONTAINS '{_wiql_escape(assigned_to)}'"
            )

        wiql = (
            "SELECT [System.Id] FROM WorkItems WHERE "
            + " AND ".join(clauses)
            + " ORDER BY [System.ChangedDate] DESC"
        )
        try:
            ids = await self._client.query_wiql(wiql, top=limit)
            items = await self._client.get_work_items(ids, fields=_SUMMARY_FIELDS)
            return {
                "success": True,
                "project": self._project,
                "items": [self._summary(i) for i in items],
                "count": len(items),
            }
        except Exception as exc:
            logger.warning("list_backlog_items failed: %s", exc)
            return {"success": False, "error": str(exc)}

    async def get_work_item(self, item_id: int) -> dict:
        """Return full detail for one work item, including parent and children."""
        try:
            item = await self._client.get_work_item(item_id)
            f = item.get("fields", {})

            parent_id = None
            child_ids = []
            for rel in item.get("relations", []):
                rel_type = rel.get("rel", "")
                linked_id = self._extract_id_from_url(rel.get("url", ""))
                if not linked_id:
                    continue
                if rel_type == "System.LinkTypes.Hierarchy-Reverse":
                    parent_id = linked_id
                elif rel_type == "System.LinkTypes.Hierarchy-Forward":
                    child_ids.append(linked_id)

            parent = None
            if parent_id:
                try:
                    parent_items = await self._client.get_work_items(
                        [parent_id],
                        fields=["System.Id", "System.Title", "System.WorkItemType", "System.State"],
                    )
                    if parent_items:
                        pf = parent_items[0].get("fields", {})
                        parent = {
                            "id": parent_items[0].get("id"),
                            "title": pf.get("System.Title"),
                            "type": pf.get("System.WorkItemType"),
                            "state": pf.get("System.State"),
                        }
                except Exception:
                    pass

            children = []
            if child_ids:
                try:
                    child_items = await self._client.get_work_items(
                        child_ids,
                        fields=[
                            "System.Id", "System.Title", "System.WorkItemType",
                            "System.State", "System.AssignedTo",
                            "Microsoft.VSTS.Scheduling.Effort",
                        ],
                    )
                    for ch in child_items:
                        cf = ch.get("fields", {})
                        children.append({
                            "id": ch.get("id"),
                            "title": cf.get("System.Title"),
                            "type": cf.get("System.WorkItemType"),
                            "state": cf.get("System.State"),
                            "assigned_to": _display_name(cf.get("System.AssignedTo")),
                            "effort": cf.get("Microsoft.VSTS.Scheduling.Effort"),
                        })
                except Exception:
                    pass

            return {
                "success": True,
                "project": self._project,
                "item": {
                    "id": item.get("id"),
                    "title": f.get("System.Title"),
                    "type": f.get("System.WorkItemType"),
                    "state": f.get("System.State"),
                    "board_column": f.get("System.BoardColumn"),
                    "board_column_done": f.get("System.BoardColumnDone"),
                    "iteration": f.get("System.IterationPath"),
                    "effort": f.get("Microsoft.VSTS.Scheduling.Effort"),
                    "description": f.get("System.Description"),
                    "assigned_to": _display_name(f.get("System.AssignedTo")),
                    "tags": f.get("System.Tags"),
                    "created_date": f.get("System.CreatedDate"),
                    "changed_date": f.get("System.ChangedDate"),
                    "parent": parent,
                    "children": children,
                    "children_summary": self._children_summary(children) if children else None,
                },
            }
        except Exception as exc:
            logger.warning("get_work_item(%s) failed: %s", item_id, exc)
            return {"success": False, "error": str(exc)}

    @staticmethod
    def _children_summary(children: list[dict]) -> dict:
        """Compute progress summary from child work items."""
        total = len(children)
        done = sum(1 for c in children if c.get("state") == "Done")
        in_progress = sum(1 for c in children if c.get("state") == "In Progress")
        return {
            "total": total,
            "done": done,
            "in_progress": in_progress,
            "remaining": total - done,
            "completion_pct": round(done / total * 100) if total else 0,
        }

    async def get_sprint_summary(self, iteration: str) -> dict:
        """Aggregate sprint-level stats: effort by person, by board column, progress."""
        try:
            clauses = [
                self._project_clause(),
                f"[System.IterationPath] = '{_wiql_escape(iteration)}'",
                "[System.State] <> 'Removed'",
            ]
            wiql = (
                "SELECT [System.Id] FROM WorkItems WHERE "
                + " AND ".join(clauses)
                + " ORDER BY [System.ChangedDate] DESC"
            )
            ids = await self._client.query_wiql(wiql, top=200)
            items = await self._client.get_work_items(ids, fields=_SUMMARY_FIELDS)

            by_type: dict[str, list] = {}
            by_board: dict[str, list] = {}
            by_person: dict[str, dict] = {}
            by_state: dict[str, int] = {}
            total_effort = 0.0
            done_effort = 0.0

            for item in items:
                s = self._summary(item)
                wit = s["type"] or "Unknown"
                board = s["board_column"] or "(none)"
                state = s["state"] or "Unknown"
                person = s["assigned_to"] or "(unassigned)"
                effort = s["effort"] or 0

                by_type.setdefault(wit, []).append(s)
                by_board.setdefault(board, []).append(s)
                by_state[state] = by_state.get(state, 0) + 1

                if wit == "Product Backlog Item":
                    total_effort += effort
                    if state == "Done" or board == "Done":
                        done_effort += effort

                    if person not in by_person:
                        by_person[person] = {"total_effort": 0, "done_effort": 0, "items": 0, "done_items": 0}
                    by_person[person]["total_effort"] += effort
                    by_person[person]["items"] += 1
                    if state == "Done" or board == "Done":
                        by_person[person]["done_effort"] += effort
                        by_person[person]["done_items"] += 1

            return {
                "success": True,
                "project": self._project,
                "iteration": iteration,
                "total_items": len(items),
                "by_state": by_state,
                "by_board_column": {col: len(items_list) for col, items_list in by_board.items()},
                "by_type": {t: len(items_list) for t, items_list in by_type.items()},
                "effort_summary": {
                    "total_pbi_effort": total_effort,
                    "done_pbi_effort": done_effort,
                    "remaining_pbi_effort": total_effort - done_effort,
                    "completion_pct": round(done_effort / total_effort * 100) if total_effort else 0,
                },
                "by_person": by_person,
            }
        except Exception as exc:
            logger.warning("get_sprint_summary failed: %s", exc)
            return {"success": False, "error": str(exc)}

    async def search_work_items(self, text: str, limit: int = 50) -> dict:
        """Find work items whose title or description contains `text`."""
        needle = _wiql_escape(text)
        wiql = (
            "SELECT [System.Id] FROM WorkItems WHERE "
            + self._project_clause()
            + f" AND ([System.Title] CONTAINS '{needle}'"
            + f" OR [System.Description] CONTAINS '{needle}')"
            + " ORDER BY [System.ChangedDate] DESC"
        )
        try:
            ids = await self._client.query_wiql(wiql, top=limit)
            items = await self._client.get_work_items(ids, fields=_SUMMARY_FIELDS)
            return {
                "success": True,
                "project": self._project,
                "items": [self._summary(i) for i in items],
                "count": len(items),
            }
        except Exception as exc:
            logger.warning("search_work_items failed: %s", exc)
            return {"success": False, "error": str(exc)}

    async def get_work_item_comments(self, item_id: int, top: int = 50) -> dict:
        """Return comments for a work item, newest first."""
        try:
            result = await self._client.get_work_item_comments(item_id, top=top, order="desc")
            comments = []
            for c in result.get("comments", []):
                comments.append({
                    "id": c.get("id"),
                    "text": c.get("text"),
                    "created_by": _display_name(c.get("createdBy")),
                    "created_date": c.get("createdDate"),
                    "modified_date": c.get("modifiedDate"),
                })
            return {
                "success": True,
                "project": self._project,
                "work_item_id": item_id,
                "comments": comments,
                "total_count": result.get("totalCount", len(comments)),
            }
        except Exception as exc:
            logger.warning("get_work_item_comments(%s) failed: %s", item_id, exc)
            return {"success": False, "error": str(exc)}

    async def add_work_item_comment(self, item_id: int, text: str) -> dict:
        """Add a comment to a work item."""
        try:
            result = await self._client.add_work_item_comment(item_id, text)
            return {
                "success": True,
                "project": self._project,
                "comment": {
                    "id": result.get("id"),
                    "work_item_id": result.get("workItemId"),
                    "text": result.get("text"),
                    "created_by": _display_name(result.get("createdBy")),
                    "created_date": result.get("createdDate"),
                },
            }
        except Exception as exc:
            logger.warning("add_work_item_comment(%s) failed: %s", item_id, exc)
            return {"success": False, "error": str(exc)}

    @staticmethod
    def _build_patch_operations(fields: dict) -> list[dict]:
        ops = []
        for key, value in fields.items():
            if value is None:
                continue
            ado_path = _FIELD_MAP.get(key)
            if ado_path is None:
                continue
            ops.append({
                "op": "add",
                "path": f"/fields/{ado_path}",
                "value": value,
            })
        return ops

    async def create_work_item(
        self,
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
    ) -> dict:
        """Create a new work item in the configured project."""
        if work_item_type not in VALID_WORK_ITEM_TYPES:
            return {
                "success": False,
                "error": f"Invalid work item type '{work_item_type}'. "
                         f"Valid types: {', '.join(sorted(VALID_WORK_ITEM_TYPES))}",
            }

        fields = {
            "title": title,
            "description": description,
            "state": state,
            "assigned_to": assigned_to,
            "iteration": iteration,
            "area_path": area_path,
            "effort": effort,
            "tags": tags,
        }
        operations = self._build_patch_operations(fields)

        if parent_id is not None:
            operations.append({
                "op": "add",
                "path": "/relations/-",
                "value": {
                    "rel": "System.LinkTypes.Hierarchy-Reverse",
                    "url": f"{self._client.org_url}/_apis/wit/workitems/{parent_id}",
                },
            })

        try:
            result = await self._client.create_work_item(work_item_type, operations)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 403 and "permissions to create tags" in str(exc) and tags:
                logger.warning("create_work_item: tag permission denied, retrying without tags")
                operations = [op for op in operations if op.get("path") != "/fields/System.Tags"]
                try:
                    result = await self._client.create_work_item(work_item_type, operations)
                except Exception as retry_exc:
                    logger.warning("create_work_item retry failed: %s", retry_exc)
                    return {"success": False, "error": str(retry_exc)}
            else:
                logger.warning("create_work_item failed: %s", exc)
                return {"success": False, "error": str(exc)}
        except Exception as exc:
            logger.warning("create_work_item failed: %s", exc)
            return {"success": False, "error": str(exc)}

        warning = None
        if tags and not result.get("fields", {}).get("System.Tags"):
            warning = "Tags were dropped — the service principal lacks tag-creation permissions."

        resp = {
            "success": True,
            "project": self._project,
            "item": {
                "id": result.get("id"),
                "title": result.get("fields", {}).get("System.Title"),
                "type": result.get("fields", {}).get("System.WorkItemType"),
                "state": result.get("fields", {}).get("System.State"),
                "url": result.get("_links", {}).get("html", {}).get("href"),
            },
        }
        if warning:
            resp["warning"] = warning
        return resp

    async def _discover_kanban_column_field(self, item_id: int) -> str | None:
        """Find the WEF Kanban.Column field reference name from a work item.

        Azure DevOps stores board column state in a team-specific field
        like ``WEF_<hex>_Kanban.Column``.  ``System.BoardColumn`` is
        read-only — this writable WEF field is what we need to PATCH.
        """
        item = await self._client.get_work_item(item_id)
        for field_name in item.get("fields", {}):
            if field_name.endswith("_Kanban.Column"):
                return field_name
        return None

    async def update_work_item(
        self,
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
    ) -> dict:
        """Update an existing work item in the configured project."""
        if state and board_column:
            return {
                "success": False,
                "error": "Cannot set both state and board_column — "
                         "board_column automatically updates the state.",
            }

        fields = {
            "title": title,
            "description": description,
            "state": state,
            "assigned_to": assigned_to,
            "iteration": iteration,
            "area_path": area_path,
            "effort": effort,
            "tags": tags,
        }
        operations = self._build_patch_operations(fields)

        if board_column:
            kanban_field = await self._discover_kanban_column_field(item_id)
            if kanban_field:
                operations.append({
                    "op": "add",
                    "path": f"/fields/{kanban_field}",
                    "value": board_column,
                })
            else:
                return {
                    "success": False,
                    "error": "Could not discover the Kanban column field for this work item. "
                             "The board may not be configured for this item type.",
                }

        if parent_id is not None:
            operations.append({
                "op": "add",
                "path": "/relations/-",
                "value": {
                    "rel": "System.LinkTypes.Hierarchy-Reverse",
                    "url": f"{self._client.org_url}/_apis/wit/workitems/{parent_id}",
                },
            })

        if not operations:
            return {"success": False, "error": "No fields to update."}

        try:
            result = await self._client.update_work_item(item_id, operations)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 403 and "permissions to create tags" in str(exc) and tags:
                logger.warning("update_work_item: tag permission denied, retrying without tags")
                operations = [op for op in operations if op.get("path") != "/fields/System.Tags"]
                if not operations:
                    return {"success": False, "error": "No fields to update (tags were the only change and the service principal lacks tag-creation permissions)."}
                try:
                    result = await self._client.update_work_item(item_id, operations)
                except Exception as retry_exc:
                    logger.warning("update_work_item retry failed: %s", retry_exc)
                    return {"success": False, "error": str(retry_exc)}
            else:
                logger.warning("update_work_item(%s) failed: %s", item_id, exc)
                return {"success": False, "error": str(exc)}
        except Exception as exc:
            logger.warning("update_work_item(%s) failed: %s", item_id, exc)
            return {"success": False, "error": str(exc)}

        warning = None
        if tags and not result.get("fields", {}).get("System.Tags"):
            warning = "Tags were dropped — the service principal lacks tag-creation permissions."

        resp = {
            "success": True,
            "project": self._project,
            "item": {
                "id": result.get("id"),
                "title": result.get("fields", {}).get("System.Title"),
                "type": result.get("fields", {}).get("System.WorkItemType"),
                "state": result.get("fields", {}).get("System.State"),
                "url": result.get("_links", {}).get("html", {}).get("href"),
            },
        }
        if warning:
            resp["warning"] = warning
        return resp
