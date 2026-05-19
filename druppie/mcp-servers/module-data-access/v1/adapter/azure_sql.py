"""Azure SQL adapter for the data access MCP module.

Supports OBO token authentication via Keycloak.
"""

import logging
from typing import Any

import pyodbc

from .base import BaseDataSourceAdapter, DataSourceInfo, DataItem, SchemaInfo

logger = logging.getLogger("data-access-mcp")


class AzureSQLAdapter(BaseDataSourceAdapter):
    """Adapter for Azure SQL Database.

    Supports:
    - Direct connection string authentication
    - OBO token authentication (fetches fresh token per request, NO caching)
    """

    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        self.connection_string = config.get("connection_string")
        self.use_obo = config.get("use_obo", False)
        self.obo_config = config.get("obo_config", {})
        self._connection = None

    @property
    def source_info(self) -> DataSourceInfo:
        return DataSourceInfo(
            source_id=self.config.get("source_id", f"azure-sql-{self.config.get('name', 'unknown')}"),
            source_type="azure-sql",
            name=self.config.get("name", "unknown"),
            auth_type="obo" if self.use_obo else "connection_string",
        )

    async def _get_connection(self) -> pyodbc.Connection:
        """Get a database connection.

        IMPORTANT: OBO tokens are fetched fresh per request and never cached.
        """
        if self._connection:
            return self._connection

        if self.use_obo:
            access_token = await self._fetch_obo_token()
            driver = self.obo_config.get("driver", "ODBC Driver 18 for SQL Server")
            server = self.obo_config.get("server")
            database = self.obo_config.get("database")

            conn_str = (
                f"DRIVER={{{driver}}};"
                f"SERVER={server};"
                f"DATABASE={database};"
                f"AccessToken={access_token};"
                "TrustServerCertificate=yes;"
            )
        else:
            conn_str = self.connection_string

        self._connection = pyodbc.connect(conn_str)
        return self._connection

    async def _fetch_obo_token(self) -> str:
        """Fetch fresh OBO token from Keycloak.

        IMPORTANT: This fetches a new token each time - NO caching.
        """
        from httpx import AsyncClient

        tenant_id = self.obo_config["tenant_id"]
        client_id = self.obo_config["client_id"]
        scope = self.obo_config["scope"]

        token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"

        data = {
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": self.obo_config["client_secret"],
            "scope": scope,
        }

        async with AsyncClient() as client:
            response = await client.post(token_url, data=data)
            response.raise_for_status()
            return response.json()["access_token"]

    async def list_available_data(
        self,
        path: str = "",
        recursive: bool = False,
    ) -> dict:
        """List tables in the database.

        Args:
            path: Optional schema name to filter
            recursive: Not applicable for SQL, ignored
        """
        try:
            conn = await self._get_connection()
            cursor = conn.cursor()

            if path:
                query = """
                    SELECT TABLE_SCHEMA, TABLE_NAME
                    FROM INFORMATION_SCHEMA.TABLES
                    WHERE TABLE_TYPE = 'BASE TABLE' AND TABLE_SCHEMA = ?
                    ORDER BY TABLE_SCHEMA, TABLE_NAME
                """
                cursor.execute(query, (path,))
            else:
                query = """
                    SELECT TABLE_SCHEMA, TABLE_NAME
                    FROM INFORMATION_SCHEMA.TABLES
                    WHERE TABLE_TYPE = 'BASE TABLE'
                    ORDER BY TABLE_SCHEMA, TABLE_NAME
                """
                cursor.execute(query)

            data_items = []
            for schema, table_name in cursor.fetchall():
                data_items.append(DataItem(
                    item_id=f"{schema}.{table_name}",
                    name=f"{schema}.{table_name}",
                    type="table",
                    metadata={"schema": schema, "table": table_name},
                ))

            return {
                "success": True,
                "data_items": [self._data_item_to_dict(item) for item in data_items],
                "count": len(data_items),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def get_schema(self, data_id: str) -> dict:
        """Get schema information for a table."""
        try:
            schema, table_name = data_id.split(".", 1)
            conn = await self._get_connection()
            cursor = conn.cursor()

            query = """
                SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE, COLUMN_DEFAULT
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?
                ORDER BY ORDINAL_POSITION
            """
            cursor.execute(query, (schema, table_name))

            columns = []
            for name, data_type, is_nullable, default in cursor.fetchall():
                columns.append({
                    "name": name,
                    "type": data_type,
                    "nullable": is_nullable == "YES",
                    "default": default,
                })

            return {
                "success": True,
                "schema": SchemaInfo(
                    columns=columns,
                    metadata={"schema": schema, "table": table_name},
                ),
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
        """Read data from a table with optional filtering and limiting."""
        try:
            schema, table_name = data_id.split(".", 1)
            conn = await self._get_connection()
            cursor = conn.cursor()

            query = f"SELECT * FROM [{schema}].[{table_name}]"
            params = []

            if filter_expr:
                query += f" WHERE {filter_expr}"

            if limit is not None:
                if offset is not None:
                    query += f" ORDER BY (SELECT NULL) OFFSET ? ROWS FETCH NEXT ? ROWS ONLY"
                    params.extend([offset, limit])
                else:
                    query += f" ORDER BY (SELECT NULL) OFFSET 0 ROWS FETCH NEXT ? ROWS ONLY"
                    params.append(limit)
            elif offset is not None:
                query += f" ORDER BY (SELECT NULL) OFFSET ? ROWS"
                params.append(offset)

            cursor.execute(query, params)

            columns = [desc[0] for desc in cursor.description]
            rows = cursor.fetchall()

            data = [{col: value for col, value in zip(columns, row)} for row in rows]

            return {
                "success": True,
                "data": data,
                "row_count": len(data),
                "columns": columns,
                "metadata": {
                    "table": f"{schema}.{table_name}",
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
        """Download table data as CSV."""
        try:
            import csv

            result = await self.read_data(data_id)

            if not result["success"]:
                return result

            with open(destination_path, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=result["columns"])
                writer.writeheader()
                writer.writerows(result["data"])

            return {
                "success": True,
                "destination": destination_path,
                "row_count": result["row_count"],
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def close(self):
        """Close the database connection."""
        if self._connection:
            self._connection.close()
            self._connection = None

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