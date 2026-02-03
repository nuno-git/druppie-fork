"""Azure Data Lake Storage Gen2 MCP Server.

Provides tools to browse, read, and analyze data in ADLS Gen2.
Supports key-based authentication.
"""

import io
import json
import logging
import os
from typing import Any

import pandas as pd
import pyarrow.parquet as pq
import structlog
from azure.storage.filedatalake import DataLakeServiceClient
from fastmcp import FastMCP

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = structlog.get_logger("azure-datalake-mcp")

# Initialize FastMCP server
mcp = FastMCP("Azure Data Lake MCP Server")

# Configuration from environment
# User can provide either:
# 1. ADLS_URL (full endpoint like https://azureopendatastorage.dfs.core.windows.net)
# 2. ADLS_ACCOUNT_NAME (auto-constructs https://ACCOUNT_NAME.dfs.core.windows.net)
ADLS_URL = os.getenv("ADLS_URL", "")
ADLS_ACCOUNT_NAME = os.getenv("ADLS_ACCOUNT_NAME", "")

# Determine endpoint
if ADLS_URL:
    ADLS_ENDPOINT = ADLS_URL
elif ADLS_ACCOUNT_NAME:
    ADLS_ENDPOINT = f"https://{ADLS_ACCOUNT_NAME}.dfs.core.windows.net"
else:
    ADLS_ENDPOINT = ""

# Cache for client connection
_adls_client = None


def get_adls_client() -> DataLakeServiceClient:
    """Get or create ADLS client (cached) - public/anonymous access.
    
    Supports two configuration options:
    1. ADLS_URL=https://azureopendatastorage.dfs.core.windows.net
    2. ADLS_ACCOUNT_NAME=azureopendatastorage
    """
    global _adls_client
    if _adls_client is None:
        if not ADLS_ENDPOINT:
            raise ValueError(
                "Either ADLS_URL or ADLS_ACCOUNT_NAME environment variable required"
            )
        # Public access - no credential needed
        _adls_client = DataLakeServiceClient(
            account_url=ADLS_ENDPOINT,
        )
    return _adls_client


@mcp.tool()
async def list_containers() -> dict:
    """List all containers in the ADLS Gen2 account.

    Returns:
        Dict with containers list
    """
    try:
        client = get_adls_client()
        containers = []

        for container in client.list_file_systems():
            containers.append({
                "name": container["name"],
                "properties": {
                    "last_modified": str(container.get("last_modified", "")),
                },
            })

        logger.info("Listed containers", count=len(containers))
        return {
            "success": True,
            "containers": containers,
            "count": len(containers),
        }

    except Exception as e:
        logger.error("Error listing containers", error=str(e))
        return {"success": False, "error": str(e)}


@mcp.tool()
async def list_files(
    container: str,
    path: str = "/",
    recursive: bool = False,
) -> dict:
    """List files and directories in a container path.

    Args:
        container: Container name
        path: Path within container (default: "/")
        recursive: Whether to list recursively

    Returns:
        Dict with files and directories
    """
    try:
        client = get_adls_client()
        file_system = client.get_file_system_client(container)

        # Normalize path
        path = path.lstrip("/")
        if path and not path.endswith("/"):
            path += "/"

        files = []
        directories = []

        # List paths
        for item in file_system.get_paths(path, recursive=recursive):
            item_name = item.name.split("/")[-1]
            
            if item.is_directory:
                directories.append({
                    "name": item_name,
                    "path": item.name,
                    "type": "directory",
                })
            else:
                files.append({
                    "name": item_name,
                    "path": item.name,
                    "type": "file",
                    "size": item.content_length or 0,
                })

        logger.info(
            "Listed files",
            container=container,
            path=path,
            files=len(files),
            dirs=len(directories),
        )

        return {
            "success": True,
            "container": container,
            "path": path or "/",
            "files": files,
            "directories": directories,
            "count": len(files) + len(directories),
        }

    except Exception as e:
        logger.error("Error listing files", container=container, path=path, error=str(e))
        return {"success": False, "error": str(e)}


