"""Azure Data Lake adapter for the data access MCP module."""

import io
import logging
from typing import Any

from azure.storage.filedatalake import DataLakeServiceClient
from azure.core.exceptions import AzureError
import pandas as pd
import pyarrow.parquet as pq

from .base import BaseDataSourceAdapter, DataSourceInfo, DataItem, SchemaInfo

logger = logging.getLogger("data-access-mcp")


class AzureDataLakeAdapter(BaseDataSourceAdapter):
    """Adapter for Azure Data Lake Storage Gen2.

    Supports:
    - Pre-configured lakes (with keys)
    - Ad-hoc public lakes (anonymous access)
    """

    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        self.account_name = config["account_name"]
        self.key = config.get("key")
        self.is_public = self.key is None

        account_url = f"https://{self.account_name}.dfs.core.windows.net"
        if self.is_public:
            self._client = DataLakeServiceClient(account_url=account_url, credential=None)
        else:
            self._client = DataLakeServiceClient(account_url=account_url, credential=self.key)

    @property
    def source_info(self) -> DataSourceInfo:
        return DataSourceInfo(
            source_id=self.config.get("source_id", f"azure-datalake-{self.account_name}"),
            source_type="azure-datalake",
            name=self.config.get("name", self.account_name),
            auth_type="public" if self.is_public else "key",
        )

    async def list_available_data(
        self,
        path: str = "",
        recursive: bool = False,
    ) -> dict:
        """List containers and files in the Data Lake."""
        try:
            if not path:
                containers = []
                for fs in self._client.list_file_systems():
                    containers.append(DataItem(
                        item_id=f"{fs.name}/",
                        name=fs.name,
                        type="container",
                        metadata={"last_modified": fs.last_modified.isoformat() if fs.last_modified else None},
                    ))
                return {
                    "success": True,
                    "data_items": [self._data_item_to_dict(item) for item in containers],
                    "count": len(containers),
                    "level": "containers",
                }

            container, file_path = self._parse_path(path)
            fs_client = self._client.get_file_system_client(container)

            data_items = []
            for path_item in fs_client.get_paths(path=file_path, recursive=recursive):
                if path_item.name.endswith("/"):
                    continue

                data_items.append(DataItem(
                    item_id=f"{container}/{path_item.name}",
                    name=path_item.name,
                    type="file",
                    metadata={
                        "is_directory": path_item.is_directory,
                        "size": path_item.content_length,
                        "last_modified": path_item.last_modified.isoformat() if path_item.last_modified else None,
                        "file_type": self._get_file_type(path_item.name),
                    },
                ))

            return {
                "success": True,
                "data_items": [self._data_item_to_dict(item) for item in data_items],
                "count": len(data_items),
                "level": "files",
                "container": container,
                "path": file_path or "/",
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def get_schema(self, data_id: str) -> dict:
        """Get schema for a Parquet or CSV file."""
        try:
            container, file_path = self._parse_path(data_id)
            file_client = self._client.get_file_client(container, file_path)

            download = file_client.download_file(max_concurrency=1)
            content = download.readall()

            file_type = self._get_file_type(file_path)

            if file_type == "parquet":
                pf = pq.ParquetFile(io.BytesIO(content))
                schema = pf.schema_arrow
                columns = [{"name": field.name, "type": str(field.type)} for field in schema]
                return {
                    "success": True,
                    "schema": SchemaInfo(
                        columns=columns,
                        metadata={
                            "file_type": "parquet",
                            "num_rows": pf.metadata.num_rows if pf.metadata else None,
                        },
                    ),
                }
            elif file_type == "csv":
                df = pd.read_csv(io.BytesIO(content), nrows=0)
                columns = [{"name": col, "type": str(dtype)} for col, dtype in df.dtypes.items()]
                return {
                    "success": True,
                    "schema": SchemaInfo(
                        columns=columns,
                        metadata={"file_type": "csv"},
                    ),
                }
            else:
                return {
                    "success": False,
                    "error": f"Unsupported file type: {file_path}. Supported: .csv, .parquet",
                }
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def read_data(
        self,
        data_id: str,
        filter_expr: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> dict:
        """Read data from a CSV or Parquet file."""
        try:
            container, file_path = self._parse_path(data_id)
            file_client = self._client.get_file_client(container, file_path)

            download = file_client.download_file()
            content = download.readall()

            file_type = self._get_file_type(file_path)

            if file_type == "parquet":
                df = pd.read_parquet(io.BytesIO(content))
            elif file_type == "csv":
                df = pd.read_csv(io.BytesIO(content))
            else:
                return {
                    "success": False,
                    "error": f"Unsupported file type: {file_path}. Supported: .csv, .parquet",
                }

            if filter_expr:
                df = df.query(filter_expr)

            if offset is not None:
                df = df.iloc[offset:]

            if limit is not None:
                df = df.head(limit)

            return {
                "success": True,
                "data": df.to_dict(orient="records"),
                "row_count": len(df),
                "columns": list(df.columns),
                "metadata": {
                    "file_type": file_type,
                    "filtered": filter_expr is not None,
                    "limited": limit is not None,
                    "offset": offset,
                },
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def download_data(
        self,
        data_id: str,
        destination_path: str,
    ) -> dict:
        """Download a file from Data Lake."""
        try:
            container, file_path = self._parse_path(data_id)
            file_client = self._client.get_file_client(container, file_path)

            download = file_client.download_file()
            content = download.readall()

            with open(destination_path, "wb") as f:
                f.write(content)

            return {
                "success": True,
                "destination": destination_path,
                "size_bytes": len(content),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _parse_path(self, path: str) -> tuple[str, str]:
        """Parse path into (container, file_path)."""
        parts = path.split("/", 1)
        return parts[0], parts[1] if len(parts) > 1 else ""

    def _get_file_type(self, path: str) -> str | None:
        """Determine file type from path."""
        path_lower = path.lower()
        if path_lower.endswith(".parquet"):
            return "parquet"
        elif path_lower.endswith(".csv"):
            return "csv"
        return None

    @staticmethod
    def _data_item_to_dict(item: DataItem) -> dict:
        """Convert DataItem to dict."""
        return {
            "item_id": item.item_id,
            "name": item.name,
            "type": item.type,
            "metadata": item.metadata,
        }

    @staticmethod
    def _schema_info_to_dict(schema: SchemaInfo) -> dict:
        """Convert SchemaInfo to dict."""
        return {
            "columns": schema.columns,
            "metadata": schema.metadata,
        }