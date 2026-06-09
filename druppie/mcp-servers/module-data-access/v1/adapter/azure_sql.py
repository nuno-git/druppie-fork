"""Azure SQL adapter for the data access MCP module.

Supports OBO token authentication via Keycloak.
"""

import logging
import re
from typing import Any

import pyodbc

from .base import BaseDataSourceAdapter, DataSourceInfo, DataItem, SchemaInfo

logger = logging.getLogger("dataaccess-mcp")

# When read_data is called without an explicit limit, cap the result so an
# agent can't pull an entire Synapse table into the LLM context by accident.
DEFAULT_ROW_CAP = 1000

# Hard ceiling for download_data so a runaway table can't exhaust memory /
# disk in the MCP container.
DOWNLOAD_ROW_CAP = 1_000_000

# Rows fetched per round-trip while streaming a download.
DOWNLOAD_BATCH_SIZE = 5000

# filter_expr is a WHERE-clause fragment, not arbitrary SQL. Reject tokens
# that would let it break out of the clause (statement terminators, comment
# markers, batch separators, extended stored procedures). Defence in depth —
# the configured SQL principal should also be db_datareader only.
_FILTER_FORBIDDEN = re.compile(
    r";|--|/\*|\*/|\bxp_|\bsp_|\bexec\b|\bexecute\b|\bgo\b",
    re.IGNORECASE,
)

