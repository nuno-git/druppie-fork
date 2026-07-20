"""Abstract base class for data source adapters.

All adapters must implement these methods to provide a unified interface
for accessing data from different sources (Azure Data Lake, Azure SQL, etc.).
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("dataaccess-mcp")


@dataclass
class DataSourceInfo:
    """Information about a data source."""
    source_id: str
    source_type: str
    name: str
    auth_type: str
    detail: str = ""


@dataclass
class DataItem:
    """An item of available data (table, file, etc.)."""
    item_id: str
    name: str
    type: str
    metadata: dict[str, Any]


@dataclass
class SchemaInfo:
    """Schema information for a data item."""
    columns: list[dict[str, Any]]
    metadata: dict[str, Any]


class BaseDataSourceAdapter(ABC):
    """Abstract base class for data source adapters.

    Each adapter implements methods for:
    - Listing available data
    - Getting schema information
    - Reading/querying data
    - Downloading data

    IMPORTANT: OBO tokens must NEVER be cached or stored. Fetch fresh token
    per request.
    """

    def __init__(self, config: dict[str, Any]):
        """Initialize adapter with configuration.

        Args:
            config: Adapter-specific configuration
        """
        self.config = config
        self._connection = None

    @property
    @abstractmethod
    def source_info(self) -> DataSourceInfo:
        """Return information about this data source."""
        pass

    @abstractmethod
    async def list_available_data(
        self,
        path: str = "",
        recursive: bool = False,
        user_token: str | None = None,
    ) -> dict:
        """List available data items (tables, files, datasets).

        Args:
            path: Optional path/namespace to filter results
            recursive: Whether to list recursively (for hierarchical sources)

        Returns:
            Dict with 'success', 'data_items' list, and metadata
        """
        pass

    @abstractmethod
    async def get_schema(self, data_id: str, user_token: str | None = None) -> dict:
        """Get schema/metadata for a specific data item.

        Args:
            data_id: Identifier for the data item (table name, file path, etc.)

        Returns:
            Dict with 'success', 'schema' (SchemaInfo), and metadata
        """
        pass

    @abstractmethod
    async def read_data(
        self,
        data_id: str,
        filter_expr: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
        user_token: str | None = None,
    ) -> dict:
        """Read data from a source.

        This handles both SQL queries (for SQL sources) and file reads
        (for file-based sources) transparently based on source type.

        Args:
            data_id: Identifier for the data item
            filter_expr: Optional filter/where clause or predicate
            limit: Optional maximum rows to return (no limit if None)
            offset: Optional offset for pagination

        Returns:
            Dict with 'success', 'data' (records), 'row_count', and metadata
        """
        pass

    @abstractmethod
    async def download_data(
        self,
        data_id: str,
        destination_path: str,
        user_token: str | None = None,
    ) -> dict:
        """Download data to a local destination.

        Args:
            data_id: Identifier for the data item
            destination_path: Local filesystem path to write to

        Returns:
            Dict with 'success', 'destination', 'size_bytes', and metadata
        """
        pass

    async def execute_query(
        self,
        query: str,
        limit: int | None = None,
        user_token: str | None = None,
    ) -> dict:
        """Run a free-form read-only query.

        Default implementation reports the operation as unsupported; SQL
        adapters override this. File-based adapters cannot satisfy a SQL
        query and must not silently succeed.
        """
        return {
            "success": False,
            "error": (
                f"execute_query is not supported for source type "
                f"'{self.source_info.source_type}' — use read_data instead"
            ),
        }

    async def test_connection(self, user_token: str | None = None) -> dict:
        """Test connection to the data source.

        Returns:
            Dict with 'success', 'message', and any error details
        """
        try:
            await self._ensure_connection()
            return {
                "success": True,
                "message": f"Successfully connected to {self.source_info.name}",
                "source_info": self.source_info,
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "source_info": self.source_info,
            }

    async def _ensure_connection(self):
        """Ensure connection is established. Override in subclasses."""
        pass

    async def close(self):
        """Close connection. Override in subclasses."""
        pass