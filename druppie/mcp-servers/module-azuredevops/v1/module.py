"""Azure DevOps module — orchestrates read-only backlog access for one project.

Reads service-principal credentials and the single allowed project from the
environment, builds an AzureDevOpsClient, and exposes high-level read operations
consumed by the MCP tools. The project is fixed here; no operation accepts a
caller-supplied project.
"""

import logging
import os

from .client import AzureDevOpsClient

logger = logging.getLogger("azuredevops-mcp")

# Fields we surface for list/detail views. System.* are the built-in fields.
_SUMMARY_FIELDS = [
    "System.Id",
    "System.Title",
    "System.WorkItemType",
    "System.State",
]
_DETAIL_FIELDS = _SUMMARY_FIELDS + [
    "System.Description",
    "System.AssignedTo",
    "System.CreatedDate",
    "System.ChangedDate",
    "System.Tags",
]


def _wiql_escape(value: str) -> str:
    """Escape a string literal for safe inclusion in a WIQL single-quoted value."""
    return value.replace("'", "''")


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
            # Fail fast at startup rather than half-configured at request time.
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
        }

    async def list_backlog_items(
        self,
        work_item_type: str | None = None,
        state: str | None = None,
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
        except Exception as exc:  # noqa: BLE001 — surface a clean error to the agent
            logger.warning("list_backlog_items failed: %s", exc)
            return {"success": False, "error": str(exc)}

    async def get_work_item(self, item_id: int) -> dict:
        """Return full detail for one work item in the configured project."""
        try:
            item = await self._client.get_work_item(item_id)
            f = item.get("fields", {})
            assigned = f.get("System.AssignedTo")
            if isinstance(assigned, dict):
                assigned = assigned.get("displayName")
            return {
                "success": True,
                "project": self._project,
                "item": {
                    "id": item.get("id"),
                    "title": f.get("System.Title"),
                    "type": f.get("System.WorkItemType"),
                    "state": f.get("System.State"),
                    "description": f.get("System.Description"),
                    "assigned_to": assigned,
                    "tags": f.get("System.Tags"),
                    "created_date": f.get("System.CreatedDate"),
                    "changed_date": f.get("System.ChangedDate"),
                },
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning("get_work_item(%s) failed: %s", item_id, exc)
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
        except Exception as exc:  # noqa: BLE001
            logger.warning("search_work_items failed: %s", exc)
            return {"success": False, "error": str(exc)}
