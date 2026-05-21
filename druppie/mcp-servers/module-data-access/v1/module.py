"""Data access module - orchestrates data source adapters."""

import logging
import os
from typing import Any

from .adapter import BaseDataSourceAdapter
from .adapter.azure_datalake import AzureDataLakeAdapter
from .adapter.azure_sql import AzureSQLAdapter

logger = logging.getLogger("dataaccess-mcp")


class DataAccessModule:
    """Main module for data access operations.

    Manages multiple data source adapters and routes operations to the
    appropriate adapter based on source_id.
    """

    def __init__(self):
        self._adapters: dict[str, BaseDataSourceAdapter] = {}
        self._load_data_sources()

    def _load_data_sources(self):
        """Load data sources from environment variables.

        Format: DATA_SOURCE_1=type:name:config_parts...

        Azure Data Lake: azure-datalake:name:account_name:key
        Azure SQL (conn string): azure-sql:name:connection_string
        Azure SQL (OBO): azure-sql-obo:name:tenant_id:client_id:client_secret:scope:server:database
        """
        for i in range(1, 10):
            config_str = os.getenv(f"DATA_SOURCE_{i}")
            if not config_str:
                continue

            try:
                parts = config_str.split(":")
                source_type = parts[0]
                name = parts[1]

                if source_type == "azure-datalake":
                    config = {
                        "source_id": name,
                        "name": name,
                        "account_name": parts[2],
                        "key": parts[3] if len(parts) > 3 else None,
                    }
                    adapter = AzureDataLakeAdapter(config)

                elif source_type == "azure-sql":
                    config = {
                        "source_id": name,
                        "name": name,
                        "connection_string": parts[2],
                    }
                    adapter = AzureSQLAdapter(config)

                elif source_type == "azure-sql-obo":
                    config = {
                        "source_id": name,
                        "name": name,
                        "use_obo": True,
                        "obo_config": {
                            "tenant_id": parts[2],
                            "client_id": parts[3],
                            "client_secret": parts[4],
                            "scope": parts[5],
                            "server": parts[6],
                            "database": parts[7],
                        },
                    }
                    adapter = AzureSQLAdapter(config)

                else:
                    logger.warning(f"Unknown data source type: {source_type}")
                    continue

                self._adapters[name] = adapter
                logger.info(f"Loaded data source: {name} ({source_type})")

            except (IndexError, ValueError) as e:
                logger.error(f"Invalid DATA_SOURCE_{i} format: {e}")

    def list_sources(self) -> dict:
        """List all configured data sources."""
        sources = []
        for adapter in self._adapters.values():
            info = adapter.source_info
            sources.append({
                "source_id": info.source_id,
                "source_type": info.source_type,
                "name": info.name,
                "auth_type": info.auth_type,
            })

        return {
            "success": True,
            "sources": sources,
            "count": len(sources),
        }

    def get_adapter(self, source_id: str) -> BaseDataSourceAdapter:
        """Get adapter by source_id."""
        adapter = self._adapters.get(source_id)
        if not adapter:
            raise ValueError(f"Unknown data source: {source_id}")
        return adapter

    async def test_connection(self, source_id: str) -> dict:
        """Test connection to a data source."""
        try:
            adapter = self.get_adapter(source_id)
            return await adapter.test_connection()
        except ValueError as e:
            return {"success": False, "error": str(e)}

    async def list_available_data(
        self,
        source_id: str,
        path: str = "",
        recursive: bool = False,
    ) -> dict:
        """List available data in a source."""
        try:
            adapter = self.get_adapter(source_id)
            return await adapter.list_available_data(path, recursive)
        except ValueError as e:
            return {"success": False, "error": str(e)}

    async def get_schema(self, source_id: str, data_id: str) -> dict:
        """Get schema for a data item."""
        try:
            adapter = self.get_adapter(source_id)
            result = await adapter.get_schema(data_id)
            if result.get("success") and "schema" in result:
                result["schema"] = {
                    "columns": result["schema"].columns,
                    "metadata": result["schema"].metadata,
                }
            return result
        except ValueError as e:
            return {"success": False, "error": str(e)}

    async def read_data(
        self,
        source_id: str,
        data_id: str,
        filter_expr: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> dict:
        """Read data from a source."""
        try:
            adapter = self.get_adapter(source_id)
            return await adapter.read_data(data_id, filter_expr, limit, offset)
        except ValueError as e:
            return {"success": False, "error": str(e)}

    async def download_data(
        self,
        source_id: str,
        data_id: str,
        destination_path: str,
    ) -> dict:
        """Download data from a source."""
        try:
            adapter = self.get_adapter(source_id)
            return await adapter.download_data(data_id, destination_path)
        except ValueError as e:
            return {"success": False, "error": str(e)}