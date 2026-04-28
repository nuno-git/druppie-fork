"""Custom agent service for business logic."""

import os
import re
import time
from uuid import UUID

import structlog
import yaml
from sqlalchemy.exc import IntegrityError

from ..agents.builtin_tools import BUILTIN_TOOL_DEFS
from ..agents.definition_loader import AgentDefinitionLoader
from ..api.errors import AuthorizationError, ConflictError, NotFoundError, ValidationError
from ..core.mcp_config import get_mcp_config
from ..db.models.custom_agent import CustomAgent
from ..domain.custom_agent import (
    CustomAgentCreate,
    CustomAgentDetail,
    CustomAgentSummary,
    CustomAgentUpdate,
)
from ..repositories.custom_agent_repository import CustomAgentRepository

logger = structlog.get_logger()

_foundry_metadata_cache: dict = {"data": None, "expires": 0.0}
_FOUNDRY_CACHE_TTL = 300  # 5 minutes


def _get_cached_foundry_metadata(endpoint: str | None) -> dict:
    """Return Foundry models + tools, cached for 5 minutes."""
    now = time.time()
    if _foundry_metadata_cache["data"] is not None and now < _foundry_metadata_cache["expires"]:
        return _foundry_metadata_cache["data"]

    from druppie.services.foundry_service import FoundryService

    foundry = FoundryService(endpoint=endpoint)
    result = {
        "foundry_models": foundry.list_models(),
        "foundry_tools": foundry.list_tools(),
    }
    _foundry_metadata_cache["data"] = result
    _foundry_metadata_cache["expires"] = now + _FOUNDRY_CACHE_TTL
    return result


