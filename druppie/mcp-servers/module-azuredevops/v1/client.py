"""Thin async Azure DevOps REST client (read-only, single project).

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

# Fixed resource ID for the Azure DevOps API. The ".default" scope yields a token
# carrying whatever permissions the service principal was granted in Azure DevOps.
AZURE_DEVOPS_SCOPE = "499b84ac-1321-427f-aa17-267ca6975798/.default"

API_VERSION = "7.0"


class AzureDevOpsClient:
    """Read-only client bound to a single Azure DevOps project."""

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

    async def _auth_header(self) -> dict[str, str]:
        token = await self._credential.get_token(AZURE_DEVOPS_SCOPE)
        return {"Authorization": f"Bearer {token.token}"}

    async def _post(self, path: str, json_body: dict) -> dict:
        headers = await self._auth_header()
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self._org_url}/{path}",
                params={"api-version": API_VERSION},
                json=json_body,
                headers=headers,
            )
            resp.raise_for_status()
            return resp.json()

    async def _get(self, path: str, params: dict | None = None) -> dict:
        headers = await self._auth_header()
        query = {"api-version": API_VERSION, **(params or {})}
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{self._org_url}/{path}",
                params=query,
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
            {"$expand": "fields"},
        )

    async def get_team_iterations(self) -> list[dict]:
        """Fetch all iterations (sprints) for the default team."""
        result = await self._get(
            f"{self._project}/_apis/work/teamsettings/iterations",
        )
        return result.get("value", [])

    async def close(self) -> None:
        await self._credential.close()
