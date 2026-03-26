"""Azure Data Lake v1 — MCP Tool Definitions.

Single source of truth for tool contract:
- Tool name, description, input schema via @mcp.tool()
- Version and module_id via @mcp.tool(meta={...})
- Agent guidance via FastMCP(instructions=...)
"""

import logging
import os
from pathlib import Path

from fastmcp import FastMCP
from .module import AzureDataLakeModule

logger = logging.getLogger("azure-datalake-mcp")

MODULE_ID = "azure-datalake"
MODULE_VERSION = "1.0.0"

# Initialize FastMCP server
mcp = FastMCP(
    "Azure Data Lake v1",
    version=MODULE_VERSION,
    instructions="Read-only operations for Azure Data Lake Storage Gen2. Supports pre-configured lakes (with keys) and ad-hoc public lakes.",
)

# Parse pre-configured lake configs from environment variables
# Format: AZURE_DATA_LAKE_1=account_name:key  (name defaults to account_name)
#     or: AZURE_DATA_LAKE_1=name:account_name:key
DATALAKE_CONFIGS = {}
for i in range(1, 10):
    config = os.getenv(f"AZURE_DATA_LAKE_{i}")
    if config:
        parts = config.split(":", 2)
        if len(parts) >= 3:
            name, account_name, key = parts[0], parts[1], parts[2]
        elif len(parts) == 2:
            name, account_name, key = parts[0], parts[0], parts[1]
        else:
            logger.warning(f"Invalid AZURE_DATA_LAKE_{i} format. Expected account_name:key")
            continue
        DATALAKE_CONFIGS[name] = {
            "name": name,
            "account_name": account_name,
            "key": key,
        }
        logger.info(f"Loaded pre-configured lake: {name}")

logger.info(f"Loaded {len(DATALAKE_CONFIGS)} pre-configured lakes")

# Workspace root for file downloads (shared volume with coding MCP)
WORKSPACE_ROOT = Path(os.getenv("WORKSPACE_ROOT", "/workspaces"))

# Initialize business logic module
module = AzureDataLakeModule(datalake_configs=DATALAKE_CONFIGS)


@mcp.tool()
async def list_datalakes() -> dict:
    """List all pre-configured Azure Data Lakes.

    Call this FIRST to discover available lake names. Use the returned 'name'
    field as the lake_name parameter in all other azure-datalake tools.
    Authentication is handled automatically — never pass keys yourself.

    Returns:
        Dict with list of configured lakes (name, account_name).
        Public lakes can also be accessed ad-hoc via account_url in other tools.
    """
    return module.list_datalakes()


@mcp.tool()
async def test_connection(
    lake_name: str | None = None,
    account_url: str | None = None,
) -> dict:
    """Test connection to a Data Lake.

    You MUST provide either lake_name or account_url.
    For pre-configured lakes, pass lake_name (from list_datalakes) —
    authentication is injected automatically.
    For public lakes, pass account_url (e.g., https://account.blob.core.windows.net).

    Args:
        lake_name: Name from list_datalakes (authentication handled automatically)
        account_url: Full URL to a public lake (anonymous access)

    Returns:
        Dict with connection status and container count if successful.
    """
    return await module.test_connection(lake_name=lake_name, account_url=account_url)


@mcp.tool()
async def list_containers(
    lake_name: str | None = None,
    account_url: str | None = None,
) -> dict:
    """List containers (file systems) in a Data Lake.

    You MUST provide either lake_name or account_url.
    For pre-configured lakes, pass lake_name (from list_datalakes) —
    authentication is injected automatically.

    Args:
        lake_name: Name from list_datalakes (authentication handled automatically)
        account_url: Full URL to a public lake (anonymous access)

    Returns:
        Dict with list of containers (name, last_modified).
    """
    return await module.list_containers(lake_name=lake_name, account_url=account_url)


