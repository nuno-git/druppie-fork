"""Azure Data Lake MCP Server.

Read-only operations for Azure Data Lake Storage Gen2.
Supports both pre-configured lakes (with keys) and ad-hoc public lakes.
Uses FastMCP framework for HTTP transport.
"""

import logging
import os

from fastmcp import FastMCP
from module import AzureDataLakeModule

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("azure-datalake-mcp")

# Initialize FastMCP server
mcp = FastMCP("Azure Data Lake MCP Server")

# Parse pre-configured lake configs from environment variables
# Format: AZURE_DATA_LAKE_1=account_name:key  (name defaults to account_name)
#     or: AZURE_DATA_LAKE_1=name:account_name:key
DATALAKE_CONFIGS = {}
for i in range(1, 10):
    config = os.getenv(f"AZURE_DATA_LAKE_{i}")
    if config:
        parts = config.split(":", 2)  # Split into at most 3 parts (key may contain colons)
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


if __name__ == "__main__":
    import uvicorn
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    app = mcp.http_app()

    async def health(request):
        """Health check endpoint."""
        return JSONResponse({
            "status": "healthy",
            "service": "azure-datalake-mcp",
            "configured_lakes": len(DATALAKE_CONFIGS),
        })

    app.routes.insert(0, Route("/health", health, methods=["GET"]))

    port = int(os.getenv("MCP_PORT", "9006"))
    logger.info(f"Starting Azure Data Lake MCP Server on port {port}")

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        log_level="info",
    )
