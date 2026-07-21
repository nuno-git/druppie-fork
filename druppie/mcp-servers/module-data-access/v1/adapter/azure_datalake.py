"""Azure Data Lake adapter for the data access MCP module."""

import io
import logging
from typing import Any

from azure.storage.filedatalake import DataLakeServiceClient
from azure.core.exceptions import AzureError
import pandas as pd
import pyarrow.parquet as pq

from .base import BaseDataSourceAdapter, DataSourceInfo, DataItem, SchemaInfo

logger = logging.getLogger("dataaccess-mcp")


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
            detail=f"{self.account_name}.dfs.core.windows.net",
        )

    async def list_available_data(
        self,
        path: str = "",
        recursive: bool = False,
        user_token: str | None = None,
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

    async def get_schema(self, data_id: str, user_token: str | None = None) -> dict:
        """Get schema for a Parquet or CSV file."""
        try:
            container, file_path = self._parse_path(data_id)
            file_client = self._client.get_file_client(container, file_path)
            file_type = self._get_file_type(file_path)

            if file_type == "parquet":
                download = file_client.download_file(max_concurrency=1)
                content = download.readall()
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
                # Only the header row is needed for schema — range-read
                # 64 KB instead of downloading multi-GB files.
                download = file_client.download_file(offset=0, length=64 * 1024)
                content = download.readall()
                last_newline = content.rfind(b"\n")
                if last_newline > 0:
                    content = content[: last_newline + 1]
                # utf-8-sig strips a leading BOM so the first column name
                # doesn't come back as "\ufeff<name>".
                df = pd.read_csv(
                    io.BytesIO(content),
                    nrows=0,
                    on_bad_lines="skip",
                    encoding="utf-8-sig",
                )
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
        user_token: str | None = None,
    ) -> dict:
        """Read data from a CSV or Parquet file."""
        try:
            container, file_path = self._parse_path(data_id)
            file_client = self._client.get_file_client(container, file_path)
            file_type = self._get_file_type(file_path)

            if file_type not in ("csv", "parquet"):
                return {
                    "success": False,
                    "error": f"Unsupported file type: {file_path}. Supported: .csv, .parquet",
                }

            warnings: list[str] = []
            skipped_rows = 0

            # Optimisation: when the caller only needs a handful of rows
            # from a CSV and there is no server-side filter, stream just
            # the head of the file instead of downloading the whole blob.
            # This turns a multi-GB download into a few-MB range read.
            can_stream = (
                file_type == "csv"
                and limit is not None
                and not filter_expr
            )

            if can_stream:
                df, warnings = await self._read_csv_head(
                    file_client, limit, offset,
                )
            else:
                download = file_client.download_file()
                content = download.readall()

                if file_type == "parquet":
                    df = pd.read_parquet(io.BytesIO(content))
                else:
                    # Tolerate malformed rows (mismatched field counts) so a
                    # single bad line doesn't fail the whole read. Real-world
                    # data lake CSVs often have embedded delimiters or stray
                    # rows; surfacing them as errors blocks all discovery.
                    # utf-8-sig strips any leading BOM.
                    df = pd.read_csv(
                        io.BytesIO(content),
                        on_bad_lines="skip",
                        encoding="utf-8-sig",
                    )
                    # Count rows pandas skipped so the caller can see that
                    # the source CSV is malformed.
                    total_lines = content.count(b"\n")
                    expected_data_rows = max(0, total_lines - 1)
                    skipped_rows = max(0, expected_data_rows - len(df))
                    if skipped_rows > 0:
                        warnings.append(
                            f"Skipped {skipped_rows} malformed row(s) in source CSV — "
                            f"field count did not match the {len(df.columns)}-column header. "
                            "Common cause: unquoted commas in free-text columns at the source."
                        )

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
                "warnings": warnings,
                "metadata": {
                    "file_type": file_type,
                    "filtered": filter_expr is not None,
                    "limited": limit is not None,
                    "offset": offset,
                    "skipped_rows": skipped_rows,
                },
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _read_csv_head(
        self,
        file_client,
        limit: int,
        offset: int | None = None,
    ) -> tuple[pd.DataFrame, list[str]]:
        """Read the first rows of a CSV via an Azure range-read.

        Downloads only enough bytes to satisfy *limit* (+ *offset*) rows,
        avoiding multi-GB transfers when the agent only needs a small sample.
        """
        rows_needed = limit + (offset or 0)
        warnings: list[str] = []

        # Heuristic: ~2 KB per row covers most enterprise CSVs.
        # Floor at 1 MB so the header + a few rows always fit.
        chunk_size = max(1 * 1024 * 1024, rows_needed * 2048)
        max_bytes = 50 * 1024 * 1024  # safety cap

        chunk_size = min(chunk_size, max_bytes)

        while True:
            download = file_client.download_file(offset=0, length=chunk_size)
            content = download.readall()
            is_complete = len(content) < chunk_size

            # Trim to last complete line so a range-read that cuts
            # mid-row (or mid-quoted-field) doesn't cause a parse error.
            if not is_complete:
                last_newline = content.rfind(b"\n")
                if last_newline > 0:
                    content = content[: last_newline + 1]

            df = pd.read_csv(
                io.BytesIO(content),
                nrows=rows_needed,
                on_bad_lines="skip",
                encoding="utf-8-sig",
            )

            if len(df) >= rows_needed or is_complete:
                break

            # Not enough rows in this chunk — double and retry
            if chunk_size >= max_bytes:
                warnings.append(
                    f"Streamed first {chunk_size // (1024 * 1024)} MB but only "
                    f"found {len(df)} rows (requested {rows_needed}). "
                    "The file may have very wide rows or many malformed lines."
                )
                break

            chunk_size = min(chunk_size * 2, max_bytes)

        # Apply offset and limit on the parsed subset
        if offset is not None:
            df = df.iloc[offset:]
        df = df.head(limit)

        return df, warnings

    async def download_data(
        self,
        data_id: str,
        destination_path: str,
        user_token: str | None = None,
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