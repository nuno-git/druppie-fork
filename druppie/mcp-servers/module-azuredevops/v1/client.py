"""Thin async Azure DevOps REST client (single project).

Authenticates with an Entra ID service principal (client credentials) and talks
to the Azure DevOps REST API. Every call is hard-scoped to ONE project that is
read from configuration — there is no method that accepts a caller-chosen
project, so the client cannot be steered at a different project.

Access tokens are requested fresh from azure-identity on demand (the credential
caches in memory and refreshes near expiry) and are NEVER written to disk.
"""

import logging

import httpx
from azure.identity.aio import ClientSecretCredential

logger = logging.getLogger("azuredevops-mcp")

# Microsoft's well-known Application ID for the Azure DevOps REST API — the same
# across every Azure tenant. The ".default" suffix requests whatever permissions
# have been assigned to the service principal in Entra ID.
AZURE_DEVOPS_SCOPE = "499b84ac-1321-427f-aa17-267ca6975798/.default"

API_VERSION = "7.0"


class AzureDevOpsClient:
    """REST client bound to a single Azure DevOps project."""

    def __init__(
        self,
        org_url: str,
        project: str,
        tenant_id: str,
        client_id: str,
        client_secret: str,
    ) -> None:
        # The project is stored once here and injected into every request path /
        # WIQL query below. It is intentionally not a method parameter anywhere.
        self._org_url = org_url.rstrip("/")
        self._project = project
        self._credential = ClientSecretCredential(
            tenant_id=tenant_id,
            client_id=client_id,
            client_secret=client_secret,
        )

    @property
    def project(self) -> str:
        return self._project

    @property
    def org_url(self) -> str:
        return self._org_url

    async def _auth_header(self) -> dict[str, str]:
        token = await self._credential.get_token(AZURE_DEVOPS_SCOPE)
        return {"Authorization": f"Bearer {token.token}"}

    async def _post(self, path: str, json_body: dict, *, api_version: str = API_VERSION) -> dict:
        headers = await self._auth_header()
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self._org_url}/{path}",
                params={"api-version": api_version},
                json=json_body,
                headers=headers,
            )
            resp.raise_for_status()
            return resp.json()

    async def _get(self, path: str, params: dict | None = None, *, api_version: str = API_VERSION) -> dict:
        headers = await self._auth_header()
        query = {"api-version": api_version, **(params or {})}
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{self._org_url}/{path}",
                params=query,
                headers=headers,
            )
            resp.raise_for_status()
            return resp.json()

    async def _patch(self, path: str, operations: list[dict]) -> dict:
        import json as _json

        headers = await self._auth_header()
        headers["Content-Type"] = "application/json-patch+json"
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.patch(
                f"{self._org_url}/{path}",
                params={"api-version": API_VERSION},
                content=_json.dumps(operations),
                headers=headers,
            )
            resp.raise_for_status()
            return resp.json()

    async def _post_patch(self, path: str, operations: list[dict]) -> dict:
        import json as _json

        headers = await self._auth_header()
        headers["Content-Type"] = "application/json-patch+json"
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self._org_url}/{path}",
                params={"api-version": API_VERSION},
                content=_json.dumps(operations),
                headers=headers,
            )
            resp.raise_for_status()
            return resp.json()

    async def query_wiql(self, wiql: str, top: int) -> list[int]:
        """Run a WIQL query scoped to the configured project, return work-item ids."""
        # Project goes in the URL path so the query can only ever hit this project.
        result = await self._post(
            f"{self._project}/_apis/wit/wiql",
            {"query": wiql},
        )
        work_items = result.get("workItems", [])
        return [wi["id"] for wi in work_items[:top]]

    async def get_work_items(
        self, ids: list[int], fields: list[str] | None = None
    ) -> list[dict]:
        """Batch-fetch work items by id, scoped to the configured project."""
        if not ids:
            return []
        body: dict = {"ids": ids}
        if fields:
            body["fields"] = fields
        result = await self._post(
            f"{self._project}/_apis/wit/workitemsbatch",
            body,
        )
        return result.get("value", [])

    async def get_work_item(self, item_id: int) -> dict:
        """Fetch a single work item by id, scoped to the configured project."""
        # Routing through the project path means an id belonging to another
        # project returns 404, never another project's data.
        return await self._get(
            f"{self._project}/_apis/wit/workitems/{item_id}",
            {"$expand": "all"},
        )

    async def get_team_iterations(self) -> list[dict]:
        """Fetch all iterations (sprints) for the default team."""
        result = await self._get(
            f"{self._project}/_apis/work/teamsettings/iterations",
        )
        return result.get("value", [])

    async def create_work_item(
        self, work_item_type: str, operations: list[dict]
    ) -> dict:
        """Create a work item in the configured project."""
        return await self._post_patch(
            f"{self._project}/_apis/wit/workitems/${work_item_type}",
            operations,
        )

    async def update_work_item(
        self, item_id: int, operations: list[dict]
    ) -> dict:
        """Update a work item in the configured project."""
        return await self._patch(
            f"{self._project}/_apis/wit/workitems/{item_id}",
            operations,
        )

    async def get_work_item_comments(
        self, item_id: int, top: int | None = None, order: str = "desc"
    ) -> dict:
        """Fetch comments for a work item, scoped to the configured project."""
        params: dict[str, str] = {"order": order}
        if top is not None:
            params["$top"] = str(top)
        return await self._get(
            f"{self._project}/_apis/wit/workItems/{item_id}/comments",
            params,
            api_version="7.0-preview.3",
        )

    async def add_work_item_comment(self, item_id: int, text: str) -> dict:
        """Add a comment to a work item, scoped to the configured project."""
        return await self._post(
            f"{self._project}/_apis/wit/workItems/{item_id}/comments",
            {"text": text},
            api_version="7.0-preview.3",
        )

    async def close(self) -> None:
        await self._credential.close()
