"""Azure AI Foundry deployment service."""

import hashlib
import json
import structlog
from datetime import datetime, timezone

logger = structlog.get_logger()

def _default_foundry_model() -> str:
    import os
    return os.environ.get("FOUNDRY_MODEL", "gpt-4.1-mini")


class FoundryService:
    """Deploys agent definitions to Azure AI Foundry."""

    def __init__(self, endpoint: str | None = None):
        self.endpoint = endpoint
        self._client = None

    def _get_client(self):
        """Lazy-initialize the Foundry client.

        Uses DefaultAzureCredential which tries, in order:
        1. EnvironmentCredential (AZURE_CLIENT_ID + AZURE_CLIENT_SECRET + AZURE_TENANT_ID)
        2. ManagedIdentityCredential (Azure-hosted containers)
        3. AzureDeveloperCliCredential (azd on PATH)
        4. AzureCliCredential (az login)

        If AZURE_TENANT_ID is set but AZURE_CLIENT_ID is not,
        EnvironmentCredential is excluded to avoid a ValueError.
        """
        if self._client is not None:
            return self._client
        if not self.endpoint:
            raise FoundryNotConfiguredError("FOUNDRY_PROJECT_ENDPOINT is not set")
        try:
            import os
            from azure.ai.projects import AIProjectClient
            from azure.identity import DefaultAzureCredential

            # Skip EnvironmentCredential when client_id is missing —
            # it would crash with "client_id should be the id of a
            # Microsoft Entra application" if only AZURE_TENANT_ID is set.
            exclude_env = not os.environ.get("AZURE_CLIENT_ID")

            self._client = AIProjectClient(
                endpoint=self.endpoint,
                credential=DefaultAzureCredential(
                    exclude_environment_credential=exclude_env,
                ),
            )
            return self._client
        except ImportError:
            raise FoundryNotConfiguredError(
                "azure-ai-projects package not installed. Run: pip install azure-ai-projects azure-identity"
            )

    @staticmethod
    def compute_spec_hash(agent_detail) -> str:
        """Compute a SHA-256 hash of the fields sent to Foundry.

        Used to detect drift between the local definition and the deployed version.
        """
        canonical = {
            "model": agent_detail.llm_profile or _default_foundry_model(),
            "system_prompt": agent_detail.system_prompt or "",
            "foundry_tools": sorted(agent_detail.foundry_tools or []),
            "temperature": agent_detail.temperature,
            "max_tokens": agent_detail.max_tokens,
            "description": agent_detail.description or "",
        }
        payload = json.dumps(canonical, sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()

    def check_connection(self) -> dict:
        """Check if Foundry credentials are available and valid."""
        if not self.endpoint:
            return {"status": "not_configured", "detail": "FOUNDRY_PROJECT_ENDPOINT is not set"}
        try:
            client = self._get_client()
            # Actually verify credentials by making a lightweight API call
            client.agents.list(limit=1)
            return {"status": "connected", "endpoint": "configured"}
        except FoundryNotConfiguredError as e:
            return {"status": "not_configured", "detail": str(e)}
        except Exception as e:
            logger.warning("foundry_connection_check_failed", error=str(e))
            return {"status": "error", "detail": "Foundry credentials are invalid or endpoint is unreachable"}

    def deploy_agent(self, agent_detail) -> dict:
        """Deploy a custom agent definition to Azure AI Foundry.

        Sends the agent definition including Foundry-native tools
        (code_interpreter, file_search, bing_grounding).

        Future: Druppie MCP tools could be bridged to Foundry via
        FunctionTool definitions backed by an API gateway.

        Args:
            agent_detail: CustomAgentDetail with the agent configuration.

        Returns:
            Dict with agent_id, name, version from Foundry.
        """
        client = self._get_client()
        from azure.ai.projects.models import PromptAgentDefinition

        model = agent_detail.llm_profile or _default_foundry_model()
        tools = self._build_foundry_tools(agent_detail.foundry_tools)

        definition = PromptAgentDefinition(
            model=model,
            instructions=agent_detail.system_prompt,
            tools=tools if tools else None,
        )

        logger.info(
            "foundry_deploying_agent",
            agent_id=agent_detail.agent_id,
            model=model,
        )

        result = client.agents.create_version(
            agent_name=agent_detail.agent_id,
            definition=definition,
        )

        logger.info(
            "foundry_agent_deployed",
            agent_id=agent_detail.agent_id,
            foundry_id=result.id,
            version=getattr(result, 'version', None),
        )

        return {
            "foundry_agent_id": result.id,
            "name": result.name,
            "version": getattr(result, 'version', None),
            "deployed_at": datetime.now(timezone.utc).isoformat(),
        }

    def delete_agent(self, agent_name: str) -> bool:
        """Delete a deployed agent from Foundry."""
        try:
            client = self._get_client()
            client.agents.delete(agent_name=agent_name)
            logger.info("foundry_agent_deleted", agent_name=agent_name)
            return True
        except Exception as e:
            logger.warning("foundry_delete_agent_failed", agent_name=agent_name, error=str(e))
            return False

    def get_agent_info(self, agent_name: str) -> dict | None:
        """Get info about a deployed agent from Foundry."""
        try:
            client = self._get_client()
            # The SDK may have a get method - wrap in try/except
            agent = client.agents.get(agent_name=agent_name)
            return {
                "foundry_agent_id": agent.id,
                "name": agent.name,
                "version": getattr(agent, 'version', None),
            }
        except Exception as e:
            logger.warning("foundry_get_agent_failed", agent_name=agent_name, error=str(e))
            return None

    def _build_foundry_tools(self, foundry_tools: list[str]) -> list:
        """Map foundry_tools strings to Azure SDK tool objects.

        Some tools (bing_grounding) require connection resources configured
        in the Foundry portal — the connection ID is auto-discovered.
        Zero-config tools (code_interpreter, file_search) work out of the box.
        """
        if not foundry_tools:
            return []

        from azure.ai.projects.models import (
            CodeInterpreterTool,
            FileSearchTool,
            BingGroundingTool,
            BingGroundingSearchToolParameters,
            BingGroundingSearchConfiguration,
        )

        # Zero-config tools — instantiate directly
        zero_config_map = {
            "code_interpreter": CodeInterpreterTool,
            "file_search": FileSearchTool,
        }

        tools = []
        for tool_type in foundry_tools:
            if tool_type in zero_config_map:
                tools.append(zero_config_map[tool_type]())
            elif tool_type == "bing_grounding":
                connection_id = self._find_bing_connection()
                if not connection_id:
                    raise ValueError(
                        "bing_grounding requires a Bing connection in Azure Foundry portal. "
                        "Go to Foundry portal → Project → Connected resources → add a Bing connection."
                    )
                tools.append(
                    BingGroundingTool(
                        bing_grounding=BingGroundingSearchToolParameters(
                            search_configurations=[
                                BingGroundingSearchConfiguration(
                                    project_connection_id=connection_id,
                                )
                            ]
                        )
                    )
                )
            elif tool_type in ("browser_automation", "deep_research", "bing_custom_search", "azure_ai_search", "microsoft_fabric"):
                logger.info("foundry_tool_not_yet_mapped", tool_type=tool_type)
            else:
                logger.warning("foundry_unknown_tool_type", tool_type=tool_type)
        return tools

    def _find_bing_connection(self) -> str | None:
        """Auto-discover the Bing Grounding connection from the Foundry project."""
        try:
            client = self._get_client()
            for conn in client.connections.list():
                name = (conn.name or "").lower()
                conn_type = str(getattr(conn, "type", "")).lower()
                if "bing" in name or "bing" in conn_type:
                    logger.info("foundry_bing_connection_found", connection_id=conn.id)
                    return conn.id
        except Exception as e:
            logger.warning("foundry_bing_connection_lookup_failed", error=str(e))
        return None

    def validate_for_foundry(self, agent_detail) -> dict:
        """Validate an agent definition is deployable to Foundry.

        Returns:
            Dict with 'valid' (bool), 'errors' (list), 'warnings' (list).
            Errors are blocking — deployment will fail.
            Warnings are informational — deployment may work but with caveats.
        """
        errors = []
        warnings = []

        # 1. Check agent_id is valid for Foundry (alphanumeric + hyphens, max 64 chars)
        if not agent_detail.agent_id:
            errors.append("agent_id is required")
        elif len(agent_detail.agent_id) > 64:
            errors.append(f"agent_id is too long ({len(agent_detail.agent_id)} chars, max 64)")

        # 2. Check system_prompt (instructions) is present and non-trivial
        prompt = (agent_detail.system_prompt or "").strip()
        if not prompt:
            errors.append("system_prompt (instructions) is required — Foundry agents need instructions to operate")
        elif len(prompt) < 20:
            warnings.append("system_prompt is very short — consider adding more detailed instructions")

        # 3. Check model is set
        model = agent_detail.llm_profile or _default_foundry_model()
        if not agent_detail.llm_profile:
            warnings.append(
                f"No model selected — will default to {_default_foundry_model()}"
            )

        # 4. Validate foundry_tools
        deployable_tools = {"code_interpreter", "file_search"}
        portal_tools = {"bing_grounding"}
        coming_soon_tools = {"browser_automation", "deep_research"}

        for tool in (agent_detail.foundry_tools or []):
            if tool in coming_soon_tools:
                errors.append(
                    f"Tool '{tool}' is not yet available in the Foundry SDK — "
                    f"remove it before deploying"
                )
            elif tool in portal_tools:
                if tool == "bing_grounding" and not self._find_bing_connection():
                    errors.append(
                        f"Tool '{tool}' requires a Bing connection in Azure Foundry portal — "
                        f"go to Foundry portal → Project → Connected resources → add a Bing connection"
                    )
                else:
                    warnings.append(
                        f"Tool '{tool}' uses a portal connection (auto-discovered from Foundry project)"
                    )
            elif tool not in deployable_tools:
                errors.append(f"Unknown Foundry tool: '{tool}'")

        # 5. Check name is present
        if not (agent_detail.name or "").strip():
            errors.append("name is required")

        # 6. Warn about Druppie-specific fields that won't transfer to Foundry
        if agent_detail.mcps and (
            (isinstance(agent_detail.mcps, list) and len(agent_detail.mcps) > 0) or
            (isinstance(agent_detail.mcps, dict) and len(agent_detail.mcps) > 0)
        ):
            warnings.append(
                "MCP tools are Druppie-specific and will NOT be available in the Foundry deployment — "
                "only Foundry-native tools are deployed"
            )
        if agent_detail.skills:
            warnings.append(
                "Skills are Druppie-specific and will NOT be available in the Foundry deployment"
            )
        if agent_detail.druppie_runtime_tools:
            warnings.append(
                "Druppie runtime tools are platform-specific and will NOT be available in the Foundry deployment"
            )

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "foundry_model": model,
            "deployable_tools": [t for t in (agent_detail.foundry_tools or []) if t in deployable_tools | portal_tools],
        }

    def list_tools(self) -> list[dict]:
        """List available tools for Azure AI Foundry agents.

        Combines built-in tools (always available) with connection-based
        tools discovered from client.connections.list().
        """
        # Built-in tools that are always available
        tools = [
            {"id": "code_interpreter", "label": "Code Interpreter", "description": "Run Python code in a sandbox"},
            {"id": "file_search", "label": "File Search", "description": "Search through uploaded files using embeddings"},
        ]

        # Map connection types to tool IDs
        connection_tool_map = {
            "bing": {"id": "bing_grounding", "label": "Bing Grounding", "description": "Ground responses with web search results"},
            "azure_ai_search": {"id": "azure_ai_search", "label": "Azure AI Search", "description": "Search your own data using Azure AI Search"},
        }

        try:
            client = self._get_client()
            seen_tools = set()
            for conn in client.connections.list():
                conn_name = (getattr(conn, "name", "") or "").lower()
                conn_type = str(getattr(conn, "type", "")).lower()
                for key, tool_def in connection_tool_map.items():
                    if key in conn_name or key in conn_type:
                        if tool_def["id"] not in seen_tools:
                            tools.append(tool_def)
                            seen_tools.add(tool_def["id"])
            logger.info("foundry_tools_listed", count=len(tools))
        except FoundryNotConfiguredError:
            pass
        except Exception as e:
            logger.warning("foundry_list_tools_failed", error=str(e))

        return tools

    def list_models(self) -> list[dict]:
        """List available model deployments from Azure AI Foundry.

        Uses client.deployments.list() to enumerate all model deployments
        in the project, authenticated via the service principal.
        """
        try:
            client = self._get_client()
            result = []
            for deployment in client.deployments.list():
                name = deployment.get("name") or deployment.get("id")
                if not name:
                    continue
                model_name = ""
                model_info = deployment.get("model") or {}
                if isinstance(model_info, dict):
                    model_name = model_info.get("name", "")
                label = f"{name} ({model_name})" if model_name else name
                result.append({
                    "id": name,
                    "label": label,
                    "model": model_name,
                })
            logger.info("foundry_models_listed", count=len(result))
            return result
        except FoundryNotConfiguredError:
            return []
        except Exception as e:
            logger.warning("foundry_list_models_failed", error=str(e))
            return []

    def is_configured(self) -> bool:
        """Check if Foundry is configured."""
        return bool(self.endpoint)


class FoundryNotConfiguredError(Exception):
    """Raised when Foundry credentials are not configured."""
    pass