@mcp.tool()
async def read_file_sample(
    container: str,
    path: str,
    lines: int = 50,
) -> dict:
    """Read a sample (first N lines) of a file.

    Supports: CSV, JSON, TXT, Parquet (schema + sample rows).

    Args:
        container: Container name
        path: File path
        lines: Number of lines to read (default: 50)

    Returns:
        Dict with content, format, and metadata
    """
    try:
        client = get_adls_client()
        file_system = client.get_file_system_client(container)
        file_client = file_system.get_file_client(path)

        # Get file metadata
        properties = file_client.get_file_properties()
        size = properties.size

        logger.info("Reading file sample", container=container, path=path, size=size)

        # Determine format
        ext = path.lower().split(".")[-1]

        if ext == "parquet":
            # Read Parquet file (schema + sample rows)
            data = io.BytesIO()
            download = file_client.download_file()
            for chunk in download.chunks():
                data.write(chunk)
            data.seek(0)

            table = pq.read_table(data)
            schema = table.schema

            # Convert schema to dict
            schema_dict = []
            for field in schema:
                schema_dict.append({
                    "name": field.name,
                    "type": str(field.type),
                })

            # Get sample rows (as dicts)
            df = table.to_pandas()
            sample_rows = df.head(lines).to_dict("records")

            return {
                "success": True,
                "path": path,
                "format": "parquet",
                "size": size,
                "schema": schema_dict,
                "total_rows": len(df),
                "sample_rows": sample_rows,
            }

        elif ext == "csv":
            # Read CSV file
            data = io.BytesIO()
            download = file_client.download_file()
            for chunk in download.chunks():
                data.write(chunk)
            data.seek(0)

            df = pd.read_csv(data)

            schema_dict = [
                {"name": col, "type": str(df[col].dtype)}
                for col in df.columns
            ]

            sample_rows = df.head(lines).to_dict("records")

            return {
                "success": True,
                "path": path,
                "format": "csv",
                "size": size,
                "schema": schema_dict,
                "total_rows": len(df),
                "sample_rows": sample_rows,
            }

        elif ext == "json":
            # Read JSON file
            data = io.BytesIO()
            download = file_client.download_file()
            for chunk in download.chunks():
                data.write(chunk)
            data.seek(0)

            content = data.getvalue().decode("utf-8")
            
            # Try to parse as JSON
            try:
                parsed = json.loads(content)
                if isinstance(parsed, list):
                    sample = parsed[:lines]
                else:
                    sample = [parsed]
            except json.JSONDecodeError:
                sample = content.split("\n")[:lines]

            return {
                "success": True,
                "path": path,
                "format": "json",
                "size": size,
                "sample": sample,
            }

        else:
            # Read as text (first N lines)
            data = io.BytesIO()
            download = file_client.download_file()
            for chunk in download.chunks():
                data.write(chunk)
            data.seek(0)

            content = data.getvalue().decode("utf-8", errors="ignore")
            lines_list = content.split("\n")[:lines]

            return {
                "success": True,
                "path": path,
                "format": ext or "text",
                "size": size,
                "lines": lines_list,
            }

    except Exception as e:
        logger.error("Error reading file sample", container=container, path=path, error=str(e))
        return {"success": False, "error": str(e)}


@mcp.tool()
async def get_file_metadata(
    container: str,
    path: str,
) -> dict:
    """Get detailed metadata for a file.

    Args:
        container: Container name
        path: File path

    Returns:
        Dict with file metadata
    """
    try:
        client = get_adls_client()
        file_system = client.get_file_system_client(container)
        file_client = file_system.get_file_client(path)

        properties = file_client.get_file_properties()

        metadata = {
            "name": path.split("/")[-1],
            "path": path,
            "size": properties.size,
            "size_mb": round(properties.size / (1024 * 1024), 2),
            "created": str(properties.creation_time),
            "modified": str(properties.last_modified),
            "is_directory": properties.is_directory,
        }

        # Add custom metadata if available
        if hasattr(properties, "metadata") and properties.metadata:
            metadata["custom_metadata"] = properties.metadata

        logger.info("Got file metadata", container=container, path=path)

        return {
            "success": True,
            "metadata": metadata,
        }

    except Exception as e:
        logger.error("Error getting file metadata", container=container, path=path, error=str(e))
        return {"success": False, "error": str(e)}



if __name__ == "__main__":
    import uvicorn
    uvicorn.run(mcp.app, host="0.0.0.0", port=9003)