class CustomAgentService:
    """Business logic for custom agents."""

    def __init__(self, repo: CustomAgentRepository):
        self.repo = repo

    def list_custom_agents(self) -> list[CustomAgentSummary]:
        """List all custom agents as summaries."""
        agents = self.repo.list_all()
        return [self._to_summary(a) for a in agents]

    def list_custom_agents_for_user(
        self, user_id: UUID, user_roles: list[str],
    ) -> list[CustomAgentSummary]:
        """List custom agents visible to a user.

        Admin/developer roles see all agents. Others see only their own.
        """
        if "admin" in user_roles or "developer" in user_roles:
            agents = self.repo.list_all()
        else:
            agents = self.repo.list_by_owner(user_id)
        return [self._to_summary(a) for a in agents]

    def get_custom_agent(self, agent_id: str) -> CustomAgentDetail:
        """Get a single custom agent by agent_id."""
        agent = self.repo.get_by_agent_id(agent_id)
        if not agent:
            raise NotFoundError("agent", agent_id)
        return self._to_detail(agent)

    def create_custom_agent(
        self,
        data: CustomAgentCreate,
        owner_id: UUID,
    ) -> CustomAgentDetail:
        """Create a new custom agent.

        Validates:
        - agent_id is kebab-case
        - agent_id does not shadow a built-in agent
        - category is not "system"
        - agent_id is not already taken
        """
        # Validate kebab-case (also validated by pydantic, but double-check)
        if not re.match(r"^[a-z][a-z0-9-]*$", data.agent_id):
            raise ValidationError(
                "agent_id must be kebab-case: lowercase letters, digits, and hyphens",
                field="agent_id",
            )

        # Validate not shadowing built-in YAML agents
        builtin_ids = AgentDefinitionLoader.list_yaml_agents()
        if data.agent_id in builtin_ids:
            raise ConflictError(
                f"agent_id '{data.agent_id}' conflicts with a built-in agent definition"
            )

        # Validate category
        if data.category == "system":
            raise ValidationError(
                "Category 'system' is reserved for built-in agents",
                field="category",
            )

        # Validate uniqueness
        if self.repo.agent_id_exists(data.agent_id):
            raise ConflictError(
                f"Custom agent with agent_id '{data.agent_id}' already exists"
            )

        # Build mcps for repo (normalize to dict or list)
        mcps = data.mcps

        # Never allow empty model
        llm_profile = data.llm_profile
        if not llm_profile or not llm_profile.strip():
            llm_profile = self._default_model()

        agent = self.repo.create(
            agent_id=data.agent_id,
            name=data.name,
            description=data.description,
            category=data.category,
            system_prompt=data.system_prompt,
            llm_profile=llm_profile,
            temperature=data.temperature,
            max_tokens=data.max_tokens,
            max_iterations=data.max_iterations,
            owner_id=owner_id,
            mcps=mcps if mcps else None,
            skills=data.skills or None,
            system_prompts_list=data.system_prompts or None,
            builtin_tools=data.druppie_runtime_tools or None,
            approval_overrides=data.approval_overrides or None,
            foundry_tools=data.foundry_tools or None,
        )
        try:
            self.repo.commit()
        except IntegrityError:
            self.repo.rollback()
            raise ConflictError(
                f"Custom agent with agent_id '{data.agent_id}' already exists"
            )

        logger.info(
            "custom_agent_created",
            agent_id=data.agent_id,
            owner_id=str(owner_id),
        )
        return self._to_detail(agent)

    def update_custom_agent(
        self,
        agent_id: str,
        data: CustomAgentUpdate,
        user_id: UUID,
        user_roles: list[str] | None = None,
    ) -> CustomAgentDetail:
        """Update an existing custom agent. Owner or admin can update."""
        agent = self.repo.get_by_agent_id(agent_id)
        if not agent:
            raise NotFoundError("agent", agent_id)

        if agent.owner_id != user_id and "admin" not in (user_roles or []):
            raise AuthorizationError("Only the owner or an admin can update this custom agent")

        # Validate category if being changed
        if data.category == "system":
            raise ValidationError(
                "Category 'system' is reserved for built-in agents",
                field="category",
            )

        # Build kwargs for repo update, only include non-None fields
        kwargs = {}
        if data.name is not None:
            kwargs["name"] = data.name
        if data.description is not None:
            kwargs["description"] = data.description
        if data.category is not None:
            kwargs["category"] = data.category
        if data.system_prompt is not None:
            kwargs["system_prompt"] = data.system_prompt
        if data.llm_profile is not None:
            if not data.llm_profile.strip():
                # Never allow empty model — default to first available deployment
                data.llm_profile = self._default_model()
            kwargs["llm_profile"] = data.llm_profile
        if data.temperature is not None:
            kwargs["temperature"] = data.temperature
        if data.max_tokens is not None:
            kwargs["max_tokens"] = data.max_tokens
        if data.max_iterations is not None:
            kwargs["max_iterations"] = data.max_iterations
        if data.is_active is not None:
            kwargs["is_active"] = data.is_active

        # Child-row fields
        if data.mcps is not None:
            kwargs["mcps"] = data.mcps
        if data.skills is not None:
            kwargs["skills"] = data.skills
        if data.system_prompts is not None:
            kwargs["system_prompts_list"] = data.system_prompts
        if data.druppie_runtime_tools is not None:
            kwargs["builtin_tools"] = data.druppie_runtime_tools
        if data.approval_overrides is not None:
            kwargs["approval_overrides"] = data.approval_overrides
        if data.foundry_tools is not None:
            kwargs["foundry_tools"] = data.foundry_tools

        agent = self.repo.update(agent_id, **kwargs)
        self.repo.commit()

        logger.info("custom_agent_updated", agent_id=agent_id, by_user=str(user_id))
        return self._to_detail(agent)

    def delete_custom_agent(
        self, agent_id: str, user_id: UUID, user_roles: list[str] | None = None,
    ) -> None:
        """Delete a custom agent. Owner or admin can delete."""
        agent = self.repo.get_by_agent_id(agent_id)
        if not agent:
            raise NotFoundError("agent", agent_id)

        if agent.owner_id != user_id and "admin" not in (user_roles or []):
            raise AuthorizationError("Only the owner or an admin can delete this custom agent")

        self.repo.delete(agent_id)
        self.repo.commit()

        logger.info("custom_agent_deleted", agent_id=agent_id, by_user=str(user_id))

    def validate_for_foundry(self, agent_id: str) -> dict:
        """Validate a custom agent definition is deployable to Azure AI Foundry.

        Returns dict with 'valid', 'errors', 'warnings', 'foundry_model', 'deployable_tools'.
        """
        from ..services.foundry_service import FoundryService

        agent = self.repo.get_by_agent_id(agent_id)
        if not agent:
            raise NotFoundError("agent", agent_id)

        detail = self._to_detail(agent)
        foundry = FoundryService()  # Only need validation logic, no client needed
        return foundry.validate_for_foundry(detail)

    def deploy_custom_agent(
        self, agent_id: str, user_id: UUID, user_roles: list[str] | None = None,
    ) -> dict:
        """Deploy a custom agent to Azure AI Foundry. Owner or admin can deploy."""
        from datetime import datetime, timezone

        from ..core.config import get_settings
        from ..services.foundry_service import FoundryNotConfiguredError, FoundryService

        agent = self.repo.get_by_agent_id(agent_id)
        if not agent:
            raise NotFoundError("agent", agent_id)
        if agent.owner_id != user_id and "admin" not in (user_roles or []):
            raise AuthorizationError("Only the owner or an admin can deploy this custom agent")

        settings = get_settings()
        foundry = FoundryService(endpoint=settings.llm.foundry_project_endpoint)
        if not foundry.is_configured():
            raise ValidationError(
                "Azure AI Foundry is not configured. Set FOUNDRY_PROJECT_ENDPOINT in .env.",
                field="foundry",
            )

        detail = self._to_detail(agent)

        # Pre-deploy validation — block if there are errors
        validation = foundry.validate_for_foundry(detail)
        if not validation["valid"]:
            raise ValidationError(
                "Agent definition is not valid for Foundry deployment: " +
                "; ".join(validation["errors"]),
                field="foundry",
            )

        # Compute spec hash before deployment so a hash failure can't leave
        # the agent deployed in Azure but with missing hash in the DB.
        spec_hash = foundry.compute_spec_hash(detail)

        try:
            result = foundry.deploy_agent(detail)
            self.repo.update_deployment_status(
                agent_id,
                deployment_status="deployed",
                deployed_at=datetime.now(timezone.utc),
                deployed_version=result.get("version"),
                deployed_spec_hash=spec_hash,
                foundry_agent_id=result.get("foundry_agent_id"),
            )
            self.repo.commit()
            if validation["warnings"]:
                result["warnings"] = validation["warnings"]
            return result
        except FoundryNotConfiguredError as e:
            raise ValidationError(str(e), field="foundry")
        except Exception as e:
            self.repo.update_deployment_status(agent_id, deployment_status="failed")
            self.repo.commit()
            logger.error("deploy_custom_agent_failed", agent_id=agent_id, exc_info=True)
            # Surface a clear message instead of letting the raw SDK exception bubble
            msg = str(e)
            if "PermissionDenied" in msg:
                raise AuthorizationError(
                    "Service principal lacks permissions to deploy agents. "
                    "Assign the 'Azure AI Developer' role on the AI Services resource."
                )
            raise ValidationError(f"Deployment failed: {msg}", field="foundry")

    def undeploy_custom_agent(
        self, agent_id: str, user_id: UUID, user_roles: list[str] | None = None,
    ) -> dict:
        """Remove a custom agent from Azure AI Foundry. Owner or admin can undeploy."""
        from ..core.config import get_settings
        from ..services.foundry_service import FoundryService

        agent = self.repo.get_by_agent_id(agent_id)
        if not agent:
            raise NotFoundError("agent", agent_id)
        if agent.owner_id != user_id and "admin" not in (user_roles or []):
            raise AuthorizationError("Only the owner or an admin can undeploy this custom agent")

        settings = get_settings()
        foundry = FoundryService(endpoint=settings.llm.foundry_project_endpoint)

        if foundry.is_configured():
            foundry_name = agent.foundry_agent_id or agent_id
            success = foundry.delete_agent(foundry_name)
            if not success:
                raise ValidationError(
                    "Failed to remove agent from Azure AI Foundry",
                    field="foundry",
                )

        self.repo.update_deployment_status(
            agent_id,
            deployment_status=None,
            deployed_at=None,
            deployed_version=None,
            deployed_spec_hash=None,
            foundry_agent_id=None,
        )
        self.repo.commit()

        logger.info("custom_agent_undeployed", agent_id=agent_id, by_user=str(user_id))
        return {"status": "undeployed", "agent_id": agent_id}

    def validate_agent(self, agent_id: str) -> list[str]:
        """Validate a custom agent by agent_id. Returns warnings."""
        agent = self.repo.get_by_agent_id(agent_id)
        if not agent:
            raise NotFoundError("agent", agent_id)
        detail = self._to_detail(agent)
        data = CustomAgentCreate(
            agent_id=detail.agent_id,
            name=detail.name,
            description=detail.description,
            category=detail.category,
            system_prompt=detail.system_prompt,
            system_prompts=detail.system_prompts,
            druppie_runtime_tools=detail.druppie_runtime_tools,
            mcps=detail.mcps,
            approval_overrides=detail.approval_overrides,
            skills=detail.skills,
            llm_profile=detail.llm_profile,
            temperature=detail.temperature,
            max_tokens=detail.max_tokens,
            max_iterations=detail.max_iterations,
        )
        return self.validate_definition(data)

    def validate_definition(self, data: CustomAgentCreate) -> list[str]:
        """Validate a custom agent definition and return warnings.

        Returns a list of warning strings for non-fatal issues like
        unknown MCP names, unknown skills, etc.
        """
        warnings = []
        mcp_config = get_mcp_config()
        known_mcps = set(mcp_config.get_servers())

        # Check MCP names
        if isinstance(data.mcps, dict):
            mcp_names = list(data.mcps.keys())
        else:
            mcp_names = data.mcps

        for mcp_name in mcp_names:
            if mcp_name not in known_mcps:
                warnings.append(f"Unknown MCP server: '{mcp_name}'")

        # Check skills
        skills_dir = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "skills"
        )
        known_skills: set[str] = set()
        if os.path.isdir(skills_dir):
            known_skills = {
                d for d in os.listdir(skills_dir)
                if os.path.isdir(os.path.join(skills_dir, d)) and not d.startswith("_")
            }

        for skill in data.skills:
            if skill not in known_skills:
                warnings.append(f"Unknown skill: '{skill}'")

        # Check builtin tools
        for tool in data.druppie_runtime_tools:
            if tool not in BUILTIN_TOOL_DEFS:
                warnings.append(f"Unknown builtin tool: '{tool}'")

        # Check system prompts
        prompts_dir = os.path.join(
            AgentDefinitionLoader._get_definitions_path(), "system_prompts"
        )
        known_prompts: set[str] = set()
        if os.path.isdir(prompts_dir):
            known_prompts = {
                f.replace(".yaml", "").replace(".yml", "")
                for f in os.listdir(prompts_dir)
                if f.endswith((".yaml", ".yml"))
            }

        for prompt in data.system_prompts:
            if prompt not in known_prompts:
                warnings.append(f"Unknown system prompt: '{prompt}'")

        return warnings

    def export_as_yaml(self, agent_id: str) -> str:
        """Export a custom agent definition in the Azure Foundry agent format.

        Produces YAML that mirrors the structure returned by the Foundry API
        (agent.version), so it can be round-tripped via the YAML editor.
        """
        agent = self.repo.get_by_agent_id(agent_id)
        if not agent:
            raise NotFoundError("agent", agent_id)

        detail = self._to_detail(agent)

        version = detail.deployed_version or "1"
        updated_ts = str(int(detail.updated_at.timestamp())) if detail.updated_at else ""

        # Build tools list in Foundry format
        tools = []
        for tool_id in (detail.foundry_tools or []):
            tools.append({"type": tool_id})

        data: dict = {
            "metadata": {
                "description": detail.description or "",
                "modified_at": updated_ts,
            },
            "object": "agent.version",
            "id": f"{detail.agent_id}:{version}",
            "name": detail.agent_id,
            "version": version,
            "description": detail.description or "",
            "definition": {
                "kind": "prompt",
                "model": detail.llm_profile or "",
                "instructions": detail.system_prompt or "",
                "tools": tools if tools else [],
            },
            "status": "active" if detail.is_active else "inactive",
        }

        if detail.max_tokens:
            data["definition"]["max_tokens"] = detail.max_tokens
        if detail.max_iterations:
            data["definition"]["max_iterations"] = detail.max_iterations
        if detail.temperature is not None and abs(detail.temperature - 0.1) > 1e-9:
            data["definition"]["temperature"] = detail.temperature

        return yaml.dump(data, default_flow_style=False, sort_keys=False)

    def get_metadata(self) -> dict:
        """Return metadata for form dropdowns.

        Returns available MCPs, skills, system_prompts, builtin_tools,
        llm_profiles, and categories.
        """
        # MCPs from mcp_config.yaml
        mcp_config = get_mcp_config()
        mcps = mcp_config.get_servers()

        # Skills from druppie/skills/ directory
        skills_dir = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "skills"
        )
        skills: list[str] = []
        if os.path.isdir(skills_dir):
            skills = sorted(
                d for d in os.listdir(skills_dir)
                if os.path.isdir(os.path.join(skills_dir, d)) and not d.startswith("_")
            )

        # System prompts from definitions/system_prompts/
        prompts_dir = os.path.join(
            AgentDefinitionLoader._get_definitions_path(), "system_prompts"
        )
        system_prompts: list[str] = []
        if os.path.isdir(prompts_dir):
            system_prompts = sorted(
                f.replace(".yaml", "").replace(".yml", "")
                for f in os.listdir(prompts_dir)
                if f.endswith((".yaml", ".yml"))
            )

        # Builtin tools from BUILTIN_TOOL_DEFS
        builtin_tools = sorted(BUILTIN_TOOL_DEFS.keys())

        # LLM models from Azure Foundry (cached, 5-min TTL)
        from druppie.core.config import get_settings

        settings = get_settings()
        foundry_meta = _get_cached_foundry_metadata(settings.llm.foundry_project_endpoint)
        foundry_models = foundry_meta["foundry_models"]
        foundry_tools = foundry_meta["foundry_tools"]

        # Categories (hardcoded, minus "system" which is reserved)
        categories = ["execution", "planning", "review", "analysis"]

        return {
            "mcps": mcps,
            "skills": skills,
            "system_prompts": system_prompts,
            "druppie_runtime_tools": builtin_tools,
            "foundry_models": foundry_models,
            "foundry_tools": foundry_tools,
            "categories": categories,
        }

    # ── Helpers ──────────────────────────────────────────────

    def _default_model(self) -> str:
        """Return the first available Foundry model, or env default."""
        from druppie.services.foundry_service import FoundryService
        from druppie.core.config import get_settings

        settings = get_settings()
        foundry = FoundryService(endpoint=settings.llm.foundry_project_endpoint)
        models = foundry.list_models()
        if models:
            return models[0]["id"]
        return os.environ.get("FOUNDRY_MODEL", "gpt-4.1-mini")

    @staticmethod
    def _is_dirty(agent: CustomAgent) -> bool:
        """Check if a deployed agent has been edited since last deployment."""
        return (
            agent.deployment_status == "deployed"
            and agent.deployed_at is not None
            and agent.updated_at is not None
            and agent.updated_at > agent.deployed_at
        )

    @staticmethod
    def _to_summary(agent: CustomAgent) -> CustomAgentSummary:
        """Convert a CustomAgent ORM model to a domain summary."""
        return CustomAgentSummary(
            id=agent.id,
            agent_id=agent.agent_id,
            name=agent.name,
            description=agent.description or "",
            category=agent.category or "execution",
            kind=agent.kind or "prompt",
            llm_profile=agent.llm_profile or "standard",
            is_active=agent.is_active if agent.is_active is not None else True,
            deployment_status=agent.deployment_status,
            is_dirty=CustomAgentService._is_dirty(agent),
            created_at=agent.created_at,
        )

    @staticmethod
    def _to_detail(agent: CustomAgent) -> CustomAgentDetail:
        """Convert a CustomAgent ORM model to a full domain detail."""
        # Build mcps
        has_tool_whitelist = any(mcp.tools for mcp in agent.mcps)
        if has_tool_whitelist:
            mcps: list[str] | dict[str, list[str]] = {}
            for mcp in agent.mcps:
                if mcp.tools:
                    mcps[mcp.mcp_name] = [t.tool_name for t in mcp.tools]
                else:
                    mcps[mcp.mcp_name] = []
        else:
            mcps = [mcp.mcp_name for mcp in agent.mcps]

        # Build approval_overrides
        approval_overrides: dict[str, dict] = {}
        for ao in agent.approval_overrides:
            approval_overrides[ao.tool_key] = {
                "requires_approval": ao.requires_approval,
                "required_role": ao.required_role,
            }

        return CustomAgentDetail(
            id=agent.id,
            agent_id=agent.agent_id,
            name=agent.name,
            description=agent.description or "",
            category=agent.category or "execution",
            kind=agent.kind or "prompt",
            llm_profile=agent.llm_profile or "standard",
            is_active=agent.is_active if agent.is_active is not None else True,
            deployment_status=agent.deployment_status,
            is_dirty=CustomAgentService._is_dirty(agent),
            created_at=agent.created_at,
            system_prompt=agent.system_prompt or "",
            workflow_yaml=agent.workflow_yaml,
            system_prompts=[sp.prompt_id for sp in agent.system_prompts],
            druppie_runtime_tools=[bt.tool_name for bt in agent.builtin_tools],
            mcps=mcps,
            approval_overrides=approval_overrides,
            skills=[s.skill_name for s in agent.skills],
            foundry_tools=[ft.tool_type for ft in agent.foundry_tools],
            temperature=agent.temperature or 0.1,
            max_tokens=agent.max_tokens or 4096,
            max_iterations=agent.max_iterations or 10,
            owner_id=agent.owner_id,
            deployed_at=agent.deployed_at,
            deployed_version=agent.deployed_version,
            deployed_spec_hash=agent.deployed_spec_hash,
            foundry_agent_id=agent.foundry_agent_id,
            updated_at=agent.updated_at,
        )
