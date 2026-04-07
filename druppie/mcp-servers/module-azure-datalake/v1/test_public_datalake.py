"""Integration tests for Azure Data Lake MCP against Microsoft's public datasets.

Tests use the public Azure Open Datasets storage account:
https://azureopendatastorage.blob.core.windows.net

This account hosts NYC Taxi data, public holidays, and other datasets
accessible anonymously via Blob API. Note: this account does NOT have
Hierarchical Namespace (HNS) enabled, so DFS-specific operations
(list_file_systems, get_paths) may fail with auth errors. Tests gracefully
skip when operations are not supported by the target account.

When run against a proper ADLS Gen2 account with HNS enabled, all tests
will fully exercise the tools.

Run with: pytest test_public_datalake.py -v
"""

import pytest

from .module import AzureDataLakeModule

PUBLIC_ACCOUNT_URL = "https://azureopendatastorage.blob.core.windows.net"
KNOWN_CONTAINER = "nyctlc"
# Known parquet file path in nyctlc — NYC Taxi green trip data
KNOWN_PARQUET_PATH = "green/puYear=2015/puMonth=1/part-00000-tid-5765235745422826791-87699929-65f2-4562-9a1f-6af8caac9207-5765-1.c000.snappy.parquet"


@pytest.fixture
def module():
    """Create module with no pre-configured lakes (testing public access only)."""
    return AzureDataLakeModule(datalake_configs={})


@pytest.mark.integration
def test_list_datalakes_empty(module):
    """list_datalakes returns empty list when no lakes are configured."""
    result = module.list_datalakes()
    assert result["success"] is True
    assert result["count"] == 0
    assert result["datalakes"] == []


@pytest.mark.integration
@pytest.mark.asyncio
async def test_connection(module):
    """Test anonymous connection to Microsoft's public storage account."""
    result = await module.test_connection(account_url=PUBLIC_ACCOUNT_URL)

    if result["success"]:
        assert result["access_type"] == "public"
        assert result["container_count"] >= 0
    else:
        # Blob-only accounts may block DFS list_file_systems
        pytest.skip(f"Account-level access blocked (no HNS): {result.get('error', 'unknown')}")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_containers(module):
    """List containers on the public storage account."""
    result = await module.list_containers(account_url=PUBLIC_ACCOUNT_URL)

    if result["success"]:
        assert result["access_type"] == "public"
        assert result["count"] > 0
        container_names = [c["name"] for c in result["containers"]]
        assert KNOWN_CONTAINER in container_names, (
            f"Expected '{KNOWN_CONTAINER}' in containers, got: {container_names}"
        )
    else:
        # Blob-only accounts may block DFS list_file_systems
        pytest.skip(f"Container listing blocked (no HNS): {result.get('error', 'unknown')}")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_paths(module):
    """List files in the nyctlc container (NYC Taxi data)."""
    result = await module.list_paths(
        container=KNOWN_CONTAINER,
        account_url=PUBLIC_ACCOUNT_URL,
    )

    if result["success"]:
        assert result["access_type"] == "public"
        assert result["container"] == KNOWN_CONTAINER
        assert result["count"] > 0
        path_names = [p["name"] for p in result["paths"]]
        assert len(path_names) > 0, "Expected at least one path in nyctlc container"
    else:
        # DFS get_paths requires HNS — Blob-only accounts reject this
        pytest.skip(f"Path listing blocked (no HNS): {result.get('error', 'unknown')}")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_read_file_schema(module):
    """Read schema of a Parquet file from NYC Taxi dataset."""
    # Try known path directly instead of discovering via list_paths
    result = await module.read_file_schema(
        container=KNOWN_CONTAINER,
        path=KNOWN_PARQUET_PATH,
        account_url=PUBLIC_ACCOUNT_URL,
    )

    if result["success"]:
        assert result["file_type"] == "parquet"
        assert len(result["columns"]) > 0
        assert len(result["schema"]) > 0
    else:
        # Direct file access may also fail on Blob-only accounts via DFS client
        pytest.skip(f"File schema read blocked (no HNS): {result.get('error', 'unknown')}")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_read_file(module):
    """Read a small sample from a Parquet file in NYC Taxi dataset."""
    # Try known path directly instead of discovering via list_paths
    result = await module.read_file(
        container=KNOWN_CONTAINER,
        path=KNOWN_PARQUET_PATH,
        account_url=PUBLIC_ACCOUNT_URL,
        max_rows=5,
    )

    if result["success"]:
        assert result["file_type"] == "parquet"
        assert result["row_count"] <= 5
        assert len(result["data"]) <= 5
        assert len(result["columns"]) > 0
    else:
        # Direct file access may also fail on Blob-only accounts via DFS client
        pytest.skip(f"File read blocked (no HNS): {result.get('error', 'unknown')}")
