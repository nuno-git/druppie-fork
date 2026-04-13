"""Architecture API routes.

Endpoints for the architecture overview page.
Provides agent definitions, MCP server info, permission matrix, and documentation.
"""

import os
from pathlib import Path

import structlog
import yaml
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from druppie.api.deps import get_current_user
from druppie.api.errors import NotFoundError
from druppie.core.mcp_config import get_mcp_config

logger = structlog.get_logger()

router = APIRouter()

DEFINITIONS_DIR = Path(__file__).parent.parent.parent / "agents" / "definitions"
DOCS_DIR = Path(__file__).parent.parent.parent.parent / "docs"

# Cached agent definitions: {agent_id: raw_yaml_dict}
_agent_defs_cache: dict[str, dict] = {}
_agent_defs_mtimes: dict[str, float] = {}


def _load_agent_definitions() -> dict[str, dict]:
    """Load all agent definitions from YAML, with mtime-based cache.

    Only re-reads files that changed on disk since last call.
    """
    if not DEFINITIONS_DIR.exists():
        return {}

    current_files = {f.stem: f for f in DEFINITIONS_DIR.glob("*.yaml")}

    # Remove agents whose files were deleted
    for agent_id in list(_agent_defs_cache.keys()):
        if agent_id not in current_files:
            del _agent_defs_cache[agent_id]
            _agent_defs_mtimes.pop(agent_id, None)

    for agent_id, yaml_file in current_files.items():
        try:
            mtime = yaml_file.stat().st_mtime
            if agent_id in _agent_defs_cache and _agent_defs_mtimes.get(agent_id) == mtime:
                continue

            with open(yaml_file, "r") as f:
                data = yaml.safe_load(f)

            if not data or not data.get("id"):
                continue
            if data.get("id") == "llm_profiles":
                continue

            _agent_defs_cache[data["id"]] = data
            _agent_defs_mtimes[agent_id] = mtime
        except Exception as e:
            logger.error("failed_to_load_agent_yaml", file=str(yaml_file), error=str(e))

    return _agent_defs_cache

# Allowed doc files (prevent path traversal)
ALLOWED_DOCS = {
    "TECHNICAL": "TECHNICAL.md",
    "FEATURES": "FEATURES.md",
    "SANDBOX": "SANDBOX.md",
    "BACKLOG": "BACKLOG.md",
    "module-specification": "module-specification.md",
    "modules-research-and-decisions": "modules-research-and-decisions.md",
}


# =============================================================================
# RESPONSE MODELS
# =============================================================================


class AgentSkillResponse(BaseModel):
    name: str


class AgentDetailResponse(BaseModel):
    id: str
    name: str
    description: str
    category: str = "execution"
    mcps: list[str] = []
    mcp_tool_access: dict[str, list[str] | None] = {}
    skills: list[str] = []
    extra_builtin_tools: list[str] = []
    llm_profile: str = "standard"
    temperature: float = 0.1
    max_tokens: int = 4096
    max_iterations: int = 10
    approval_overrides: dict[str, dict] = {}
    system_prompts: list[str] = []


class AgentsArchResponse(BaseModel):
    agents: list[AgentDetailResponse]
    total: int


class PermissionEntry(BaseModel):
    agent_id: str
    server: str
    tool: str
    has_access: bool
    requires_approval: bool
    required_role: str | None = None


class PermissionMatrixResponse(BaseModel):
    entries: list[PermissionEntry]
    agents: list[str]
    servers: dict[str, list[str]]


class DocListItem(BaseModel):
    id: str
    name: str
    filename: str


class DocListResponse(BaseModel):
    docs: list[DocListItem]


class DocContentResponse(BaseModel):
    id: str
    name: str
    content: str


# =============================================================================
# ROUTES
# =============================================================================


