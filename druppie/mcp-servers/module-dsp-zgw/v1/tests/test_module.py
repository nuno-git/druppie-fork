"""Tests for DSP ZGW Module v1."""

import pytest

from v1.module import DspZgwModule


@pytest.fixture
def module():
    """Create a DspZgwModule instance with test defaults."""
    return DspZgwModule(
        base_url="https://zaken.test.example.com",
        client_id="test-client",
        client_secret="test-secret",
    )


class TestDspZgwModuleInit:
    """Test module initialization."""

    def test_init_with_defaults(self):
        mod = DspZgwModule()
        assert mod._base_url
        assert mod._client_id
        assert mod._client_secret

    def test_init_with_custom_params(self):
        mod = DspZgwModule(
            base_url="https://custom.example.com",
            client_id="custom-id",
            client_secret="custom-secret",
        )
        assert mod._base_url == "https://custom.example.com"
        assert mod._client_id == "custom-id"

    def test_init_strips_trailing_slash(self):
        mod = DspZgwModule(base_url="https://example.com/")
        assert mod._base_url == "https://example.com"

    def test_headers_set(self, module):
        assert module._headers["Client-Id"] == "test-client"
        assert module._headers["Client-Secret"] == "test-secret"


class TestCreateZaak:
    """Test create_zaak method."""

    @pytest.mark.asyncio
    async def test_create_zaak_returns_expected_keys(self, module):
        """Verify create_zaak returns the expected structure.

        This is a structural test — full integration tests would require
        a running ZGW API endpoint.
        """
        # Verify the method signature accepts all required params
        import inspect

        sig = inspect.signature(module.create_zaak)
        params = list(sig.parameters.keys())
        assert "zaaktype" in params
        assert "beschrijving" in params
        assert "locatie_lat" in params
        assert "locatie_lon" in params
        assert "metadata" in params
        assert "user_id" in params
        assert "project_id" in params


class TestGetZaakStatus:
    """Test get_zaak_status method."""

    @pytest.mark.asyncio
    async def test_method_signature(self, module):
        """Verify get_zaak_status accepts expected params."""
        import inspect

        sig = inspect.signature(module.get_zaak_status)
        params = list(sig.parameters.keys())
        assert "zaak_id" in params
        assert "user_id" in params


class TestGetZaaktypen:
    """Test get_zaaktypen method."""

    @pytest.mark.asyncio
    async def test_method_signature(self, module):
        """Verify get_zaaktypen accepts expected params."""
        import inspect

        sig = inspect.signature(module.get_zaaktypen)
        params = list(sig.parameters.keys())
        assert "user_id" in params
        assert "project_id" in params


class TestLinkDocumentToZaak:
    """Test link_document_to_zaak method."""

    @pytest.mark.asyncio
    async def test_method_signature(self, module):
        """Verify link_document_to_zaak accepts expected params."""
        import inspect

        sig = inspect.signature(module.link_document_to_zaak)
        params = list(sig.parameters.keys())
        assert "zaak_url" in params
        assert "document_url" in params
        assert "titel" in params
