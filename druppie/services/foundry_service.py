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

    def __init__(self, endpoint: str | None = None):
        self.endpoint = endpoint
        self._client = None

    def _get_client(self):
        """Lazy-initialize the Foundry client."""
        if self._client is not None:
            return self._client
        if not self.endpoint:
            raise FoundryNotConfiguredError("FOUNDRY_PROJECT_ENDPOINT is not set")
        try:
            from azure.ai.projects import AIProjectClient
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

    def deploy_agent(self, agent_detail) -> dict:
        """Deploy a custom agent definition to Azure AI Foundry.

        Args:
            agent_detail: CustomAgentDetail with the agent configuration.

        Returns:
            Dict with agent_id, name, version from Foundry.
        """
        client = self._get_client()
        from azure.ai.projects.models import PromptAgentDefinition

        model = PROFILE_MODEL_MAP.get(agent_detail.llm_profile, "gpt-4.1-mini")

        definition = PromptAgentDefinition(
            model=model,
            instructions=agent_detail.system_prompt,
            temperature=agent_detail.temperature,
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

    def is_configured(self) -> bool:
        """Check if Foundry is configured."""
        return bool(self.endpoint)


class FoundryNotConfiguredError(Exception):
    """Raised when Foundry credentials are not configured."""
    pass
