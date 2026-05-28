"""DSP ZGW Module v1 — Public API.

Entry point for v1 business logic. One public method per MCP tool.
Wraps DSP ZGW REST APIs (Zaken, Documenten, Catalogi).
"""

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger("dsp-zgw-mcp.v1")

ZGW_BASE_URL = os.getenv("ZGW_BASE_URL", "https://zaken.example.com")
ZGW_CLIENT_ID = os.getenv("ZGW_CLIENT_ID", "test-client")
ZGW_CLIENT_SECRET = os.getenv("ZGW_CLIENT_SECRET", "test-secret")


class DspZgwModule:
    """v1 business logic for DSP ZGW integration.

    Wraps the Zaken API, Documenten API, and Catalogi API endpoints.
    All public methods correspond 1:1 to MCP tools defined in tools.py.
    """

    def __init__(
        self,
        base_url: str | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
    ):
        self._base_url = (base_url or ZGW_BASE_URL).rstrip("/")
        self._client_id = client_id or ZGW_CLIENT_ID
        self._client_secret = client_secret or ZGW_CLIENT_SECRET
        self._headers = {
            "Content-Type": "application/json",
            "Client-Id": self._client_id,
            "Client-Secret": self._client_secret,
        }

    async def _request(self, method: str, path: str, json: dict | None = None) -> dict[str, Any]:
        """Make an HTTP request to the ZGW API."""
        url = f"{self._base_url}{path}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.request(method, url, json=json, headers=self._headers)
            response.raise_for_status()
            return response.json()

    async def create_zaak(
        self,
        zaaktype: str,
        beschrijving: str,
        locatie_lat: float,
        locatie_lon: float,
        metadata: dict[str, Any] | None = None,
        user_id: str = "",
        project_id: str = "",
        session_id: str = "",
        app_id: str = "",
    ) -> dict[str, Any]:
        """Create a new zaak in DSP via ZGW Zaken API."""
        payload: dict[str, Any] = {
            "zaaktype": zaaktype,
            "bronorganisatie": os.getenv("ZGW_BRONORGANISATIE", "000000000"),
            "verantwoordelijkeOrganisatie": os.getenv(
                "ZWG_VERANTWOORDELIJKE_ORGANISATIE", "000000000"
            ),
            "omschrijving": beschrijving,
            "zaakgeometrie": {
                "type": "Point",
                "coordinates": [locatie_lon, locatie_lat],
            },
        }
        if metadata:
            payload["eigenschappen"] = [{"naam": k, "waarde": str(v)} for k, v in metadata.items()]

        result = await self._request("POST", "/zaken/api/v1/zaken", json=payload)
        return {
            "zaak_id": result.get("identificatie", ""),
            "zaak_url": result.get("url", ""),
            "status": result.get("status", ""),
        }

    async def get_zaak_status(
        self,
        zaak_id: str,
        user_id: str = "",
        project_id: str = "",
        session_id: str = "",
        app_id: str = "",
    ) -> dict[str, Any]:
        """Retrieve the current status and last remark of a zaak."""
        result = await self._request("GET", f"/zaken/api/v1/zaken?identificatie={zaak_id}")
        zaken = result.get("results", [])
        if not zaken:
            return {"zaak_id": zaak_id, "status": "not_found", "opmerkingen": []}

        zaak = zaken[0]
        status_url = zaak.get("status")
        status_label = "onbekend"
        if status_url:
            try:
                status_data = await self._request("GET", status_url)
                statustype_url = status_data.get("statustype")
                if statustype_url:
                    statustype_data = await self._request("GET", statustype_url)
                    status_label = statustype_data.get("omschrijving", "onbekend")
            except httpx.HTTPError:
                logger.warning("Failed to fetch status details for zaak %s", zaak_id)

        return {
            "zaak_id": zaak_id,
            "status": status_label,
            "opmerkingen": zaak.get("opmerkingen", []),
        }

    async def get_zaaktypen(
        self,
        user_id: str = "",
        project_id: str = "",
        session_id: str = "",
        app_id: str = "",
    ) -> dict[str, Any]:
        """Retrieve available zaaktypen from DSP Catalogi API."""
        result = await self._request("GET", "/catalogi/api/v1/zaaktypen")
        zaaktypen = []
        for zt in result.get("results", []):
            zaaktypen.append(
                {
                    "url": zt.get("url", ""),
                    "identificatie": zt.get("identificatie", ""),
                    "omschrijving": zt.get("omschrijving", ""),
                }
            )
        return {"zaaktypen": zaaktypen}

    async def link_document_to_zaak(
        self,
        zaak_url: str,
        document_url: str,
        titel: str = "Bijlage",
        user_id: str = "",
        project_id: str = "",
        session_id: str = "",
        app_id: str = "",
    ) -> dict[str, Any]:
        """Link a document (e.g., photo) to an existing zaak via ZGW API."""
        payload = {
            "zaak": zaak_url,
            "informatieobject": document_url,
            "titel": titel,
            "aardRelatieWeergave": "legt vast",
        }
        result = await self._request("POST", "/zaken/api/v1/zaakinformatieobjecten", json=payload)
        return {
            "zaak_url": zaak_url,
            "document_url": document_url,
            "link_url": result.get("url", ""),
        }
