"""Azure AI Foundry deployment service."""

import structlog
from datetime import datetime, timezone

logger = structlog.get_logger()

# LLM profile -> Foundry model mapping
PROFILE_MODEL_MAP = {
    "standard": "gpt-4.1-mini",
    "cheap": "gpt-4.1-mini",
    "ollama": "gpt-4.1-mini",
}


class FoundryService:
    """Deploys agent definitions to Azure AI Foundry."""

    def __init__(self, endpoint: str | None = None, api_key: str | None = None):
        self.endpoint = endpoint
        self.api_key = api_key
        self._client = None

    def _get_client(self):
        """Lazy-initialize the Foundry client.

        Credential priority:
        1. API key (set in .env as FOUNDRY_API_KEY)
        2. DefaultAzureCredential (az login, managed identity, env vars, etc.)
        """
        if self._client is not None:
            return self._client
        if not self.endpoint:
            raise FoundryNotConfiguredError("FOUNDRY_PROJECT_ENDPOINT is not set")
        try:
            from azure.ai.projects import AIProjectClient

            if self.api_key:
                from azure.core.credentials import AzureKeyCredential
                self._client = AIProjectClient(
                    endpoint=self.endpoint,
                    credential=AzureKeyCredential(self.api_key),
                )
            else:
                from azure.identity import DefaultAzureCredential
                self._client = AIProjectClient(
                    endpoint=self.endpoint,
                    credential=DefaultAzureCredential(),
                )
            return self._client
        except ImportError:
            raise FoundryNotConfiguredError(
                "azure-ai-projects package not installed. Run: pip install azure-ai-projects azure-identity"
            )

    def check_connection(self) -> dict:
        """Check if Foundry credentials are available and valid."""
        if not self.endpoint:
            return {"status": "not_configured", "detail": "FOUNDRY_PROJECT_ENDPOINT is not set"}
        try:
            self._get_client()
            return {"status": "configured", "endpoint": self.endpoint}
        except FoundryNotConfiguredError as e:
            return {"status": "not_configured", "detail": str(e)}
        except Exception as e:
            return {"status": "error", "detail": str(e)}

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

        model = PROFILE_MODEL_MAP.get(agent_detail.llm_profile, "gpt-4.1-mini")
        tools = self._build_foundry_tools(agent_detail.foundry_tools)

        definition = PromptAgentDefinition(
            model=model,
            instructions=agent_detail.system_prompt,
            temperature=agent_detail.temperature,
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

    @staticmethod
    def _build_foundry_tools(foundry_tools: list[str]) -> list:
        """Map foundry_tools strings to Azure SDK tool objects.

        Some tools (bing_grounding, azure_ai_search, microsoft_fabric)
        require connection resources configured in the Foundry portal.
        They are included here for completeness but will fail at runtime
        if the connection is not set up. Zero-config tools
        (code_interpreter, file_search, browser_automation, deep_research)
        work out of the box.
        """
        if not foundry_tools:
            return []

        from azure.ai.projects.models import (
            CodeInterpreterTool,
            FileSearchTool,
            BingGroundingTool,
        )

        # Zero-config tools — instantiate directly
        zero_config_map = {
            "code_interpreter": CodeInterpreterTool,
            "file_search": FileSearchTool,
            # browser_automation and deep_research may need newer SDK
            # versions — they are stored in DB but skipped if SDK doesn't
            # support them yet.
        }

        # Tools requiring connection — instantiate without connection_id;
        # Foundry portal config provides the connection at runtime.
        connection_map = {
            "bing_grounding": BingGroundingTool,
        }

        tools = []
        for tool_type in foundry_tools:
            tool_cls = zero_config_map.get(tool_type) or connection_map.get(tool_type)
            if tool_cls:
                tools.append(tool_cls())
            elif tool_type in ("browser_automation", "deep_research", "bing_custom_search", "azure_ai_search", "microsoft_fabric"):
                # Known tool types not yet mapped in SDK — stored in DB
                # for future use, logged but not sent.
                logger.info("foundry_tool_not_yet_mapped", tool_type=tool_type)
            else:
                logger.warning("foundry_unknown_tool_type", tool_type=tool_type)
        return tools

    def is_configured(self) -> bool:
        """Check if Foundry is configured."""
        return bool(self.endpoint)


class FoundryNotConfiguredError(Exception):
    """Raised when Foundry credentials are not configured."""
    pass
