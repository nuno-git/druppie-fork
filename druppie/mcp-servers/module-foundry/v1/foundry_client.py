"""Thin wrapper around azure-ai-projects used by the Foundry MCP.

Isolates the Azure SDK surface: connection enumeration, deployed model
listing, tool-object construction, and agent creation. All public
methods return structured results (no exceptions propagate to the
caller) so MCP tools can map failures directly into `{ok: false, reason}`
responses.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("foundry-mcp.client")


# Mapping from azure connection `type` strings (case-insensitive match)
# to the Foundry tool types we surface in schema.ALLOWED_TOOL_TYPES.
# Multiple connection types can back a single tool (different SDK
# versions report slightly different strings).
CONNECTION_TYPE_TO_TOOL: dict[str, str] = {
    "groundingwithbingsearch": "bing_grounding",
    "apibinggrounding": "bing_grounding",
    "bing_grounding": "bing_grounding",
    "bingcustomsearch": "bing_custom_search",
    "azureaisearch": "azure_ai_search",
    "cognitivesearch": "azure_ai_search",
    "fabric": "microsoft_fabric",
    "microsoftfabric": "microsoft_fabric",
    "sharepoint": "sharepoint_grounding",
    "sharepointgrounding": "sharepoint_grounding",
    "microsoft365": "sharepoint_grounding",
    "m365": "sharepoint_grounding",
}


class FoundryClient:
    """Lazy, cached Azure AI Foundry client."""

    def __init__(self, endpoint: str | None = None):
        self.endpoint = endpoint or os.environ.get("FOUNDRY_PROJECT_ENDPOINT")
        self._client = None

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def _get_client(self):
        """Lazy-init the AIProjectClient using DefaultAzureCredential.

        Mirrors the exclude_environment_credential logic in
        druppie/services/foundry_service.py so a partially-populated
        env (TENANT_ID without CLIENT_ID) doesn't crash credential
        resolution.
        """
        if self._client is not None:
            return self._client
        if not self.endpoint:
            raise FoundryNotConfiguredError("FOUNDRY_PROJECT_ENDPOINT is not set")

        from azure.ai.projects import AIProjectClient
        from azure.identity import DefaultAzureCredential

        exclude_env = not os.environ.get("AZURE_CLIENT_ID")
        self._client = AIProjectClient(
            endpoint=self.endpoint,
            credential=DefaultAzureCredential(
                exclude_environment_credential=exclude_env,
            ),
        )
        return self._client

    def check_connection(self) -> dict:
        """Verify credentials and endpoint are usable."""
        if not self.endpoint:
            return {
                "ok": False,
                "reason": "FOUNDRY_PROJECT_ENDPOINT is not set",
                "code": "not_configured",
            }
        try:
            client = self._get_client()
            # Lightweight call that exercises auth + network
            list(client.agents.list(limit=1))
            return {"ok": True, "endpoint": self.endpoint}
        except FoundryNotConfiguredError as e:
            return {"ok": False, "reason": str(e), "code": "not_configured"}
        except Exception as e:
            logger.warning("foundry_connection_check_failed: %s", e)
            return {
                "ok": False,
                "reason": f"connection check failed: {e}",
                "code": "connection_error",
            }

    # ------------------------------------------------------------------
    # Enumeration
    # ------------------------------------------------------------------

    def list_connections(self) -> dict:
        """Enumerate project connections, bucketed by Foundry tool type."""
        try:
            client = self._get_client()
            raw = list(client.connections.list())
        except FoundryNotConfiguredError as e:
            return {"ok": False, "reason": str(e), "code": "not_configured"}
        except Exception as e:
            logger.warning("foundry_list_connections_failed: %s", e)
            return {
                "ok": False,
                "reason": f"failed to list connections: {e}",
                "code": "azure_error",
            }

        buckets: dict[str, list[dict]] = {}
        all_conns: list[dict] = []
        for conn in raw:
            conn_type_raw = str(getattr(conn, "type", "") or "")
            conn_id = getattr(conn, "id", None) or getattr(conn, "name", None)
            conn_name = getattr(conn, "name", None)
            normalized = conn_type_raw.replace("-", "").replace("_", "").lower()
            tool_type = CONNECTION_TYPE_TO_TOOL.get(normalized)
            entry = {
                "id": conn_id,
                "name": conn_name,
                "type": conn_type_raw,
                "tool_type": tool_type,
            }
            all_conns.append(entry)
            if tool_type:
                buckets.setdefault(tool_type, []).append(entry)
        return {"ok": True, "connections": all_conns, "by_tool_type": buckets}

    def list_deployed_models(self) -> dict:
        """Return names of model deployments available in the project.

        The SDK surface for this varies; we try the known shapes and
        fall back to an empty list with a reason rather than raising.
        """
        try:
            client = self._get_client()
        except FoundryNotConfiguredError as e:
            return {"ok": False, "reason": str(e), "code": "not_configured"}

        try:
            if hasattr(client, "deployments"):
                raw = list(client.deployments.list())
            else:
                return {
                    "ok": False,
                    "reason": "SDK has no deployments accessor",
                    "code": "unsupported",
                    "models": [],
                }
        except Exception as e:
            logger.warning("foundry_list_models_failed: %s", e)
            return {
                "ok": False,
                "reason": f"failed to list deployments: {e}",
                "code": "azure_error",
                "models": [],
            }

        models: list[dict] = []
        for dep in raw:
            name = getattr(dep, "name", None)
            model = getattr(dep, "model_name", None) or getattr(dep, "model", None)
            if name:
                models.append({"name": name, "model": model})
        return {"ok": True, "models": models}

    # ------------------------------------------------------------------
    # Tool construction & deploy
    # ------------------------------------------------------------------

    @staticmethod
    def build_tool_objects(tool_refs: list[dict]) -> list:
        """Map FoundryToolRef dicts to Azure SDK tool objects.

        Tools the current SDK doesn't expose (browser_automation,
        deep_research, etc.) are silently skipped — matches the
        existing FoundryService behavior. The validator runs before
        this, so inputs are already schema-valid.
        """
        if not tool_refs:
            return []

        from azure.ai.projects.models import (
            BingGroundingTool,
            CodeInterpreterTool,
            FileSearchTool,
        )

        # zero-config: no constructor args
        zero_config = {
            "code_interpreter": CodeInterpreterTool,
            "file_search": FileSearchTool,
        }
        # connection-backed: prefer passing connection_id, fall back to
        # no-arg instantiation for SDK versions that don't accept it
        connection_backed = {
            "bing_grounding": BingGroundingTool,
        }

        tools = []
        for ref in tool_refs:
            ttype = ref.get("type")
            cid = ref.get("connection_id")
            cls = zero_config.get(ttype) or connection_backed.get(ttype)
            if cls is None:
                logger.info("foundry_tool_type_not_supported_by_sdk: %s", ttype)
                continue
            if ttype in connection_backed and cid:
                try:
                    tools.append(cls(connection_id=cid))
                    continue
                except TypeError:
                    logger.info(
                        "foundry_tool_no_connection_id_kwarg: %s — using portal config",
                        ttype,
                    )
            tools.append(cls())
        return tools

    def create_agent(self, normalized: dict) -> dict:
        """Deploy a validated, normalized YAML payload to Foundry."""
        try:
            client = self._get_client()
        except FoundryNotConfiguredError as e:
            return {"ok": False, "reason": str(e), "code": "not_configured"}

        try:
            from azure.ai.projects.models import PromptAgentDefinition
        except ImportError as e:
            return {
                "ok": False,
                "reason": f"azure-ai-projects import failed: {e}",
                "code": "sdk_missing",
            }

        tools = self.build_tool_objects(normalized.get("tools", []))

        definition = PromptAgentDefinition(
            model=normalized["model"],
            instructions=normalized["instructions"],
            tools=tools if tools else None,
        )

        try:
            result = client.agents.create_version(
                agent_name=normalized["name"],
                definition=definition,
            )
        except Exception as e:
            logger.warning(
                "foundry_create_agent_failed: name=%s error=%s",
                normalized.get("name"),
                e,
            )
            return {
                "ok": False,
                "reason": f"Foundry rejected deployment: {e}",
                "code": "deploy_failed",
            }

        return {
            "ok": True,
            "foundry_agent_id": getattr(result, "id", None),
            "name": getattr(result, "name", normalized["name"]),
            "version": getattr(result, "version", None),
            "model": normalized["model"],
            "deployed_at": datetime.now(timezone.utc).isoformat(),
        }


class FoundryNotConfiguredError(Exception):
    """Raised when the project endpoint is missing."""