# execute_query accepts a single read-only statement. It must START with
# SELECT or WITH (after whitespace) and must not contain any of the tokens
# below — comments, batch separators, stored-proc markers, or DML/DDL
# verbs. The configured db_datareader principal is the real hard line;
# this validator just makes the contract explicit at the boundary.
_QUERY_LEADING_KEYWORD = re.compile(r"^\s*(select|with)\b", re.IGNORECASE)
_QUERY_FORBIDDEN = re.compile(
    r"--|/\*|\*/|\bxp_|\bsp_|\bexec\b|\bexecute\b|\bgo\b|"
    r"\binsert\b|\bupdate\b|\bdelete\b|\bmerge\b|\bdrop\b|"
    r"\balter\b|\bcreate\b|\btruncate\b|\bgrant\b|\brevoke\b",
    re.IGNORECASE,
)


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

    async def _ensure_connection(self):
        """Prove connectivity for the inherited test_connection().

        The base class test_connection() only awaits _ensure_connection();
        without this override it would hit the base no-op and report success
        even when the database is unreachable. Open a real connection and run
        a trivial query so a failure surfaces honestly.
        """
        conn = await self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        cursor.fetchone()

    @staticmethod
    def _validate_filter(filter_expr: str) -> None:
        """Reject a filter_expr that tries to break out of the WHERE clause.

        Raises ValueError on a forbidden token.
        """
        if _FILTER_FORBIDDEN.search(filter_expr):
            raise ValueError(
                "filter_expr must be a plain WHERE-clause fragment — "
                "statement terminators, comments and stored-procedure "
                "calls are not allowed"
            )

    @staticmethod
    def _validate_query(query: str) -> str:
        """Validate and normalise a free-form SELECT/WITH query.

        Strips a single trailing semicolon (a common harmless habit) and
        then rejects the query if it contains any forbidden token or does
        not start with SELECT/WITH. Returns the normalised query.
        """
        normalised = query.strip().rstrip(";").strip()
        if not _QUERY_LEADING_KEYWORD.match(normalised):
            raise ValueError(
                "query must start with SELECT or WITH — execute_query is "
                "read-only"
            )
        if ";" in normalised:
            raise ValueError(
                "query must be a single statement — additional ';' "
                "separators are not allowed"
            )
        if _QUERY_FORBIDDEN.search(normalised):
            raise ValueError(
                "query contains a forbidden token (DML/DDL verb, comment, "
                "batch separator or stored-procedure call)"
            )
        return normalised

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
        """Read data from a table with optional filtering and limiting.

        When no limit is given the result is capped at DEFAULT_ROW_CAP so an
        agent cannot accidentally pull an entire table into context; the cap
        is reported in warnings[] and metadata.capped.
        """
        try:
            schema, table_name = data_id.split(".", 1)
            if filter_expr:
                self._validate_filter(filter_expr)

            warnings: list[str] = []
            capped = limit is None
            effective_limit = limit if limit is not None else DEFAULT_ROW_CAP

            conn = await self._get_connection()
            cursor = conn.cursor()

            query = f"SELECT * FROM [{schema}].[{table_name}]"
            params: list = []

            if filter_expr:
                query += f" WHERE {filter_expr}"

            query += " ORDER BY (SELECT NULL) OFFSET ? ROWS FETCH NEXT ? ROWS ONLY"
            params.extend([offset or 0, effective_limit])

            cursor.execute(query, params)

            columns = [desc[0] for desc in cursor.description]
            rows = cursor.fetchall()
            data = [{col: value for col, value in zip(columns, row)} for row in rows]

            if capped and len(data) == effective_limit:
                warnings.append(
                    f"No limit was given — result capped at {DEFAULT_ROW_CAP} "
                    "rows. Pass an explicit 'limit' to read more."
                )

            return {
                "success": True,
                "data": data,
                "row_count": len(data),
                "columns": columns,
                "warnings": warnings,
                "metadata": {
                    "table": f"{schema}.{table_name}",
                    "filtered": filter_expr is not None,
                    "limited": limit is not None,
                    "offset": offset,
                    "capped": capped and len(data) == effective_limit,
                },
            }
        except ValueError as e:
            return {"success": False, "error": str(e)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def execute_query(
        self,
        query: str,
        limit: int | None = None,
    ) -> dict:
        """Run a read-only SELECT/WITH query against the source.

        The query is validated and capped at DEFAULT_ROW_CAP rows when no
        explicit limit is given; one extra row is fetched to detect
        truncation so callers can paginate via their own ORDER BY/OFFSET.
        """
        try:
            normalised = self._validate_query(query)

            warnings: list[str] = []
            capped_by_default = limit is None
            effective_limit = limit if limit is not None else DEFAULT_ROW_CAP

            conn = await self._get_connection()
            cursor = conn.cursor()
            cursor.execute(normalised)

            if cursor.description is None:
                return {
                    "success": False,
                    "error": "query returned no result set",
                }

            columns = [desc[0] for desc in cursor.description]
            rows = cursor.fetchmany(effective_limit + 1)
            truncated = len(rows) > effective_limit
            rows = rows[:effective_limit]
            data = [{col: value for col, value in zip(columns, row)} for row in rows]

            if truncated:
                msg = (
                    f"Result truncated at {effective_limit} rows; pass a "
                    "larger 'limit' or paginate via ORDER BY/OFFSET."
                )
                if capped_by_default:
                    msg = (
                        f"No limit was given — result capped at "
                        f"{DEFAULT_ROW_CAP} rows. " + msg
                    )
                warnings.append(msg)

            return {
                "success": True,
                "data": data,
                "row_count": len(data),
                "columns": columns,
                "warnings": warnings,
                "metadata": {
                    "limited": limit is not None,
                    "truncated": truncated,
                },
            }
        except ValueError as e:
            return {"success": False, "error": str(e)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def download_data(
        self,
        data_id: str,
        destination_path: str,
    ) -> dict:
        """Download a full table to CSV, streaming in batches.

        Rows are fetched DOWNLOAD_BATCH_SIZE at a time and written
        incrementally so a large table does not have to be materialised in
        memory. A hard DOWNLOAD_ROW_CAP guards against a runaway table.
        """
        try:
            import csv

            schema, table_name = data_id.split(".", 1)
            conn = await self._get_connection()
            cursor = conn.cursor()
            cursor.execute(f"SELECT * FROM [{schema}].[{table_name}]")

            columns = [desc[0] for desc in cursor.description]
            row_count = 0
            truncated = False
            warnings: list[str] = []

            with open(destination_path, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(columns)
                while True:
                    batch = cursor.fetchmany(DOWNLOAD_BATCH_SIZE)
                    if not batch:
                        break
                    if row_count + len(batch) > DOWNLOAD_ROW_CAP:
                        batch = batch[: DOWNLOAD_ROW_CAP - row_count]
                        truncated = True
                    writer.writerows(batch)
                    row_count += len(batch)
                    if truncated:
                        break

            if truncated:
                warnings.append(
                    f"Table exceeded the {DOWNLOAD_ROW_CAP}-row download cap; "
                    "the CSV is truncated."
                )

            return {
                "success": True,
                "destination": destination_path,
                "row_count": row_count,
                "warnings": warnings,
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