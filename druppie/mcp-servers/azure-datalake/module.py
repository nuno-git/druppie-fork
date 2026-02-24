"""Azure Data Lake MCP Server - Business Logic Module.

Contains all business logic for Azure Data Lake Gen2 read operations.
Supports both pre-configured lakes (with keys) and ad-hoc public lakes.
"""

import io
import logging
from typing import Any

from azure.storage.filedatalake import DataLakeServiceClient
from azure.core.exceptions import AzureError
import pandas as pd
import pyarrow.parquet as pq

logger = logging.getLogger("azure-datalake-mcp")


class AzureDataLakeModule:
    """Business logic module for Azure Data Lake operations.

    Supports two access modes:
    1. Pre-configured lakes: Defined in environment variables with account keys
    2. Ad-hoc public lakes: User provides URL, uses anonymous access
    """

    def __init__(self, datalake_configs: dict[str, dict]):
        """Initialize with pre-configured lake definitions.

        Args:
            datalake_configs: Dict mapping lake names to their config
                {"lake_name": {"account_name": "...", "key": "..."}}
        """
        self.datalake_configs = datalake_configs
        self._clients: dict[str, DataLakeServiceClient] = {}

    def _get_client_by_name(self, lake_name: str) -> DataLakeServiceClient:
        """Get or create DataLakeServiceClient for a pre-configured lake."""
        if lake_name in self._clients:
            return self._clients[lake_name]

        config = self.datalake_configs.get(lake_name)
        if not config:
            raise ValueError(f"Unknown Data Lake: {lake_name}")

        account_url = f"https://{config['account_name']}.dfs.core.windows.net"
        client = DataLakeServiceClient(
            account_url=account_url,
            credential=config["key"],
        )
        self._clients[lake_name] = client
        return client

    def _get_client_by_url(self, account_url: str) -> DataLakeServiceClient:
        """Get DataLakeServiceClient for a public lake (anonymous access)."""
        # Normalize URL
        if not account_url.startswith("https://"):
            account_url = f"https://{account_url}"

        # Public/anonymous access - no credential
        client = DataLakeServiceClient(
            account_url=account_url,
            credential=None,  # Anonymous access
        )
        return client

    def _resolve_client(
        self, lake_name: str | None = None, account_url: str | None = None
    ) -> tuple[DataLakeServiceClient, str]:
        """Resolve client from either lake_name or account_url.

        Returns:
            Tuple of (client, source_identifier) where source_identifier
            is either the lake_name or account_url for logging purposes.
        """
        if lake_name:
            return self._get_client_by_name(lake_name), lake_name
        elif account_url:
            return self._get_client_by_url(account_url), account_url
        else:
            raise ValueError("Either lake_name or account_url must be provided")

    def list_datalakes(self) -> dict:
        """List all pre-configured Data Lakes.

        Note: This only shows pre-configured lakes. Public lakes are accessed
        ad-hoc via account_url parameter in other tools.
        """
        lakes = []
        for name, config in self.datalake_configs.items():
            lakes.append({
                "name": name,
                "account_name": config["account_name"],
                "type": "pre-configured",
                # Don't expose the key
            })
        return {
            "success": True,
            "datalakes": lakes,
            "count": len(lakes),
            "note": "Public lakes can be accessed ad-hoc via account_url parameter",
        }

    async def test_connection(
        self,
        lake_name: str | None = None,
        account_url: str | None = None,
    ) -> dict:
        """Test connection to a Data Lake.

        Args:
            lake_name: Name of pre-configured lake (uses stored key)
            account_url: Full URL to public lake (anonymous access)
        """
        try:
            client, source = self._resolve_client(lake_name, account_url)
            # Try to list file systems (containers)
            containers = list(client.list_file_systems())
            return {
                "success": True,
                "source": source,
                "access_type": "pre-configured" if lake_name else "public",
                "container_count": len(containers),
                "message": f"Successfully connected to {source}",
            }
        except AzureError as e:
            return {
                "success": False,
                "source": lake_name or account_url,
                "error": f"Azure error: {e.message}",
                "error_code": getattr(e, 'status_code', None),
            }
        except ValueError as e:
            return {
                "success": False,
                "error": str(e),
            }
        except Exception as e:
            return {
                "success": False,
                "source": lake_name or account_url,
                "error": str(e),
            }

    async def list_containers(
        self,
        lake_name: str | None = None,
        account_url: str | None = None,
    ) -> dict:
        """List containers (file systems) in a Data Lake.

        Args:
            lake_name: Name of pre-configured lake
            account_url: Full URL to public lake
        """
        try:
            client, source = self._resolve_client(lake_name, account_url)
            containers = []
            for fs in client.list_file_systems():
                containers.append({
                    "name": fs.name,
                    "last_modified": fs.last_modified.isoformat() if fs.last_modified else None,
                })
            return {
                "success": True,
                "source": source,
                "access_type": "pre-configured" if lake_name else "public",
                "containers": containers,
                "count": len(containers),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def list_paths(
        self,
        container: str,
        lake_name: str | None = None,
        account_url: str | None = None,
        path: str = "",
        recursive: bool = False,
    ) -> dict:
        """List paths in a container.

        Args:
            container: Container/file system name
            lake_name: Name of pre-configured lake
            account_url: Full URL to public lake
            path: Path within container (default: root)
            recursive: List recursively (default: false)
        """
        try:
            client, source = self._resolve_client(lake_name, account_url)
            fs_client = client.get_file_system_client(container)

            paths = []
            for path_item in fs_client.get_paths(path=path, recursive=recursive):
                paths.append({
                    "name": path_item.name,
                    "is_directory": path_item.is_directory,
                    "size": path_item.content_length if not path_item.is_directory else 0,
                    "last_modified": path_item.last_modified.isoformat() if path_item.last_modified else None,
                })

            return {
                "success": True,
                "source": source,
                "access_type": "pre-configured" if lake_name else "public",
                "container": container,
                "path": path or "/",
                "recursive": recursive,
                "paths": paths,
                "count": len(paths),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def read_file(
        self,
        container: str,
        path: str,
        lake_name: str | None = None,
        account_url: str | None = None,
        max_rows: int = 1000,
    ) -> dict:
        """Read a CSV or Parquet file.

        Args:
            container: Container/file system name
            path: Path to the file
            lake_name: Name of pre-configured lake
            account_url: Full URL to public lake
            max_rows: Maximum rows to return (default: 1000)
        """
        try:
            client, source = self._resolve_client(lake_name, account_url)
            file_client = client.get_file_client(container, path)

            # Download file content
            download = file_client.download_file()
            content = download.readall()

            # Detect file type and parse
            path_lower = path.lower()
            if path_lower.endswith(".parquet"):
                df = pd.read_parquet(io.BytesIO(content))
            elif path_lower.endswith(".csv"):
                df = pd.read_csv(io.BytesIO(content), nrows=max_rows)
            else:
                return {
                    "success": False,
                    "error": f"Unsupported file type: {path}. Supported: .csv, .parquet",
                }

            # Limit rows for parquet too
            truncated = False
            if len(df) > max_rows:
                df = df.head(max_rows)
                truncated = True

            return {
                "success": True,
                "source": source,
                "access_type": "pre-configured" if lake_name else "public",
                "container": container,
                "path": path,
                "file_type": "parquet" if path_lower.endswith(".parquet") else "csv",
                "schema": {col: str(dtype) for col, dtype in df.dtypes.items()},
                "columns": list(df.columns),
                "row_count": len(df),
                "truncated": truncated,
                "max_rows": max_rows,
                "data": df.to_dict(orient="records"),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def read_file_schema(
        self,
        container: str,
        path: str,
        lake_name: str | None = None,
        account_url: str | None = None,
    ) -> dict:
        """Read only the schema of a file (no data rows).

        Args:
            container: Container/file system name
            path: Path to the file
            lake_name: Name of pre-configured lake
            account_url: Full URL to public lake
        """
        try:
            client, source = self._resolve_client(lake_name, account_url)
            file_client = client.get_file_client(container, path)

            path_lower = path.lower()
            if path_lower.endswith(".parquet"):
                # Read minimal amount for schema
                download = file_client.download_file(max_concurrency=1)
                content = download.readall()
                pf = pq.ParquetFile(io.BytesIO(content))
                schema = pf.schema_arrow

                return {
                    "success": True,
                    "source": source,
                    "access_type": "pre-configured" if lake_name else "public",
                    "container": container,
                    "path": path,
                    "file_type": "parquet",
                    "schema": {field.name: str(field.type) for field in schema},
                    "columns": [field.name for field in schema],
                    "num_rows": pf.metadata.num_rows if pf.metadata else None,
                }
            elif path_lower.endswith(".csv"):
                # Read just header
                download = file_client.download_file(max_concurrency=1)
                content = download.readall()
                df = pd.read_csv(io.BytesIO(content), nrows=0)

                return {
                    "success": True,
                    "source": source,
                    "access_type": "pre-configured" if lake_name else "public",
                    "container": container,
                    "path": path,
                    "file_type": "csv",
                    "schema": {col: str(dtype) for col, dtype in df.dtypes.items()},
                    "columns": list(df.columns),
                }
            else:
                return {
                    "success": False,
                    "error": f"Unsupported file type: {path}. Supported: .csv, .parquet",
                }
        except Exception as e:
            return {"success": False, "error": str(e)}
