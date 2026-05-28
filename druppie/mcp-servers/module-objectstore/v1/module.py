"""Objectstore Module v1 — Public API.

Entry point for v1 business logic. One public method per MCP tool.
Wraps S3-compatible object storage for upload, download, and deletion.
"""

import io
import logging
import os
import uuid
from typing import Any

import boto3
from botocore.config import Config as BotoConfig

logger = logging.getLogger("objectstore-mcp.v1")

S3_ENDPOINT_URL = os.getenv("S3_ENDPOINT_URL", "http://localhost:9000")
S3_ACCESS_KEY = os.getenv("S3_ACCESS_KEY", "minioadmin")
S3_SECRET_KEY = os.getenv("S3_SECRET_KEY", "minioadmin")
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME", "druppie-objects")
S3_REGION = os.getenv("S3_REGION", "us-east-1")


class ObjectstoreModule:
    """v1 business logic for S3-compatible object storage.

    Provides upload, presigned URL generation, and deletion of objects.
    All public methods correspond 1:1 to MCP tools defined in tools.py.
    """

    def __init__(
        self,
        endpoint_url: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
        bucket_name: str | None = None,
        region: str | None = None,
    ):
        self._endpoint_url = endpoint_url or S3_ENDPOINT_URL
        self._access_key = access_key or S3_ACCESS_KEY
        self._secret_key = secret_key or S3_SECRET_KEY
        self._bucket_name = bucket_name or S3_BUCKET_NAME
        self._region = region or S3_REGION

        self._client = boto3.client(
            "s3",
            endpoint_url=self._endpoint_url,
            aws_access_key_id=self._access_key,
            aws_secret_access_key=self._secret_key,
            region_name=self._region,
            config=BotoConfig(
                signature_version="s3v4",
                retries={"max_attempts": 3, "mode": "standard"},
            ),
        )
        self._ensure_bucket_exists()

    def _ensure_bucket_exists(self) -> None:
        """Create the bucket if it does not exist."""
        try:
            self._client.head_bucket(Bucket=self._bucket_name)
        except Exception:
            try:
                self._client.create_bucket(Bucket=self._bucket_name)
                logger.info("Created bucket: %s", self._bucket_name)
            except Exception as e:
                logger.warning("Could not create bucket %s: %s", self._bucket_name, e)

    async def upload_object(
        self,
        data: str,
        filename: str,
        content_type: str = "application/octet-stream",
        prefix: str = "",
        user_id: str = "",
        project_id: str = "",
        session_id: str = "",
        app_id: str = "",
    ) -> dict[str, Any]:
        """Upload a file (base64-encoded bytes) to the S3 bucket.

        Args:
            data: Base64-encoded file content.
            filename: Original filename.
            content_type: MIME type of the file.
            prefix: Optional key prefix (folder path).

        Returns:
            Dictionary with object_key and size.
        """
        import base64

        if not data:
            raise ValueError("No data provided for upload")
        if not filename:
            raise ValueError("Filename is required")

        # Decode base64 data
        try:
            file_bytes = base64.b64decode(data)
        except Exception as e:
            raise ValueError(f"Invalid base64 data: {e}") from e

        # Generate object key
        ext = os.path.splitext(filename)[1]
        object_id = uuid.uuid4().hex[:12]
        key = f"{prefix}/{object_id}{ext}" if prefix else f"{object_id}{ext}"

        self._client.upload_fileobj(
            io.BytesIO(file_bytes),
            self._bucket_name,
            key,
            ExtraArgs={"ContentType": content_type},
        )

        return {
            "object_key": key,
            "filename": filename,
            "size_bytes": len(file_bytes),
            "content_type": content_type,
            "bucket": self._bucket_name,
        }

    async def get_object_url(
        self,
        object_key: str,
        expires_in: int = 3600,
        user_id: str = "",
        project_id: str = "",
        session_id: str = "",
        app_id: str = "",
    ) -> dict[str, Any]:
        """Generate a presigned URL for downloading an object.

        Args:
            object_key: The S3 object key.
            expires_in: URL expiration time in seconds (default 3600 = 1 hour).

        Returns:
            Dictionary with presigned URL and expiration.
        """
        if not object_key:
            raise ValueError("Object key is required")

        expires_in = max(60, min(expires_in, 86400))  # Clamp: 1 min to 24 hours

        url = self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self._bucket_name, "Key": object_key},
            ExpiresIn=expires_in,
        )

        return {
            "object_key": object_key,
            "url": url,
            "expires_in_seconds": expires_in,
            "bucket": self._bucket_name,
        }

    async def delete_object(
        self,
        object_key: str,
        user_id: str = "",
        project_id: str = "",
        session_id: str = "",
        app_id: str = "",
    ) -> dict[str, Any]:
        """Delete an object from the bucket.

        Args:
            object_key: The S3 object key to delete.

        Returns:
            Dictionary with deletion confirmation.
        """
        if not object_key:
            raise ValueError("Object key is required")

        self._client.delete_object(
            Bucket=self._bucket_name,
            Key=object_key,
        )

        return {
            "object_key": object_key,
            "status": "verwijderd",
            "bucket": self._bucket_name,
        }
