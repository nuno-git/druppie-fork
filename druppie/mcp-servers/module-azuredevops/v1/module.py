"""Azure DevOps module — orchestrates read-only backlog access for one project.

Reads service-principal credentials and the single allowed project from the
environment, builds an AzureDevOpsClient, and exposes high-level read operations
consumed by the MCP tools. The project is fixed here; no operation accepts a
caller-supplied project.
"""

import logging
import os
from datetime import datetime, timezone

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


def _wiql_escape(value: str) -> str:
    return value.replace("'", "''")


def _display_name(field_value) -> str | None:
    if isinstance(field_value, dict):
        return field_value.get("displayName")
    return field_value


class AzureDevOpsModule:
    """High-level read-only backlog operations for the configured project."""

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
