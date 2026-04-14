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

    def __init__(self, endpoint: str | None = None, api_key: str | None = None, azure_token: str | None = None):
        self.endpoint = endpoint
        self.api_key = api_key
        self.azure_token = azure_token
        self._client = None

    def _get_client(self):
        """Lazy-initialize the Foundry client.

        Credential priority:
        1. Azure token from DB (user logged in via device code flow)
        2. API key (set in .env as FOUNDRY_API_KEY)
        3. DefaultAzureCredential (fallback - uses az login, managed identity, etc.)
        """
        if self._client is not None:
            return self._client
        if not self.endpoint:
            raise FoundryNotConfiguredError("FOUNDRY_PROJECT_ENDPOINT is not set")
        try:
            from azure.ai.projects import AIProjectClient

            if self.azure_token:
                from azure.core.credentials import AccessToken

                class _StaticTokenCredential:
                    """Credential that returns a pre-fetched token."""
                    def __init__(self, token: str):
                        self._token = token

                    def get_token(self, *scopes, **kwargs) -> AccessToken:
                        import time
                        # Token validity is managed externally; set a far-future expiry
                        return AccessToken(self._token, int(time.time()) + 3600)

                self._client = AIProjectClient(
                    endpoint=self.endpoint,
                    credential=_StaticTokenCredential(self.azure_token),
                )
            elif self.api_key:
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

    def deploy_agent(self, agent_detail) -> dict:
        """Deploy a custom agent definition to Azure AI Foundry.

        The DB stores a full agent definition (MCPs, skills, builtin tools,
        approval overrides) which governs behavior inside Druppie's own
        orchestration. When deploying to Foundry, only the Foundry-compatible
        subset is sent: model, instructions (system_prompt), and temperature.

        Future: MCP tool schemas could be mapped to Foundry FunctionTool
        definitions, allowing Foundry-deployed agents to access external
        tools natively. This requires fetching tool JSON schemas from the
        registry and converting them to Foundry's function format.

        Args:
            agent_detail: CustomAgentDetail with the agent configuration.

        Returns:
            Dict with agent_id, name, version from Foundry.
        """
        client = self._get_client()
        from azure.ai.projects.models import PromptAgentDefinition

        model = PROFILE_MODEL_MAP.get(agent_detail.llm_profile, "gpt-4.1-mini")

        # Currently sends: model, instructions, temperature.
        # Fields stored but not yet sent to Foundry:
        #   - mcps/skills/builtin_tools: Druppie-runtime concepts
        #   - approval_overrides: Druppie's internal approval workflow
        #   - max_tokens/max_iterations: Druppie agent loop settings
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
