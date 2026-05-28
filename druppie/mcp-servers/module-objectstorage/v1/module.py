"""Object Storage Module v1 — Public API.

Entry point for v1 business logic. One public method per MCP tool.
Imports from sibling files for complex logic.

S3-compatibele objectopslag-module voor upload, download en verwijdering
van bestanden.
"""

import io
import logging
import os
import uuid
from typing import Any

import boto3
from botocore.config import Config as BotoConfig

logger = logging.getLogger("objectstorage-mcp.v1")


class ObjectStorageModule:
    """v1 business logic for S3-compatible object storage.

    All public methods correspond 1:1 to MCP tools defined in tools.py.
    """

    def __init__(self):
        self._endpoint_url = os.getenv("OBJECTSTORAGE_ENDPOINT_URL", "")
        self._access_key = os.getenv("OBJECTSTORAGE_ACCESS_KEY", "")
        self._secret_key = os.getenv("OBJECTSTORAGE_SECRET_KEY", "")
        self._bucket = os.getenv("OBJECTSTORAGE_BUCKET", "")
        self._region = os.getenv("OBJECTSTORAGE_REGION", "")
        self._prefix = os.getenv("OBJECTSTORAGE_PREFIX", "")

        self._client = None
        if self._endpoint_url and self._access_key and self._secret_key:
            self._client = boto3.client(
                "s3",
                endpoint_url=self._endpoint_url,
                aws_access_key_id=self._access_key,
                aws_secret_access_key=self._secret_key,
                region_name=self._region or "us-east-1",
                config=BotoConfig(
                    signature_version="s3v4",
                ),
            )
            logger.info("Object storage connected: %s", self._endpoint_url)
        else:
            logger.warning(
                "Object storage not configured — set OBJECTSTORAGE_ENDPOINT_URL, "
                "OBJECTSTORAGE_ACCESS_KEY, OBJECTSTORAGE_SECRET_KEY"
            )

    def _get_client(self):
        """Get S3 client or raise if not configured."""
        if not self._client:
            raise RuntimeError(
                "Object storage not configured — set OBJECTSTORAGE_ENDPOINT_URL, "
                "OBJECTSTORAGE_ACCESS_KEY, OBJECTSTORAGE_SECRET_KEY"
            )
        return self._client

    def _build_key(self, filename: str) -> str:
        """Build the full object key with optional prefix."""
        if self._prefix:
            return f"{self._prefix.rstrip('/')}/{filename}"
        return filename

    async def upload_object(
        self,
        bestand_pad: str,
        bestandsnaam: str = "",
        content_type: str = "application/octet-stream",
        user_id: str = "",
        project_id: str = "",
        session_id: str = "",
        app_id: str = "",
    ) -> dict[str, Any]:
        """Upload een bestand naar S3 en retourneer Object-Key."""
        client = self._get_client()

        if not bestandsnaam:
            bestandsnaam = os.path.basename(bestand_pad)

        # Generate unique key to avoid collisions
        object_key = self._build_key(f"{uuid.uuid4().hex[:8]}_{bestandsnaam}")

        with open(bestand_pad, "rb") as f:
            client.upload_fileobj(
                f,
                self._bucket,
                object_key,
                ExtraArgs={"ContentType": content_type},
            )

        logger.info("Uploaded %s → %s", bestandsnaam, object_key)

        return {
            "object_key": object_key,
            "bucket": self._bucket,
            "bestandsnaam": bestandsnaam,
        }

    async def get_object_url(
        self,
        object_key: str,
        geldigheid_seconden: int = 3600,
        user_id: str = "",
        project_id: str = "",
        session_id: str = "",
        app_id: str = "",
    ) -> dict[str, Any]:
        """Genereer tijdelijke signed URL voor download."""
        client = self._get_client()

        url = client.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": self._bucket,
                "Key": object_key,
            },
            ExpiresIn=geldigheid_seconden,
        )

        logger.info(
            "Generated signed URL for %s (expires in %ds)",
            object_key,
            geldigheid_seconden,
        )

        return {
            "url": url,
            "object_key": object_key,
            "geldigheid_seconden": geldigheid_seconden,
        }

    async def delete_object(
        self,
        object_key: str,
        user_id: str = "",
        project_id: str = "",
        session_id: str = "",
        app_id: str = "",
    ) -> dict[str, Any]:
        """Verwijder een object uit de bucket."""
        client = self._get_client()

        client.delete_object(
            Bucket=self._bucket,
            Key=object_key,
        )

        logger.info("Deleted object %s", object_key)

        return {
            "status": "deleted",
            "object_key": object_key,
        }
