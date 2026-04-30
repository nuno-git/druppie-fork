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

    @classmethod
    def from_execution_repo(cls, execution_repo) -> "CustomAgentService":
        """Create a service instance using the execution repo's DB session."""
        return cls(CustomAgentRepository(execution_repo.db))

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
        if data.foundry_tool_configs is not None:
            kwargs["foundry_tool_configs"] = data.foundry_tool_configs

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
            success = foundry.delete_agent(agent_id)
            if not success:
                logger.warning(
                    "foundry_delete_failed_clearing_local",
                    agent_id=agent_id,
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

    # ── Builtin-tool adapters ───────────────────────────────────
    # These methods are called from builtin_tools.py during agent execution.
    # They resolve ownership from session_id, delegate to the existing service
    # methods, and return tool-result dicts.

    def _resolve_owner(self, session_id: UUID) -> UUID | None:
        """Resolve the owner user_id from a session_id."""
        from ..db.models.session import Session
        session = self.repo.db.query(Session).filter_by(id=session_id).first()
        return session.user_id if session else None

    def create_foundry_agent_from_tool(
        self,
        agent_id: str,
        name: str,
        description: str,
        instructions: str,
        model: str,
        session_id: UUID,
        foundry_tools: list | None = None,
        tool_resources: dict | None = None,
        max_tokens: int = 4096,
        max_iterations: int = 10,
    ) -> dict:
        """Create a Foundry agent from a builtin tool call."""
        from .foundry_service import FoundryService, ALLOWED_TOOL_TYPES

        spec_errors = FoundryService.validate_agent_spec(
            name=name,
            description=description,
            instructions=instructions,
            foundry_tools=foundry_tools,
            tool_resources=tool_resources,
        )
        if spec_errors:
            return {
                "success": False,
                "error": "Foundry spec validation failed:\n" + "\n".join(f"- {e}" for e in spec_errors),
            }

        validated_tools = [t for t in (foundry_tools or []) if t in ALLOWED_TOOL_TYPES]

        foundry_tool_configs = {}
        if tool_resources:
            for tool_type, res in tool_resources.items():
                if isinstance(res, dict) and res:
                    foundry_tool_configs[tool_type] = res

        try:
            owner_id = self._resolve_owner(session_id)
            data = CustomAgentCreate(
                agent_id=agent_id,
                name=name,
                description=description,
                category="execution",
                system_prompt=instructions,
                llm_profile=FoundryService.resolve_model(model),
                temperature=0.1,
                max_tokens=max_tokens,
                max_iterations=max_iterations,
                foundry_tools=validated_tools,
                foundry_tool_configs=foundry_tool_configs if foundry_tool_configs else None,
            )
            self.create_custom_agent(data, owner_id)
            return {
                "success": True,
                "agent_id": agent_id,
                "name": name,
                "description": description,
                "foundry_tools": validated_tools,
                "message": f"Agent '{name}' created successfully. It can be deployed to Azure AI Foundry from the Agents page.",
            }
        except (ConflictError, ValidationError) as e:
            return {"success": False, "error": str(e)}
        except Exception as e:
            logger.error("foundry_agent_creation_failed", error=str(e), agent_id=agent_id)
            return {"success": False, "error": "Agent creation failed"}

    def update_foundry_agent_from_tool(
        self,
        agent_id: str,
        session_id: UUID,
        name: str | None = None,
        description: str | None = None,
        instructions: str | None = None,
        model: str | None = None,
        foundry_tools: list | None = None,
        tool_resources: dict | None = None,
        max_tokens: int | None = None,
        max_iterations: int | None = None,
    ) -> dict:
        """Update a Foundry agent from a builtin tool call."""
        from .foundry_service import FoundryService, ALLOWED_TOOL_TYPES

        try:
            agent = self.repo.get_by_agent_id(agent_id)
            if not agent:
                return {"success": False, "error": f"Agent '{agent_id}' not found"}

            owner_id = self._resolve_owner(session_id)
            merged_name = name if name is not None else agent.name
            merged_desc = description if description is not None else (agent.description or "")
            merged_instr = instructions if instructions is not None else (agent.system_prompt or "")
            merged_tools = foundry_tools if foundry_tools is not None else [ft.tool_type for ft in agent.foundry_tools]
            spec_errors = FoundryService.validate_agent_spec(
                name=merged_name,
                description=merged_desc,
                instructions=merged_instr,
                foundry_tools=merged_tools,
                tool_resources=tool_resources,
            )
            if spec_errors:
                return {
                    "success": False,
                    "error": "Foundry spec validation failed:\n" + "\n".join(f"- {e}" for e in spec_errors),
                }

            update_data = CustomAgentUpdate()
            if name is not None:
                update_data.name = name
            if description is not None:
                update_data.description = description
            if instructions is not None:
                update_data.system_prompt = instructions
            if model is not None:
                update_data.llm_profile = FoundryService.resolve_model(model)
            if max_tokens is not None:
                update_data.max_tokens = max_tokens
            if max_iterations is not None:
                update_data.max_iterations = max_iterations
            if foundry_tools is not None:
                update_data.foundry_tools = [t for t in foundry_tools if t in ALLOWED_TOOL_TYPES]
            if tool_resources is not None:
                ftc = {}
                for tool_type, res in tool_resources.items():
                    if isinstance(res, dict) and res:
                        ftc[tool_type] = res
                if ftc:
                    update_data.foundry_tool_configs = ftc

            self.update_custom_agent(agent_id, update_data, owner_id)
            updated_fields = [k for k, v in update_data.model_dump(exclude_none=True).items() if v is not None]
            return {
                "success": True,
                "agent_id": agent_id,
                "updated_fields": updated_fields,
                "message": f"Agent '{agent_id}' updated successfully.",
            }
        except (AuthorizationError, NotFoundError, ValidationError) as e:
            return {"success": False, "error": str(e)}
        except Exception as e:
            logger.error("foundry_agent_update_failed", error=str(e), agent_id=agent_id)
            return {"success": False, "error": "Agent update failed"}

    def deploy_from_tool(
        self,
        agent_id: str,
        session_id: UUID,
        dry_run: bool = False,
    ) -> dict:
        """Deploy a Foundry agent from a builtin tool call.

        Preserves the 3-stage pipeline (validate, availability, deploy) and dry_run support.
        """
        from .foundry_service import FoundryService, CONNECTION_REQUIRED

        try:
            agent = self.repo.get_by_agent_id(agent_id)
            if not agent:
                return {"ok": False, "stage": "load", "errors": [f"Agent '{agent_id}' not found"]}

            endpoint = os.environ.get("FOUNDRY_PROJECT_ENDPOINT")
            foundry = FoundryService(endpoint=endpoint)
            if not foundry.is_configured():
                return {
                    "ok": False,
                    "stage": "load",
                    "errors": ["Azure AI Foundry is not configured. Set FOUNDRY_PROJECT_ENDPOINT."],
                }

            detail = self._to_detail(agent)

            # Stage 1 — validate
            validation = foundry.validate_for_foundry(detail)
            if not validation["valid"]:
                return {
                    "ok": False,
                    "stage": "validate",
                    "errors": validation["errors"],
                    "warnings": validation.get("warnings", []),
                }
            warnings = validation.get("warnings", [])

            # Stage 2 — availability
            avail = foundry.list_available_tools()
            if not avail.get("ok"):
                return {
                    "ok": False,
                    "stage": "availability",
                    "errors": [avail.get("reason", "Could not check tool availability")],
                    "warnings": warnings,
                }

            avail_errors = []
            conn_by_type = {c["type"]: c for c in avail.get("connection_backed", [])}
            for tool in (detail.foundry_tools or []):
                if tool in CONNECTION_REQUIRED:
                    entry = conn_by_type.get(tool)
                    if not entry or not entry.get("available"):
                        avail_errors.append(
                            f"Tool '{tool}' requires a connection in the Foundry project but none was found"
                        )

            known_models = {m["name"] for m in avail.get("deployed_models", []) if m.get("name")}
            model = detail.llm_profile or FoundryService.resolve_model("standard")
            if known_models and model not in known_models:
                avail_errors.append(
                    f"Model '{model}' is not deployed in this project (known: {sorted(known_models)})"
                )

            if avail_errors:
                return {
                    "ok": False,
                    "stage": "availability",
                    "errors": avail_errors,
                    "warnings": warnings,
                }

            if dry_run:
                return {
                    "ok": True,
                    "stage": "availability",
                    "dry_run": True,
                    "warnings": warnings,
                    "plan": {
                        "agent_id": agent_id,
                        "name": detail.name,
                        "model": model,
                        "tools": detail.foundry_tools or [],
                    },
                }

            # Stage 3 — deploy
            from datetime import datetime, timezone

            spec_hash = foundry.compute_spec_hash(detail)
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

            logger.info(
                "foundry_agent_deployed",
                agent_id=agent_id,
                foundry_id=result.get("foundry_agent_id"),
                session_id=str(session_id),
            )

            return {
                "ok": True,
                "stage": "deploy",
                "warnings": warnings,
                "deployment": {
                    "agent_id": agent_id,
                    "foundry_agent_id": result.get("foundry_agent_id"),
                    "name": result.get("name"),
                    "version": result.get("version"),
                    "model": model,
                    "deployed_at": result.get("deployed_at"),
                },
            }
        except Exception as e:
            logger.error("foundry_deploy_failed", error=str(e), agent_id=agent_id)
            try:
                self.repo.update_deployment_status(agent_id, deployment_status="failed")
                self.repo.commit()
            except Exception:
                pass
            return {
                "ok": False,
                "stage": "deploy",
                "errors": [f"Deployment failed: {e}"],
            }

    def undeploy_from_tool(
        self,
        agent_id: str,
        session_id: UUID,
    ) -> dict:
        """Remove a deployed Foundry agent from a builtin tool call."""
        from .foundry_service import FoundryService

        try:
            agent = self.repo.get_by_agent_id(agent_id)
            if not agent:
                return {"success": False, "error": f"Agent '{agent_id}' not found"}

            owner_id = self._resolve_owner(session_id)
            if owner_id and agent.owner_id and owner_id != agent.owner_id:
                return {"success": False, "error": "Only the owner can undeploy this agent"}

            endpoint = os.environ.get("FOUNDRY_PROJECT_ENDPOINT")
            foundry = FoundryService(endpoint=endpoint)
            if foundry.is_configured():
                foundry.delete_agent(agent_id)

            self.repo.update_deployment_status(
                agent_id,
                deployment_status=None,
                deployed_at=None,
                deployed_version=None,
                deployed_spec_hash=None,
                foundry_agent_id=None,
            )
            self.repo.commit()

            logger.info(
                "foundry_agent_undeployed",
                agent_id=agent_id,
                session_id=str(session_id),
            )

            return {
                "success": True,
                "agent_id": agent_id,
                "message": f"Agent '{agent_id}' undeployed from Azure AI Foundry.",
            }
        except Exception as e:
            logger.error("foundry_undeploy_failed", error=str(e), agent_id=agent_id)
            return {"success": False, "error": f"Undeploy failed: {e}"}

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

        if detail.foundry_tool_configs:
            data["tool_resources"] = detail.foundry_tool_configs

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
            llm_profile=agent.llm_profile or "standard",
            is_active=agent.is_active if agent.is_active is not None else True,
            deployment_status=agent.deployment_status,
            is_dirty=CustomAgentService._is_dirty(agent),
            created_at=agent.created_at,
            system_prompt=agent.system_prompt or "",
            system_prompts=[sp.prompt_id for sp in agent.system_prompts],
            druppie_runtime_tools=[bt.tool_name for bt in agent.builtin_tools],
            mcps=mcps,
            approval_overrides=approval_overrides,
            skills=[s.skill_name for s in agent.skills],
            foundry_tools=[ft.tool_type for ft in agent.foundry_tools],
            foundry_tool_configs=CustomAgentService._build_foundry_tool_configs(agent.foundry_tools),
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

    @staticmethod
    def _build_foundry_tool_configs(foundry_tools) -> dict[str, dict]:
        """Build per-tool config dict from ORM foundry tool rows."""
        configs = {}
        for ft in foundry_tools:
            config = {}
            if ft.vector_store_ids:
                config["vector_store_ids"] = [
                    vid.strip() for vid in ft.vector_store_ids.split(",") if vid.strip()
                ]
            if ft.connection_id:
                config["connection_id"] = ft.connection_id
            if config:
                configs[ft.tool_type] = config
        return configs
