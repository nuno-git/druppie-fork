"""Index platform documentation into module-vectorstore.

Indexes skills, platform standards, and module specifications into a
'platform-knowledge' index so agents can semantically search platform docs.

Requires module-vectorstore and module-llm to be running.
"""

import json
import logging
import sys
import time
from pathlib import Path

import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("index-platform-knowledge")

VECTORSTORE_URL = "http://module-vectorstore:9012"
DRUPPIE_DIR = Path("/app/druppie") if Path("/app/druppie").exists() else Path(__file__).parent.parent / "druppie"

INDEX_NAME = "platform-knowledge"
PROJECT_ID = "__platform__"


def collect_skills() -> list[dict]:
    """Collect all SKILL.md files."""
    docs = []
    skills_dir = DRUPPIE_DIR / "skills"
    if not skills_dir.exists():
        logger.warning("Skills directory not found: %s", skills_dir)
        return docs

    for skill_dir in sorted(skills_dir.iterdir()):
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.exists():
            continue
        content = skill_file.read_text(encoding="utf-8")
        docs.append({
            "content": content,
            "source_name": f"skills/{skill_dir.name}/SKILL.md",
            "source_type": "markdown",
            "source_section": f"Skill: {skill_dir.name}",
            "metadata": {"type": "skill", "skill_name": skill_dir.name},
        })
        logger.info("Collected skill: %s", skill_dir.name)

    return docs


def collect_standards() -> list[dict]:
    """Collect platform standards templates."""
    docs = []
    templates_dir = DRUPPIE_DIR / "templates" / "project" / "docs"
    if not templates_dir.exists():
        logger.warning("Templates directory not found: %s", templates_dir)
        return docs

    for md_file in sorted(templates_dir.glob("*.md")):
        content = md_file.read_text(encoding="utf-8")
        docs.append({
            "content": content,
            "source_name": f"templates/project/docs/{md_file.name}",
            "source_type": "markdown",
            "source_section": f"Standard: {md_file.stem}",
            "metadata": {"type": "standard", "standard_name": md_file.stem},
        })
        logger.info("Collected standard: %s", md_file.name)

    return docs


def collect_module_specs() -> list[dict]:
    """Collect MODULE.yaml + tool descriptions from mcp_config."""
    docs = []
    mcp_servers_dir = DRUPPIE_DIR / "mcp-servers"
    mcp_config_path = DRUPPIE_DIR / "core" / "mcp_config.yaml"

    mcp_config_content = ""
    if mcp_config_path.exists():
        mcp_config_content = mcp_config_path.read_text(encoding="utf-8")
        docs.append({
            "content": mcp_config_content,
            "source_name": "core/mcp_config.yaml",
            "source_type": "yaml",
            "source_section": "MCP Configuration",
            "metadata": {"type": "config", "config_name": "mcp_config"},
        })
        logger.info("Collected mcp_config.yaml")

    if not mcp_servers_dir.exists():
        return docs

    for module_dir in sorted(mcp_servers_dir.iterdir()):
        if not module_dir.is_dir() or not module_dir.name.startswith("module-"):
            continue

        module_yaml = module_dir / "MODULE.yaml"
        if not module_yaml.exists():
            continue

        parts = [module_yaml.read_text(encoding="utf-8")]

        tools_py = module_dir / "v1" / "tools.py"
        if tools_py.exists():
            parts.append(tools_py.read_text(encoding="utf-8"))

        content = "\n\n---\n\n".join(parts)
        module_name = module_dir.name.replace("module-", "")

        docs.append({
            "content": content,
            "source_name": f"mcp-servers/{module_dir.name}/MODULE.yaml",
            "source_type": "yaml",
            "source_section": f"Module: {module_name}",
            "metadata": {"type": "module", "module_name": module_name},
        })
        logger.info("Collected module: %s", module_name)

    return docs