@router.get("/architecture/agents", response_model=AgentsArchResponse)
async def list_architecture_agents(
    user: dict = Depends(get_current_user),
):
    """List all agents with full architecture details."""
    agents = []

    for data in _load_agent_definitions().values():
        try:
            # Parse MCP access
            mcps_raw = data.get("mcps", [])
            if isinstance(mcps_raw, dict):
                mcp_list = list(mcps_raw.keys())
                mcp_tool_access = {k: v if isinstance(v, list) else None for k, v in mcps_raw.items()}
            else:
                mcp_list = mcps_raw
                mcp_tool_access = {m: None for m in mcps_raw}

            # Parse approval overrides
            overrides_raw = data.get("approval_overrides", {})
            overrides = {}
            for key, val in overrides_raw.items():
                if isinstance(val, dict):
                    overrides[key] = val
                else:
                    overrides[key] = {"requires_approval": val}

            agent = AgentDetailResponse(
                id=data["id"],
                name=data.get("name", data["id"]),
                description=data.get("description", ""),
                category=data.get("category", "execution"),
                mcps=mcp_list,
                mcp_tool_access=mcp_tool_access,
                skills=data.get("skills", []),
                extra_builtin_tools=data.get("extra_builtin_tools", []),
                llm_profile=data.get("llm_profile", "standard"),
                temperature=data.get("temperature", 0.1),
                max_tokens=data.get("max_tokens", 4096),
                max_iterations=data.get("max_iterations", 10),
                approval_overrides=overrides,
                system_prompts=data.get("system_prompts", []),
            )
            agents.append(agent)

        except Exception as e:
            logger.error("failed_to_load_agent_for_architecture", agent_id=data.get("id"), error=str(e))

    # Sort by category then name
    category_order = {"system": 0, "execution": 1, "quality": 2, "deployment": 3}
    agents.sort(key=lambda a: (category_order.get(a.category, 99), a.name))

    return AgentsArchResponse(agents=agents, total=len(agents))


@router.get("/architecture/permissions", response_model=PermissionMatrixResponse)
async def get_permission_matrix(
    user: dict = Depends(get_current_user),
):
    """Get the full permission matrix: which agents can use which tools."""
    mcp_config = get_mcp_config()
    config = mcp_config.config

    agent_definitions = _load_agent_definitions()

    # Build the matrix
    entries = []
    all_agents = sorted(agent_definitions.keys())
    servers_with_tools: dict[str, list[str]] = {}

    for server_id, server_config in config.get("mcps", {}).items():
        tools = server_config.get("tools", [])
        tool_names = [t["name"] for t in tools]
        if not tool_names:
            continue
        servers_with_tools[server_id] = tool_names

        for tool_config in tools:
            tool_name = tool_config["name"]
            global_approval = tool_config.get("requires_approval", False)
            global_role = tool_config.get("required_role")

            for agent_id, agent_data in agent_definitions.items():
                # Check if agent has access to this server
                agent_mcps = agent_data.get("mcps", [])
                if isinstance(agent_mcps, dict):
                    if server_id not in agent_mcps:
                        entries.append(PermissionEntry(
                            agent_id=agent_id, server=server_id, tool=tool_name,
                            has_access=False, requires_approval=False,
                        ))
                        continue
                    # Check tool-level access
                    allowed_tools = agent_mcps.get(server_id)
                    if isinstance(allowed_tools, list) and tool_name not in allowed_tools:
                        entries.append(PermissionEntry(
                            agent_id=agent_id, server=server_id, tool=tool_name,
                            has_access=False, requires_approval=False,
                        ))
                        continue
                else:
                    if server_id not in agent_mcps:
                        entries.append(PermissionEntry(
                            agent_id=agent_id, server=server_id, tool=tool_name,
                            has_access=False, requires_approval=False,
                        ))
                        continue

                # Agent has access - check approval requirements
                requires_approval = global_approval
                required_role = global_role

                # Check agent overrides
                override_key = f"{server_id}:{tool_name}"
                overrides = agent_data.get("approval_overrides", {})
                if override_key in overrides:
                    override = overrides[override_key]
                    if isinstance(override, dict):
                        requires_approval = override.get("requires_approval", requires_approval)
                        required_role = override.get("required_role", required_role)

                entries.append(PermissionEntry(
                    agent_id=agent_id, server=server_id, tool=tool_name,
                    has_access=True, requires_approval=requires_approval,
                    required_role=required_role,
                ))

    return PermissionMatrixResponse(
        entries=entries,
        agents=all_agents,
        servers=servers_with_tools,
    )