@mcp.tool()
async def list_paths(
    container: str,
    lake_name: str | None = None,
    account_url: str | None = None,
    path: str = "",
    recursive: bool = False,
) -> dict:
    """List files and directories in a container path.

    You MUST provide either lake_name or account_url.
    For pre-configured lakes, pass lake_name (from list_datalakes) —
    authentication is injected automatically.

    Args:
        container: Container/file system name (required)
        lake_name: Name from list_datalakes (authentication handled automatically)
        account_url: Full URL to a public lake (anonymous access)
        path: Path within container (default: root)
        recursive: List recursively (default: false)

    Returns:
        Dict with list of paths (name, is_directory, size, last_modified).
    """
    return await module.list_paths(
        container=container,
        lake_name=lake_name,
        account_url=account_url,
        path=path,
        recursive=recursive,
    )


@mcp.tool()
async def read_file(
    container: str,
    path: str,
    lake_name: str | None = None,
    account_url: str | None = None,
    max_rows: int = 1000,
) -> dict:
    """Read a CSV or Parquet file from Data Lake.

    You MUST provide either lake_name or account_url.
    For pre-configured lakes, pass lake_name (from list_datalakes) —
    authentication is injected automatically.

    Args:
        container: Container/file system name (required)
        path: Path to the file (required)
        lake_name: Name from list_datalakes (authentication handled automatically)
        account_url: Full URL to a public lake (anonymous access)
        max_rows: Maximum rows to return (default: 1000)

    Returns:
        Dict with schema, columns, row_count, and data (as records).
    """
    return await module.read_file(
        container=container,
        path=path,
        lake_name=lake_name,
        account_url=account_url,
        max_rows=max_rows,
    )


@mcp.tool()
async def read_file_schema(
    container: str,
    path: str,
    lake_name: str | None = None,
    account_url: str | None = None,
) -> dict:
    """Read only the schema/structure of a CSV or Parquet file.

    You MUST provide either lake_name or account_url.
    For pre-configured lakes, pass lake_name (from list_datalakes) —
    authentication is injected automatically.

    Args:
        container: Container/file system name (required)
        path: Path to the file (required)
        lake_name: Name from list_datalakes (authentication handled automatically)
        account_url: Full URL to a public lake (anonymous access)

    Returns:
        Dict with schema (column names and types) only, no data rows.
    """
    return await module.read_file_schema(
        container=container,
        path=path,
        lake_name=lake_name,
        account_url=account_url,
    )


@mcp.tool()
async def download_file(
    container: str,
    path: str,
    destination: str,
    session_id: str = "",
    project_id: str = "",
    lake_name: str | None = None,
    account_url: str | None = None,
) -> dict:
    """Download a file from Data Lake and save it to the project workspace.

    You MUST provide either lake_name or account_url.
    For pre-configured lakes, pass lake_name (from list_datalakes) —
    authentication is injected automatically.

    Args:
        container: Container/file system name (required)
        path: Source file path in the datalake (required)
        destination: Destination path relative to workspace root, e.g. data/myfile.parquet (required)
        session_id: Session ID (auto-injected by backend)
        project_id: Project ID (auto-injected by backend)
        lake_name: Name from list_datalakes (authentication handled automatically)
        account_url: Full URL to a public lake (anonymous access)

    Returns:
        Dict with download result including destination path and file size.
    """
    # Build workspace path: /workspaces/default/{project_id}/{session_id}/{destination}
    workspace_dir = WORKSPACE_ROOT / "default" / project_id / session_id
    destination_path = (workspace_dir / destination).resolve()

    # Path traversal guard: ensure resolved path stays under workspace directory
    try:
        destination_path.relative_to(workspace_dir.resolve())
    except ValueError:
        return {
            "success": False,
            "error": f"Invalid destination path: '{destination}' escapes the workspace directory",
        }

    return await module.download_file(
        container=container,
        path=path,
        destination_path=destination_path,
        lake_name=lake_name,
        account_url=account_url,
    )
