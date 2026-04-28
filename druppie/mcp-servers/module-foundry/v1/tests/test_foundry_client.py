"""Unit tests for FoundryClient — pure-logic methods only.

build_tool_objects is a static method that maps tool-ref dicts to Azure
SDK objects. Tests that exercise SDK tool construction are skipped when
azure-ai-projects can't be imported (e.g. local dev without Docker).
"""

from __future__ import annotations

import pytest

from v1.foundry_client import CONNECTION_TYPE_TO_TOOL, FoundryClient

_has_azure_sdk = True
try:
    from azure.ai.projects.models import CodeInterpreterTool  # noqa: F401
except Exception:
    _has_azure_sdk = False

needs_sdk = pytest.mark.skipif(not _has_azure_sdk, reason="azure-ai-projects not available")


# ------------------------------------------------------------------
# build_tool_objects
# ------------------------------------------------------------------


class TestBuildToolObjects:
    def test_empty_refs_returns_empty(self):
        tools, skipped = FoundryClient.build_tool_objects([])
        assert tools == []
        assert skipped == []

    @needs_sdk
    def test_code_interpreter_returns_tool(self):
        tools, skipped = FoundryClient.build_tool_objects(
            [{"type": "code_interpreter"}]
        )
        assert len(tools) == 1
        assert skipped == []

    @needs_sdk
    def test_file_search_returns_tool(self):
        tools, skipped = FoundryClient.build_tool_objects(
            [{"type": "file_search"}]
        )
        assert len(tools) == 1
        assert skipped == []

    @needs_sdk
    def test_bing_grounding_with_connection_id(self):
        tools, skipped = FoundryClient.build_tool_objects(
            [{"type": "bing_grounding", "connection_id": "/subscriptions/x/connections/bing"}]
        )
        assert len(tools) == 1
        assert skipped == []

    @needs_sdk
    def test_bing_grounding_without_connection_id(self):
        tools, skipped = FoundryClient.build_tool_objects(
            [{"type": "bing_grounding"}]
        )
        assert len(tools) == 1
        assert skipped == []

    def test_unsupported_type_skipped(self):
        tools, skipped = FoundryClient.build_tool_objects(
            [{"type": "browser_automation"}]
        )
        assert tools == []
        assert skipped == ["browser_automation"]

    @needs_sdk
    def test_mixed_supported_and_unsupported(self):
        tools, skipped = FoundryClient.build_tool_objects(
            [
                {"type": "code_interpreter"},
                {"type": "deep_research"},
                {"type": "file_search"},
                {"type": "browser_automation"},
            ]
        )
        assert len(tools) == 2
        assert set(skipped) == {"deep_research", "browser_automation"}

    def test_multiple_skipped_preserves_order(self):
        tools, skipped = FoundryClient.build_tool_objects(
            [
                {"type": "browser_automation"},
                {"type": "deep_research"},
            ]
        )
        assert tools == []
        assert skipped == ["browser_automation", "deep_research"]


# ------------------------------------------------------------------
# CONNECTION_TYPE_TO_TOOL mapping
# ------------------------------------------------------------------


class TestConnectionTypeMapping:
    def test_bing_variants_all_map(self):
        for key in ("groundingwithbingsearch", "apibinggrounding", "bing_grounding"):
            assert CONNECTION_TYPE_TO_TOOL[key] == "bing_grounding"

    def test_search_variants_map(self):
        for key in ("azureaisearch", "cognitivesearch"):
            assert CONNECTION_TYPE_TO_TOOL[key] == "azure_ai_search"

    def test_fabric_variants_map(self):
        for key in ("fabric", "microsoftfabric"):
            assert CONNECTION_TYPE_TO_TOOL[key] == "microsoft_fabric"

    def test_sharepoint_variants_map(self):
        for key in ("sharepoint", "sharepointgrounding", "microsoft365", "m365"):
            assert CONNECTION_TYPE_TO_TOOL[key] == "sharepoint_grounding"

    def test_unknown_type_returns_none(self):
        assert CONNECTION_TYPE_TO_TOOL.get("totally_unknown") is None