@router.get("/architecture/docs", response_model=DocListResponse)
async def list_docs(
    user: dict = Depends(get_current_user),
):
    """List available documentation files."""
    docs = []
    for doc_id, filename in ALLOWED_DOCS.items():
        filepath = DOCS_DIR / filename
        if filepath.exists():
            # Create a readable name from the filename
            name = filename.replace(".md", "").replace("-", " ").replace("_", " ").title()
            docs.append(DocListItem(id=doc_id, name=name, filename=filename))

    return DocListResponse(docs=docs)


@router.get("/architecture/docs/{doc_id}", response_model=DocContentResponse)
async def get_doc(
    doc_id: str,
    user: dict = Depends(get_current_user),
):
    """Get the content of a documentation file."""
    if doc_id not in ALLOWED_DOCS:
        raise NotFoundError("document", doc_id)

    filename = ALLOWED_DOCS[doc_id]
    filepath = DOCS_DIR / filename

    if not filepath.exists():
        raise NotFoundError("document", doc_id)

    content = filepath.read_text(encoding="utf-8")
    name = filename.replace(".md", "").replace("-", " ").replace("_", " ").title()

    return DocContentResponse(id=doc_id, name=name, content=content)


@router.post("/architecture/refresh")
async def refresh_architecture(
    user: dict = Depends(get_current_user),
):
    """Clear architecture caches after a core update.

    Forces re-read of agent YAML definitions and MCP config from disk.
    Called automatically after update_core_builder completes.
    """
    from druppie.agents.definition_loader import AgentDefinitionLoader

    AgentDefinitionLoader.clear_cache()
    get_mcp_config().clear_cache()
    _agent_defs_cache.clear()
    _agent_defs_mtimes.clear()

    logger.info("architecture_cache_refreshed", user_id=user.get("sub"))

    return {"status": "refreshed"}


# =============================================================================
# WORKFLOW - Dynamic agent connections
# =============================================================================


class WorkflowConnection(BaseModel):
    from_agent: str
    to_agent: str
    label: str = ""
    color: str = "#3b82f6"
    dashed: bool = False


class WorkflowResponse(BaseModel):
    connections: list[WorkflowConnection]


WORKFLOW_YAML = DEFINITIONS_DIR / "workflow.yaml"


def _load_workflow_rules() -> list[dict]:
    """Load workflow connections from workflow.yaml."""
    if not WORKFLOW_YAML.exists():
        logger.warning("workflow_yaml_not_found", path=str(WORKFLOW_YAML))
        return []
    try:
        with open(WORKFLOW_YAML, "r") as f:
            data = yaml.safe_load(f)
        return data.get("connections", [])
    except Exception as e:
        logger.error("workflow_yaml_load_failed", error=str(e))
        return []


@router.get("/architecture/workflow", response_model=WorkflowResponse)
async def get_workflow(
    user: dict = Depends(get_current_user),
):
    """Get the agent workflow connections.

    Returns only connections where both agents exist in the current definitions.
    This means new agents appear automatically, and removed agents disappear.
    """
    agent_ids = set(_load_agent_definitions().keys())

    # Filter connections to only include existing agents
    connections = []
    for rule in _load_workflow_rules():
        if rule["from"] in agent_ids and rule["to"] in agent_ids:
            connections.append(WorkflowConnection(
                from_agent=rule["from"],
                to_agent=rule["to"],
                label=rule.get("label", ""),
                color=rule.get("color", "#3b82f6"),
                dashed=rule.get("dashed", False),
            ))

    return WorkflowResponse(connections=connections)
