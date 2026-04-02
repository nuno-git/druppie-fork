"""Registry Module v1 — Business Logic.

Module-first registry for the Druppie platform. Every MCP server IS a module
(containerized MCP server with MODULE.yaml). This registry provides discovery
and inspection of modules, agents, skills, and builtin tools.

Data sources:
- MODULE.yaml files from mcp-servers/ directories (identity, versions)
- mcp_config.yaml (URLs, types, approval rules, tool lists)
- Live MCP servers via tools/list (tool schemas, descriptions)
- Agent YAML definitions (agent config, cross-references)
- SKILL.md frontmatter (skill metadata)
- builtin_tools.py (builtin tool definitions)
"""

import ast
import logging
import re
import time
from pathlib import Path

import yaml
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

logger = logging.getLogger("registry-mcp")


class RegistryModule:
    """Business logic for the platform registry.

    Modules are the primary concept — every MCP server is a module.
    Agents, skills, and builtin tools are supporting building blocks.
    """

    def __init__(self, data_dir: str = "/data"):
        self.data_dir = Path(data_dir)
        self.modules: dict[str, dict] = {}
        self.agents: dict[str, dict] = {}
        self.skills: dict[str, dict] = {}
        self.builtin_tools: dict[str, dict] = {}
        self.default_builtin_tools: list[str] = []
        self._tool_cache: dict[str, list[dict]] = {}
        self._cache_ttl = 60  # seconds
        self._cache_timestamps: dict[str, float] = {}
        self._load_all()

    def _load_all(self):
        """Load all data sources and build cross-references."""
        self._load_agents()
        self._load_skills()
        self._load_builtin_tools()
        self._load_modules()
        self._build_cross_references()
        logger.info(
            "Registry loaded: %d modules, %d agents, %d skills, %d builtin tools",
            len(self.modules),
            len(self.agents),
            len(self.skills),
            len(self.builtin_tools),
        )

    # ── Data Loading ─────────────────────────────────────────────────────

    def _load_modules(self):
        """Load modules by merging MODULE.yaml manifests with mcp_config.yaml.

        A module is identified by its MODULE.yaml file in mcp-servers/module-<name>/.
        The mcp_config.yaml provides the URL, type, tool approval rules, and
        injection config for each module.
        """
        # First, load mcp_config.yaml for URLs, types, and tool approval rules
        mcp_config = self._read_mcp_config()

        # Then scan MODULE.yaml files — these are the source of truth for identity
        mcp_servers_dir = self.data_dir / "mcp-servers"
        if not mcp_servers_dir.is_dir():
            logger.warning("MCP servers directory not found: %s", mcp_servers_dir)
            return

        for module_dir in sorted(mcp_servers_dir.iterdir()):
            if not module_dir.is_dir() or not module_dir.name.startswith("module-"):
                continue
            manifest_path = module_dir / "MODULE.yaml"
            if not manifest_path.is_file():
                continue
            try:
                manifest = yaml.safe_load(manifest_path.read_text())
                if not manifest or not isinstance(manifest, dict) or "id" not in manifest:
                    continue

                module_id = manifest["id"]
                config = mcp_config.get(module_id, {})

                # Parse tool definitions from mcp_config (approval rules, etc.)
                config_tools = []
                for tool in config.get("tools", []):
                    config_tools.append({
                        "name": tool.get("name", ""),
                        "description": tool.get("description", ""),
                        "requires_approval": tool.get("requires_approval", False),
                        "required_role": tool.get("required_role"),
                        "parameters": tool.get("parameters"),
                    })

                self.modules[module_id] = {
                    "id": module_id,
                    "directory": module_dir.name,
                    "latest_version": manifest.get("latest_version", "1.0.0"),
                    "versions": manifest.get("versions", []),
                    "type": config.get("type", "core"),
                    "url": config.get("url", ""),
                    "config_tools": config_tools,
                }
                logger.info(
                    "Loaded module: %s (versions: %s, type: %s, tools: %d)",
                    module_id,
                    manifest.get("versions", []),
                    config.get("type", "core"),
                    len(config_tools),
                )
            except Exception as e:
                logger.error("Failed to load module from %s: %s", module_dir.name, e)

    def _read_mcp_config(self) -> dict:
        """Read mcp_config.yaml and return the mcps dict keyed by module id."""
        config_path = self.data_dir / "mcp_config.yaml"
        if not config_path.is_file():
            logger.warning("MCP config not found: %s", config_path)
            return {}

        try:
            content = config_path.read_text()
            # Strip env var syntax ${VAR:-default} → default
            content = re.sub(r'\$\{[^:}]+:-([^}]*)\}', r'\1', content)
            config = yaml.safe_load(content)
            return config.get("mcps", {})
        except Exception as e:
            logger.error("Failed to parse MCP config: %s", e)
            return {}

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
        """Build cross-references: which agents use which modules."""
        for module_id, module in self.modules.items():
            used_by = []
            for agent_id, agent in self.agents.items():
                if module_id in agent.get("mcps", {}):
                    used_by.append(agent_id)
            module["used_by_agents"] = sorted(used_by)

        # Build agent_overrides per tool within each module
        for module_id, module in self.modules.items():
            for tool in module["config_tools"]:
                overrides = {}
                for agent_id, agent in self.agents.items():
                    key = f"{module_id}:{tool['name']}"
                    if key in agent.get("approval_overrides", {}):
                        overrides[agent_id] = agent["approval_overrides"][key]
                tool["agent_overrides"] = overrides

    # ── Live MCP Discovery ───────────────────────────────────────────────

    def _get_module_url(self, module_id: str) -> str | None:
        """Get module URL from loaded config."""
        module = self.modules.get(module_id, {})
        return module.get("url") or None

    async def _get_live_tools(self, module_id: str) -> list[dict] | None:
        """Fetch tools from a live module via MCP tools/list.

        Returns cached results if within TTL. Returns None on failure
        (caller should fall back to config-based tools).
        """
        now = time.time()
        if module_id in self._tool_cache:
            if now - self._cache_timestamps.get(module_id, 0) < self._cache_ttl:
                return self._tool_cache[module_id]

        url = self._get_module_url(module_id)
        if not url:
            return None

        try:
            transport = StreamableHttpTransport(url=f"{url}/mcp")
            async with Client(transport) as client:
                tools = await client.list_tools()
                result = [
                    {
                        "name": t.name,
                        "description": t.description or "",
                        "parameters": t.inputSchema if hasattr(t, "inputSchema") else {},
                        "meta": dict(t.meta) if hasattr(t, "meta") and t.meta else {},
                    }
                    for t in tools
                ]
                self._tool_cache[module_id] = result
                self._cache_timestamps[module_id] = now
                return result
        except Exception as e:
            logger.warning("Failed to fetch tools from module %s: %s", module_id, e)
            return None

    async def _get_live_description(self, module_id: str) -> str:
        """Fetch module description from live MCP server instructions."""
        url = self._get_module_url(module_id)
        if not url:
            return ""

        try:
            transport = StreamableHttpTransport(url=f"{url}/mcp")
            async with Client(transport) as client:
                if hasattr(client, "_server_instructions") and client._server_instructions:
                    return client._server_instructions
                return ""
        except Exception as e:
            logger.warning("Failed to fetch description from module %s: %s", module_id, e)
            return ""

    # ── Public API: Modules ──────────────────────────────────────────────

    def list_modules(self, category: str = "") -> dict:
        """List all available modules, optionally filtered by type.

        Args:
            category: Filter by MCP type — "core", "module", or "both". Empty = all.
        """
        items = []
        for module in sorted(self.modules.values(), key=lambda m: m["id"]):
            if category and module["type"] != category:
                continue
            items.append({
                "id": module["id"],
                "latest_version": module["latest_version"],
                "versions": module["versions"],
                "type": module["type"],
                "tool_count": len(module["config_tools"]),
                "used_by_agents": module.get("used_by_agents", []),
            })

        return {
            "success": True,
            "count": len(items),
            "modules": items,
        }

    async def get_module(self, module_id: str, version: str = "") -> dict:
        """Get detailed info for a specific module.

        Returns module identity (from MODULE.yaml), tools (live MCP discovery
        with config fallback), approval rules, and agent cross-references.

        Args:
            module_id: The module identifier (e.g. "coding", "ocr").
            version: Major version to inspect (e.g. "v1", "v2"). Defaults to latest.
        """
        module = self.modules.get(module_id)
        if not module:
            return {
                "success": False,
                "error": f"Module '{module_id}' not found. Use list_modules() to see available modules.",
            }

        # Determine which version to show
        if version:
            display_version = version.lstrip("v")
        else:
            display_version = module["latest_version"].split(".")[0]

        # Try live MCP discovery first, fall back to config
        live_tools = await self._get_live_tools(module_id)
        if live_tools is not None:
            # Merge live tool schemas with approval rules from config
            config_by_name = {t["name"]: t for t in module["config_tools"]}
            tools = []
            for lt in live_tools:
                ct = config_by_name.get(lt["name"], {})
                tools.append({
                    "name": lt["name"],
                    "description": lt["description"],
                    "parameters": lt.get("parameters", {}),
                    "requires_approval": ct.get("requires_approval", False),
                    "required_role": ct.get("required_role"),
                    "agent_overrides": ct.get("agent_overrides", {}),
                })
        else:
            tools = [
                {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "requires_approval": t.get("requires_approval", False),
                    "required_role": t.get("required_role"),
                    "agent_overrides": t.get("agent_overrides", {}),
                }
                for t in module["config_tools"]
            ]

        # Get description from live MCP if available
        description = await self._get_live_description(module_id)

        return {
            "success": True,
            "module": {
                "id": module_id,
                "latest_version": module["latest_version"],
                "versions": module["versions"],
                "type": module["type"],
                "description": description,
                "showing_version": f"v{display_version}",
                "tools": tools,
                "used_by_agents": module.get("used_by_agents", []),
            },
        }

    def search_modules(self, query: str) -> dict:
        """Search modules by keyword across IDs, tool names, and descriptions.

        Args:
            query: Search keyword (case-insensitive).
        """
        if not query or not query.strip():
            return {"success": False, "error": "Query must not be empty."}

        query_lower = query.strip().lower()
        results = []

        for module in sorted(self.modules.values(), key=lambda m: m["id"]):
            # Search in module ID
            if query_lower in module["id"].lower():
                results.append(self._search_result(module, "id"))
                continue

            # Search in tool names and descriptions
            matched_tools = []
            for tool in module["config_tools"]:
                name = tool.get("name", "")
                desc = tool.get("description", "")
                if query_lower in name.lower() or query_lower in desc.lower():
                    matched_tools.append(name)
            if matched_tools:
                results.append(self._search_result(module, "tools", matched_tools))
                continue

        return {
            "success": True,
            "query": query.strip(),
            "count": len(results),
            "results": results,
        }

    def _search_result(self, module: dict, match_field: str, matched_tools: list[str] | None = None) -> dict:
        """Build a search result entry for a module."""
        result = {
            "id": module["id"],
            "latest_version": module["latest_version"],
            "type": module["type"],
            "match_field": match_field,
        }
        if matched_tools:
            result["matched_tools"] = matched_tools
        return result

    # ── Public API: Components (agents, skills, builtin tools) ───────────

    def list_components(self, category: str = "") -> dict:
        """List agents, skills, and builtin tools.

        For modules, use list_modules() instead.

        Args:
            category: Filter — "agents", "skills", or "builtin_tools". Empty = all.
        """
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