def collect_agent_definitions() -> list[dict]:
    """Collect agent YAML definitions."""
    docs = []
    agents_dir = DRUPPIE_DIR / "agents" / "definitions"
    if not agents_dir.exists():
        logger.warning("Agent definitions directory not found: %s", agents_dir)
        return docs

    for yaml_file in sorted(agents_dir.glob("*.yaml")):
        if yaml_file.name in ("llm_profiles.yaml",):
            continue
        content = yaml_file.read_text(encoding="utf-8")
        agent_name = yaml_file.stem
        docs.append({
            "content": content,
            "source_name": f"agents/definitions/{yaml_file.name}",
            "source_type": "yaml",
            "source_section": f"Agent: {agent_name}",
            "metadata": {"type": "agent", "agent_name": agent_name},
        })
        logger.info("Collected agent definition: %s", agent_name)

    return docs


def collect_documentation() -> list[dict]:
    """Collect docs/ folder markdown files."""
    docs = []
    docs_dir = DRUPPIE_DIR.parent / "docs"
    if not docs_dir.exists():
        logger.warning("Docs directory not found: %s", docs_dir)
        return docs

    for md_file in sorted(docs_dir.glob("**/*.md")):
        content = md_file.read_text(encoding="utf-8")
        rel_path = md_file.relative_to(docs_dir.parent)
        docs.append({
            "content": content,
            "source_name": str(rel_path).replace("\\", "/"),
            "source_type": "markdown",
            "source_section": f"Doc: {md_file.stem}",
            "metadata": {"type": "documentation", "doc_name": md_file.stem},
        })
        logger.info("Collected doc: %s", rel_path)

    return docs


def wait_for_service(url: str, name: str, max_retries: int = 30, delay: float = 2.0):
    """Wait for a service to become healthy."""
    for attempt in range(max_retries):
        try:
            resp = httpx.get(f"{url}/health", timeout=5.0)
            if resp.status_code == 200:
                logger.info("%s is healthy", name)
                return
        except httpx.ConnectError:
            pass
        if attempt < max_retries - 1:
            logger.info("Waiting for %s... (attempt %d/%d)", name, attempt + 1, max_retries)
            time.sleep(delay)

    logger.error("%s not available after %d attempts", name, max_retries)
    sys.exit(1)


def index_documents(documents: list[dict]):
    """Call vectorstore index_documents via direct HTTP API."""
    from fastmcp import Client
    from fastmcp.client.transports import StreamableHttpTransport
    import asyncio

    async def _do_index():
        transport = StreamableHttpTransport(url=f"{VECTORSTORE_URL}/mcp")
        async with Client(transport) as client:
            result = await client.call_tool("index_documents", {
                "index_name": INDEX_NAME,
                "documents": documents,
                "description": "Druppie platform documentation — skills, standards, modules, agents",
                "project_id": PROJECT_ID,
                "chunk_size": 1000,
                "chunk_overlap": 200,
            })
            return result

    return asyncio.run(_do_index())


def main():
    logger.info("=== Platform Knowledge Indexer ===")

    wait_for_service(VECTORSTORE_URL, "module-vectorstore")

    all_docs = []
    all_docs.extend(collect_skills())
    all_docs.extend(collect_standards())
    all_docs.extend(collect_module_specs())
    all_docs.extend(collect_agent_definitions())
    all_docs.extend(collect_documentation())

    if not all_docs:
        logger.warning("No documents found to index")
        return

    logger.info("Collected %d documents total", len(all_docs))

    batch_size = 20
    total_chunks = 0

    for i in range(0, len(all_docs), batch_size):
        batch = all_docs[i:i + batch_size]
        logger.info("Indexing batch %d-%d of %d...", i + 1, min(i + batch_size, len(all_docs)), len(all_docs))
        try:
            result = index_documents(batch)
            if isinstance(result, list) and len(result) > 0:
                first = result[0]
                if hasattr(first, "text"):
                    import json
                    data = json.loads(first.text)
                    total_chunks += data.get("chunks_created", 0)
                    logger.info("  Indexed: %d docs, %d chunks", data.get("documents_indexed", 0), data.get("chunks_created", 0))
        except Exception as e:
            logger.error("Failed to index batch: %s", e)
            raise

    logger.info("=== Platform knowledge indexed: %d documents, %d chunks ===", len(all_docs), total_chunks)


if __name__ == "__main__":
    main()
