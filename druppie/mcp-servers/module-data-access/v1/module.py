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

        Format: DATA_SOURCE_1=type:name:config_blob

        Only the type and name are split off the front (split(":", 2)); the
        remaining config_blob keeps every internal colon. This matters for
        Azure SQL — connection strings contain colons (e.g. Server=tcp:host)
        that a naive split would shred.

        Azure Data Lake: azure-datalake:name:account_name[:key]
        Azure SQL (conn string): azure-sql:name:connection_string
        Azure SQL (OBO): azure-sql-obo:name:tenant:client:secret:scope:server:database
        """
        for i in range(1, 10):
            config_str = os.getenv(f"DATA_SOURCE_{i}")
            if not config_str:
                continue

            try:
                head = config_str.split(":", 2)
                if len(head) < 3:
                    raise ValueError(
                        "expected 'type:name:config_blob' (at least 3 "
                        "colon-separated parts)"
                    )
                source_type, name, config_blob = head

                if source_type == "azure-datalake":
                    # config_blob is account_name[:key]; neither contains a
                    # colon, so a single maxsplit recovers both.
                    dl_parts = config_blob.split(":", 1)
                    config = {
                        "source_id": name,
                        "name": name,
                        "account_name": dl_parts[0],
                        "key": dl_parts[1] if len(dl_parts) > 1 else None,
                    }
                    adapter = AzureDataLakeAdapter(config)

                elif source_type == "azure-sql":
                    # config_blob is the full ODBC connection string,
                    # colons and all.
                    config = {
                        "source_id": name,
                        "name": name,
                        "connection_string": config_blob,
                    }
                    adapter = AzureSQLAdapter(config)

                elif source_type == "azure-sql-obo":
                    # Reads Entra credentials from ENTRA_* env vars (shared
                    # with the Keycloak broker). Config blob only carries
                    # scope:server:database.
                    entra_tenant = os.getenv("ENTRA_TENANT_ID", "")
                    entra_client = os.getenv("ENTRA_CLIENT_ID", "")
                    entra_secret = os.getenv("ENTRA_CLIENT_SECRET", "")
                    if not all([entra_tenant, entra_client, entra_secret]):
                        raise ValueError(
                            "azure-sql-obo requires ENTRA_TENANT_ID, "
                            "ENTRA_CLIENT_ID and ENTRA_CLIENT_SECRET env vars"
                        )
                    obo = config_blob.rsplit(":", 2)
                    if len(obo) < 3:
                        raise ValueError(
                            "azure-sql-obo expects scope:server:database"
                        )
                    config = {
                        "source_id": name,
                        "name": name,
                        "use_obo": True,
                        "obo_config": {
                            "tenant_id": entra_tenant,
                            "client_id": entra_client,
                            "client_secret": entra_secret,
                            "scope": obo[0],
                            "server": obo[1],
                            "database": obo[2],
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
                "detail": info.detail,
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

    async def test_connection(self, source_id: str, user_token: str | None = None) -> dict:
        """Test connection to a data source."""
        try:
            adapter = self.get_adapter(source_id)
            if isinstance(adapter, AzureSQLAdapter):
                return await adapter.test_connection(user_token=user_token)
            return await adapter.test_connection()
        except ValueError as e:
            return {"success": False, "error": str(e)}

    async def list_available_data(
        self,
        source_id: str,
        path: str = "",
        recursive: bool = False,
        user_token: str | None = None,
    ) -> dict:
        """List available data in a source."""
        try:
            adapter = self.get_adapter(source_id)
            if isinstance(adapter, AzureSQLAdapter):
                return await adapter.list_available_data(path, recursive, user_token=user_token)
            return await adapter.list_available_data(path, recursive)
        except ValueError as e:
            return {"success": False, "error": str(e)}

    async def get_schema(self, source_id: str, data_id: str, user_token: str | None = None) -> dict:
        """Get schema for a data item."""
        try:
            adapter = self.get_adapter(source_id)
            if isinstance(adapter, AzureSQLAdapter):
                result = await adapter.get_schema(data_id, user_token=user_token)
            else:
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
        user_token: str | None = None,
    ) -> dict:
        """Read data from a source."""
        try:
            adapter = self.get_adapter(source_id)
            if isinstance(adapter, AzureSQLAdapter):
                return await adapter.read_data(data_id, filter_expr, limit, offset, user_token=user_token)
            return await adapter.read_data(data_id, filter_expr, limit, offset)
        except ValueError as e:
            return {"success": False, "error": str(e)}

    async def execute_query(
        self,
        source_id: str,
        query: str,
        limit: int | None = None,
        user_token: str | None = None,
    ) -> dict:
        """Run a free-form read-only query against a SQL source."""
        try:
            adapter = self.get_adapter(source_id)
            if isinstance(adapter, AzureSQLAdapter):
                return await adapter.execute_query(query, limit, user_token=user_token)
            return await adapter.execute_query(query, limit)
        except ValueError as e:
            return {"success": False, "error": str(e)}

    async def download_data(
        self,
        source_id: str,
        data_id: str,
        destination_path: str,
        user_token: str | None = None,
    ) -> dict:
        """Download data from a source."""
        try:
            adapter = self.get_adapter(source_id)
            if isinstance(adapter, AzureSQLAdapter):
                return await adapter.download_data(data_id, destination_path, user_token=user_token)
            return await adapter.download_data(data_id, destination_path)
        except ValueError as e:
            return {"success": False, "error": str(e)}
