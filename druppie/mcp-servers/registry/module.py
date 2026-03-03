"""Registry MCP Server - Business Logic Module.

Loads and indexes Druppie platform building blocks at startup:
agents, skills, MCP servers, and builtin tools.
Provides read-only catalog access via list/get pattern.
"""

import ast
import logging
from collections import defaultdict
from pathlib import Path

import yaml

logger = logging.getLogger("registry-mcp")


class RegistryModule:
    """Business logic for platform registry operations."""

    def __init__(self, data_dir: str = "/data"):
        self.data_dir = Path(data_dir)
        self.agents: dict[str, dict] = {}
        self.skills: dict[str, dict] = {}
        self.mcp_servers: dict[str, dict] = {}
        self.builtin_tools: dict[str, dict] = {}
        self.default_builtin_tools: list[str] = []
        self._load_all()

    def _load_all(self):
        """Load all data sources and build cross-references."""
        self._load_agents()
        self._load_skills()
        self._load_mcp_config()
        self._load_builtin_tools()
        self._build_cross_references()
        logger.info(
            "Registry loaded: %d agents, %d skills, %d MCP servers, %d builtin tools",
            len(self.agents),
            len(self.skills),
            len(self.mcp_servers),
            len(self.builtin_tools),
        )

    # --- Data Loading ---

    def _load_agents(self):
        """Load agent definitions from YAML files."""
        agents_dir = self.data_dir / "agents"
        if not agents_dir.is_dir():
            logger.warning("Agents directory not found: %s", agents_dir)
            return

        for yaml_file in sorted(agents_dir.glob("*.yaml")):
            if yaml_file.name == "llm_profiles.yaml":
                continue
            try:
                data = yaml.safe_load(yaml_file.read_text())
                if not data or not isinstance(data, dict) or "id" not in data:
                    continue
                agent_id = data["id"]
                self.agents[agent_id] = {
                    "id": agent_id,
                    "name": data.get("name", agent_id),
                    "description": data.get("description", ""),
                    "skills": data.get("skills", []),
                    "mcps": data.get("mcps", {}),
                    "system_prompts": data.get("system_prompts", []),
                    "approval_overrides": data.get("approval_overrides", {}),
                    "llm_profile": data.get("llm_profile", ""),
                    "temperature": data.get("temperature"),
                    "max_tokens": data.get("max_tokens"),
                    "max_iterations": data.get("max_iterations"),
                }
                logger.info("Loaded agent: %s", agent_id)
            except Exception as e:
                logger.error("Failed to parse agent %s: %s", yaml_file.name, e)

    def _load_skills(self):
        """Load skills from SKILL.md frontmatter."""
        skills_dir = self.data_dir / "skills"
        if not skills_dir.is_dir():
            logger.warning("Skills directory not found: %s", skills_dir)
            return

        for skill_dir in sorted(skills_dir.iterdir()):
            skill_file = skill_dir / "SKILL.md"
            if not skill_file.is_file():
                continue
            try:
                content = skill_file.read_text()
                frontmatter, body = self._parse_frontmatter(content)
                if not frontmatter:
                    continue
                name = frontmatter.get("name", skill_dir.name)
                self.skills[name] = {
                    "name": name,
                    "description": frontmatter.get("description", ""),
                    "allowed_tools": frontmatter.get("allowed-tools", {}),
                    "content": body,
                }
                logger.info("Loaded skill: %s", name)
            except Exception as e:
                logger.error("Failed to parse skill %s: %s", skill_dir.name, e)

    def _parse_frontmatter(self, text: str) -> tuple[dict | None, str]:
        """Parse YAML frontmatter from markdown text."""
        if not text.startswith("---"):
            return None, text
        parts = text.split("---", 2)
        if len(parts) < 3:
            return None, text
        frontmatter = yaml.safe_load(parts[1])
        body = parts[2].strip()
        return frontmatter, body

    def _load_mcp_config(self):
        """Load MCP server definitions from mcp_config.yaml."""
        config_path = self.data_dir / "mcp_config.yaml"
        if not config_path.is_file():
            logger.warning("MCP config not found: %s", config_path)
            return

        try:
            content = config_path.read_text()
            # Strip env var syntax ${VAR:-default} → default
            import re
            content = re.sub(r'\$\{[^:}]+:-([^}]*)\}', r'\1', content)
            config = yaml.safe_load(content)

            for server_name, server_data in config.get("mcps", {}).items():
                tools = []
                for tool in server_data.get("tools", []):
                    tools.append({
                        "name": tool.get("name", ""),
                        "description": tool.get("description", ""),
                        "requires_approval": tool.get("requires_approval", False),
                        "required_role": tool.get("required_role"),
                        "parameters": tool.get("parameters"),
                    })
                self.mcp_servers[server_name] = {
                    "name": server_name,
                    "description": server_data.get("description", ""),
                    "tools": tools,
                    "tool_count": len(tools),
                }
                logger.info("Loaded MCP server: %s (%d tools)", server_name, len(tools))
        except Exception as e:
            logger.error("Failed to parse MCP config: %s", e)

    def _load_builtin_tools(self):
        """Load builtin tool definitions using ast (safe, no code execution)."""
        bt_path = self.data_dir / "builtin_tools.py"
        if not bt_path.is_file():
            logger.warning("Builtin tools file not found: %s", bt_path)
            return

        try:
            source = bt_path.read_text()
            tree = ast.parse(source)

            for node in ast.walk(tree):
                # Handle both regular (x = ...) and annotated (x: type = ...) assignments
                if isinstance(node, ast.Assign):
                    targets = [t for t in node.targets if isinstance(t, ast.Name)]
                    value = node.value
                elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value:
                    targets = [node.target]
                    value = node.value
                else:
                    continue
                for target in targets:
                    if target.id == "BUILTIN_TOOL_DEFS":
                        defs = ast.literal_eval(ast.unparse(value))
                        for tool_name, tool_def in defs.items():
                            func = tool_def.get("function", {})
                            self.builtin_tools[tool_name] = {
                                "name": func.get("name", tool_name),
                                "description": func.get("description", ""),
                                "parameters": func.get("parameters", {}),
                            }
                        logger.info("Loaded %d builtin tools", len(self.builtin_tools))
                    elif target.id == "DEFAULT_BUILTIN_TOOLS":
                        self.default_builtin_tools = ast.literal_eval(
                            ast.unparse(value)
                        )
        except Exception as e:
            logger.error("Failed to parse builtin tools: %s", e)

    def _build_cross_references(self):
        """Build cross-references: which agents use which MCP servers/tools."""
        # Build used_by_agents for each MCP server
        for server_name, server in self.mcp_servers.items():
            used_by = []
            for agent_id, agent in self.agents.items():
                if server_name in agent.get("mcps", {}):
                    used_by.append(agent_id)
            server["used_by_agents"] = used_by

        # Build agent_overrides per tool
        for server_name, server in self.mcp_servers.items():
            for tool in server["tools"]:
                overrides = {}
                for agent_id, agent in self.agents.items():
                    key = f"{server_name}:{tool['name']}"
                    if key in agent.get("approval_overrides", {}):
                        overrides[agent_id] = agent["approval_overrides"][key]
                tool["agent_overrides"] = overrides

    # --- Public API ---

    def list_components(self, category: str = "") -> dict:
        """List all building blocks, optionally filtered by category."""
        categories = {}

        if not category or category == "agents":
            categories["agents"] = {
                "count": len(self.agents),
                "items": [
                    {
                        "id": a["id"],
                        "name": a["name"],
                        "description": a["description"],
                    }
                    for a in sorted(self.agents.values(), key=lambda x: x["id"])
                ],
            }

        if not category or category == "skills":
            categories["skills"] = {
                "count": len(self.skills),
                "items": [
                    {
                        "name": s["name"],
                        "description": s["description"],
                    }
                    for s in sorted(self.skills.values(), key=lambda x: x["name"])
                ],
            }

        if not category or category == "mcps":
            categories["mcps"] = {
                "count": len(self.mcp_servers),
                "items": [
                    {
                        "name": m["name"],
                        "description": m["description"],
                        "tool_count": m["tool_count"],
                    }
                    for m in sorted(
                        self.mcp_servers.values(), key=lambda x: x["name"]
                    )
                ],
            }

        if not category or category == "builtin_tools":
            categories["builtin_tools"] = {
                "count": len(self.builtin_tools),
                "items": [
                    {
                        "name": t["name"],
                        "description": t["description"],
                    }
                    for t in sorted(
                        self.builtin_tools.values(), key=lambda x: x["name"]
                    )
                ],
            }

        total = sum(c["count"] for c in categories.values())
        return {"success": True, "categories": categories, "total": total}

    def get_agent(self, agent_id: str) -> dict:
        """Get full details of an agent."""
        agent = self.agents.get(agent_id)
        if not agent:
            return {
                "success": False,
                "error": f"Agent '{agent_id}' not found. Use list_components(category='agents') to see available agents.",
            }

        # Determine builtin tools for this agent
        builtin = list(self.default_builtin_tools)
        if agent.get("skills"):
            builtin.append("invoke_skill")

        return {
            "success": True,
            "agent": {
                **agent,
                "builtin_tools": builtin,
            },
        }

    def get_skill(self, skill_name: str) -> dict:
        """Get full skill content."""
        skill = self.skills.get(skill_name)
        if not skill:
            return {
                "success": False,
                "error": f"Skill '{skill_name}' not found. Use list_components(category='skills') to see available skills.",
            }
        return {"success": True, "skill": skill}

    def get_mcp_server(self, server_name: str) -> dict:
        """Get MCP server details with full tool list."""
        server = self.mcp_servers.get(server_name)
        if not server:
            return {
                "success": False,
                "error": f"MCP server '{server_name}' not found. Use list_components(category='mcps') to see available servers.",
            }
        return {"success": True, "server": server}

    def get_tool(self, server_name: str, tool_name: str) -> dict:
        """Get full tool definition with parameters and approval info."""
        server = self.mcp_servers.get(server_name)
        if not server:
            return {
                "success": False,
                "error": f"MCP server '{server_name}' not found.",
            }

        for tool in server["tools"]:
            if tool["name"] == tool_name:
                return {
                    "success": True,
                    "tool": {
                        **tool,
                        "server": server_name,
                        "used_by_agents": [
                            agent_id
                            for agent_id, agent in self.agents.items()
                            if server_name in agent.get("mcps", {})
                            and tool_name in agent["mcps"].get(server_name, [])
                        ],
                    },
                }

        return {
            "success": False,
            "error": f"Tool '{tool_name}' not found in server '{server_name}'. Use get_mcp_server('{server_name}') to see available tools.",
        }
