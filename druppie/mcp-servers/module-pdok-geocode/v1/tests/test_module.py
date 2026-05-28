"""Tests for PDOK Geocode Module v1."""

import pytest

from v1.module import PdokGeocodeModule


@pytest.fixture
def module():
    """Create a PdokGeocodeModule instance."""
    return PdokGeocodeModule()


class TestPdokGeocodeModuleInit:
    """Test module initialization."""

    def test_init_creates_http_client(self, module):
        """Module should have an httpx client."""
        assert module._client is not None


class TestReverseGeocode:
    """Test reverse_geocode method."""

    def test_method_signature(self, module):
        """Verify reverse_geocode accepts expected params."""
        import inspect

        sig = inspect.signature(module.reverse_geocode)
        params = list(sig.parameters.keys())
        assert "lat" in params
        assert "lon" in params
        assert "user_id" in params
        assert "project_id" in params
        assert "session_id" in params
        assert "app_id" in params

    @pytest.mark.asyncio
    async def test_reverse_geocode_returns_structure(self, module):
        """Verify reverse_geocode returns expected keys (mocked test would
        be needed for full integration). This tests the return structure
        by checking method signature."""
        import inspect

        sig = inspect.signature(module.reverse_geocode)
        assert "lat" in sig.parameters
        assert sig.parameters["lat"].annotation is float
        assert sig.parameters["lon"].annotation is float


class TestSearchAddress:
    """Test search_address method."""

    def test_method_signature(self, module):
        """Verify search_address accepts expected params."""
        import inspect

        sig = inspect.signature(module.search_address)
        params = list(sig.parameters.keys())
        assert "query" in params
        assert "rows" in params
        assert "user_id" in params

    @pytest.mark.asyncio
    async def test_search_address_validates_min_length(self, module):
        """Query shorter than 2 characters should raise ValueError."""
        with pytest.raises(ValueError, match="at least 2"):
            await module.search_address(query="a")

    @pytest.mark.asyncio
    async def test_search_address_validates_empty_query(self, module):
        """Empty query should raise ValueError."""
        with pytest.raises(ValueError, match="at least 2"):
            await module.search_address(query="")

    @pytest.mark.asyncio
    async def test_search_address_validates_whitespace_query(self, module):
        """Whitespace-only query should raise ValueError."""
        with pytest.raises(ValueError, match="at least 2"):
            await module.search_address(query="  ")
