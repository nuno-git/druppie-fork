"""Azure Data Lake MCP Server - Business Logic Module.

Contains all business logic for Azure Data Lake Gen2 read operations.
Supports both pre-configured lakes (with keys) and ad-hoc public lakes.
"""

import io
import logging
from pathlib import Path
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
        if not account_url.startswith("https://"):
            account_url = f"https://{account_url}"

        client = DataLakeServiceClient(
            account_url=account_url,
            credential=None,
        )
        return client

    def _resolve_client(
        self, lake_name: str | None = None, account_url: str | None = None
    ) -> tuple[DataLakeServiceClient, str]:
        """Resolve client from either lake_name or account_url."""
        if lake_name:
            return self._get_client_by_name(lake_name), lake_name
        elif account_url:
            return self._get_client_by_url(account_url), account_url
        else:
            raise ValueError("Either lake_name or account_url must be provided")

    def list_datalakes(self) -> dict:
        """List all pre-configured Data Lakes."""
        lakes = []
        for name, config in self.datalake_configs.items():
            lakes.append({
                "name": name,
                "account_name": config["account_name"],
                "type": "pre-configured",
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
        """Test connection to a Data Lake."""
        try:
            client, source = self._resolve_client(lake_name, account_url)
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
        """List containers (file systems) in a Data Lake."""
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
        """List paths in a container."""
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
        """Read a CSV or Parquet file."""
        try:
            client, source = self._resolve_client(lake_name, account_url)
            file_client = client.get_file_client(container, path)

            download = file_client.download_file()
            content = download.readall()

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
        """Read only the schema of a file (no data rows)."""
        try:
            client, source = self._resolve_client(lake_name, account_url)
            file_client = client.get_file_client(container, path)

            path_lower = path.lower()
            if path_lower.endswith(".parquet"):
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

    async def download_file(
        self,
        container: str,
        path: str,
        destination_path: Path,
        lake_name: str | None = None,
        account_url: str | None = None,
    ) -> dict:
        """Download a file from Data Lake and save it to a local path."""
        try:
            client, source = self._resolve_client(lake_name, account_url)
            file_client = client.get_file_client(container, path)

            download = file_client.download_file()
            content = download.readall()

            destination_path.parent.mkdir(parents=True, exist_ok=True)
            destination_path.write_bytes(content)

            return {
                "success": True,
                "source": source,
                "access_type": "pre-configured" if lake_name else "public",
                "container": container,
                "path": path,
                "destination": str(destination_path),
                "size_bytes": len(content),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
