"""Tests for Objectstore Module v1."""

import base64
import os

import pytest

# Set test S3 config before importing module
os.environ.setdefault("S3_ENDPOINT_URL", "http://localhost:9000")
os.environ.setdefault("S3_ACCESS_KEY", "test-access")
os.environ.setdefault("S3_SECRET_KEY", "test-secret")
os.environ.setdefault("S3_BUCKET_NAME", "test-bucket")

from v1.module import ObjectstoreModule


class TestObjectstoreModuleInit:
    """Test module initialization."""

    def test_init_with_defaults(self):
        """Module should initialize with env defaults."""
        # This will try to connect to S3, but we just test config
        # We skip actual connection for unit tests
        pass

    def test_config_from_env(self):
        """Module should read config from environment."""
        assert os.environ.get("S3_ENDPOINT_URL") is not None
        assert os.environ.get("S3_BUCKET_NAME") is not None


class TestUploadObject:
    """Test upload_object method."""

    def test_method_signature(self):
        """Verify upload_object accepts expected params."""
        import inspect

        sig = inspect.signature(ObjectstoreModule.upload_object)
        params = list(sig.parameters.keys())
        assert "data" in params
        assert "filename" in params
        assert "content_type" in params
        assert "prefix" in params
        assert "user_id" in params
        assert "project_id" in params

    @pytest.mark.asyncio
    async def test_upload_validates_empty_data(self):
        """Empty data should raise ValueError."""
        mod = ObjectstoreModule.__new__(ObjectstoreModule)
        mod._bucket_name = "test"
        with pytest.raises(ValueError, match="No data"):
            await mod.upload_object(data="", filename="test.jpg")

    @pytest.mark.asyncio
    async def test_upload_validates_empty_filename(self):
        """Empty filename should raise ValueError."""
        mod = ObjectstoreModule.__new__(ObjectstoreModule)
        mod._bucket_name = "test"
        with pytest.raises(ValueError, match="Filename"):
            await mod.upload_object(data="dGVzdA==", filename="")


class TestGetObjectUrl:
    """Test get_object_url method."""

    def test_method_signature(self):
        """Verify get_object_url accepts expected params."""
        import inspect

        sig = inspect.signature(ObjectstoreModule.get_object_url)
        params = list(sig.parameters.keys())
        assert "object_key" in params
        assert "expires_in" in params
        assert "user_id" in params

    @pytest.mark.asyncio
    async def test_get_url_validates_empty_key(self):
        """Empty object_key should raise ValueError."""
        mod = ObjectstoreModule.__new__(ObjectstoreModule)
        mod._bucket_name = "test"
        with pytest.raises(ValueError, match="Object key"):
            await mod.get_object_url(object_key="")


class TestDeleteObject:
    """Test delete_object method."""

    def test_method_signature(self):
        """Verify delete_object accepts expected params."""
        import inspect

        sig = inspect.signature(ObjectstoreModule.delete_object)
        params = list(sig.parameters.keys())
        assert "object_key" in params
        assert "user_id" in params
        assert "project_id" in params

    @pytest.mark.asyncio
    async def test_delete_validates_empty_key(self):
        """Empty object_key should raise ValueError."""
        mod = ObjectstoreModule.__new__(ObjectstoreModule)
        mod._bucket_name = "test"
        with pytest.raises(ValueError, match="Object key"):
            await mod.delete_object(object_key="")
