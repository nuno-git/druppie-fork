"""Custom agent repository for database access."""

from uuid import UUID

from .base import BaseRepository
from ..domain.agent_definition import AgentDefinition, ApprovalOverride
from ..db.models.custom_agent import (
    CustomAgent,
    CustomAgentMcp,
    CustomAgentMcpTool,
    CustomAgentSkill,
    CustomAgentSystemPrompt,
    CustomAgentBuiltinTool,
    CustomAgentApprovalOverride,
    CustomAgentFoundryTool,
)


UPDATABLE_FIELDS = {
    "name", "description", "category", "system_prompt",
    "llm_profile", "temperature", "max_tokens", "max_iterations",
    "kind", "workflow_yaml", "is_active",
}

DEPLOYMENT_FIELDS = {
    "deployment_status", "deployed_at", "deployed_version",
    "deployed_spec_hash", "foundry_agent_id",
}


class CustomAgentRepository(BaseRepository):
    """Database access for custom agent definitions."""

    def list_all(self) -> list[CustomAgent]:
        """List all custom agents."""
        return (
            self.db.query(CustomAgent)
            .order_by(CustomAgent.created_at.desc())
            .all()
        )

    def list_by_owner(self, owner_id: UUID) -> list[CustomAgent]:
        """List custom agents owned by a specific user."""
        return (
            self.db.query(CustomAgent)
            .filter(CustomAgent.owner_id == owner_id)
            .order_by(CustomAgent.created_at.desc())
            .all()
        )

    def get_by_agent_id(self, agent_id: str) -> CustomAgent | None:
        """Get a custom agent by its agent_id."""
        return self.db.query(CustomAgent).filter_by(agent_id=agent_id).first()

    def create(
        self,
        agent_id: str,
        name: str,
        description: str | None = None,
        category: str = "execution",
        kind: str = "prompt",
        system_prompt: str | None = None,
        workflow_yaml: str | None = None,
        llm_profile: str = "standard",
        temperature: float = 0.1,
        max_tokens: int = 4096,
        max_iterations: int = 10,
        owner_id: UUID | None = None,
        mcps: dict[str, list[str]] | list[str] | None = None,
        skills: list[str] | None = None,
        system_prompts_list: list[str] | None = None,
        builtin_tools: list[str] | None = None,
        approval_overrides: dict[str, dict] | None = None,
        foundry_tools: list[str] | None = None,
        foundry_tool_configs: dict[str, dict] | None = None,
    ) -> CustomAgent:
        """Create a custom agent with all child rows."""
        agent = CustomAgent(
            agent_id=agent_id,
            name=name,
            description=description,
            category=category,
            kind=kind,
            system_prompt=system_prompt,
            workflow_yaml=workflow_yaml,
            llm_profile=llm_profile,
            temperature=temperature,
            max_tokens=max_tokens,
            max_iterations=max_iterations,
            owner_id=owner_id,
        )
        self.db.add(agent)
        self.db.flush()

        self._create_child_rows(agent, mcps, skills, system_prompts_list, builtin_tools, approval_overrides, foundry_tools, foundry_tool_configs)
        self.db.flush()
        return agent

    def update(self, agent_id: str, **kwargs) -> CustomAgent:
        """Update a custom agent. Replaces child rows if provided."""
        agent = self.get_by_agent_id(agent_id)
        if not agent:
            raise ValueError(f"Custom agent '{agent_id}' not found")

        # Extract child-row kwargs
        mcps = kwargs.pop("mcps", None)
        skills = kwargs.pop("skills", None)
        system_prompts_list = kwargs.pop("system_prompts_list", None)
        builtin_tools = kwargs.pop("builtin_tools", None)
        approval_overrides = kwargs.pop("approval_overrides", None)
        foundry_tools = kwargs.pop("foundry_tools", None)
        foundry_tool_configs = kwargs.pop("foundry_tool_configs", None)

        # Update scalar fields (allowlist prevents mass-assignment)
        for key, value in kwargs.items():
            if key in UPDATABLE_FIELDS:
                setattr(agent, key, value)

        # Replace child rows if provided
        for new_value, attr in [
            (mcps, "mcps"),
            (skills, "skills"),
            (system_prompts_list, "system_prompts"),
            (builtin_tools, "builtin_tools"),
            (approval_overrides, "approval_overrides"),
            (foundry_tools, "foundry_tools"),
        ]:
            if new_value is not None:
                for row in getattr(agent, attr):
                    self.db.delete(row)
                self.db.flush()
                setattr(agent, attr, [])

        self._create_child_rows(agent, mcps, skills, system_prompts_list, builtin_tools, approval_overrides, foundry_tools, foundry_tool_configs)
        self.db.flush()
        return agent

    def update_deployment_status(self, agent_id: str, **kwargs) -> None:
        """Update deployment-related fields only."""
        agent = self.get_by_agent_id(agent_id)
        if not agent:
            raise ValueError(f"Custom agent '{agent_id}' not found")
        for key, value in kwargs.items():
            if key in DEPLOYMENT_FIELDS:
                setattr(agent, key, value)
        self.db.flush()

    def delete(self, agent_id: str) -> None:
        """Delete a custom agent by agent_id."""
        self.db.query(CustomAgent).filter_by(agent_id=agent_id).delete()

    def agent_id_exists(self, agent_id: str) -> bool:
        """Check if an agent_id already exists."""
        return self.db.query(CustomAgent).filter_by(agent_id=agent_id).first() is not None

    def list_agent_ids(self) -> list[str]:
        """List all custom agent IDs."""
        rows = self.db.query(CustomAgent.agent_id).all()
        return [row[0] for row in rows]

    def to_agent_definition(self, custom_agent: CustomAgent) -> AgentDefinition:
        """Convert a CustomAgent DB record to an AgentDefinition domain model."""
        # Build mcps field
        mcps: list[str] | dict[str, list[str]]
        has_tool_whitelist = any(mcp.tools for mcp in custom_agent.mcps)

        if has_tool_whitelist:
            mcps = {}
            for mcp in custom_agent.mcps:
                if mcp.tools:
                    mcps[mcp.mcp_name] = [t.tool_name for t in mcp.tools]
                else:
                    mcps[mcp.mcp_name] = []
        else:
            mcps = [mcp.mcp_name for mcp in custom_agent.mcps]

        # Build approval_overrides
        overrides: dict[str, ApprovalOverride] = {}
        for ao in custom_agent.approval_overrides:
            overrides[ao.tool_key] = ApprovalOverride(
                requires_approval=ao.requires_approval,
                required_role=ao.required_role,
            )

        return AgentDefinition(
            id=custom_agent.agent_id,
            name=custom_agent.name,
            description=custom_agent.description or "",
            system_prompt=custom_agent.system_prompt or "",
            extra_builtin_tools=[bt.tool_name for bt in custom_agent.builtin_tools],
            mcps=mcps,
            approval_overrides=overrides,
            skills=[s.skill_name for s in custom_agent.skills],
            system_prompts=[sp.prompt_id for sp in custom_agent.system_prompts],
            llm_profile=custom_agent.llm_profile or "standard",
            temperature=custom_agent.temperature or 0.1,
            max_tokens=custom_agent.max_tokens or 4096,
            max_iterations=custom_agent.max_iterations or 10,
        )

    def _create_child_rows(
        self,
        agent: CustomAgent,
        mcps: dict[str, list[str]] | list[str] | None,
        skills: list[str] | None,
        system_prompts_list: list[str] | None,
        builtin_tools: list[str] | None,
        approval_overrides: dict[str, dict] | None,
        foundry_tools: list[str] | None = None,
        foundry_tool_configs: dict[str, dict] | None = None,
    ) -> None:
        """Create child rows for a custom agent."""
        if mcps is not None:
            if isinstance(mcps, dict):
                for mcp_name, tools in mcps.items():
                    mcp_row = CustomAgentMcp(custom_agent_id=agent.id, mcp_name=mcp_name)
                    self.db.add(mcp_row)
                    self.db.flush()
                    for tool_name in tools:
                        self.db.add(CustomAgentMcpTool(custom_agent_mcp_id=mcp_row.id, tool_name=tool_name))
            else:
                for mcp_name in mcps:
                    self.db.add(CustomAgentMcp(custom_agent_id=agent.id, mcp_name=mcp_name))

        if skills is not None:
            for skill_name in skills:
                self.db.add(CustomAgentSkill(custom_agent_id=agent.id, skill_name=skill_name))

        if system_prompts_list is not None:
            for prompt_id in system_prompts_list:
                self.db.add(CustomAgentSystemPrompt(custom_agent_id=agent.id, prompt_id=prompt_id))

        if builtin_tools is not None:
            for tool_name in builtin_tools:
                self.db.add(CustomAgentBuiltinTool(custom_agent_id=agent.id, tool_name=tool_name))

        if approval_overrides is not None:
            for tool_key, override in approval_overrides.items():
                self.db.add(CustomAgentApprovalOverride(
                    custom_agent_id=agent.id,
                    tool_key=tool_key,
                    requires_approval=override.get("requires_approval", True),
                    required_role=override.get("required_role"),
                ))

        if foundry_tools is not None:
            configs = foundry_tool_configs or {}
            for tool_type in foundry_tools:
                tc = configs.get(tool_type, {})
                vs_ids = tc.get("vector_store_ids")
                self.db.add(CustomAgentFoundryTool(
                    custom_agent_id=agent.id,
                    tool_type=tool_type,
                    connection_id=tc.get("connection_id"),
                    vector_store_ids=",".join(vs_ids) if vs_ids else None,
                ))
