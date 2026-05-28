"""DSP-ZGW Module v1 — Public API.

Entry point for v1 business logic. One public method per MCP tool.
Imports from sibling files for complex logic.

Connects to DSP zaaksysteem via ZGW-API (Zaken API 1.0 + Catalogi API 1.0).
"""

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger("dsp-zgw-mcp.v1")


class DSPZGWModule:
    """v1 business logic for DSP-ZGW zaaksysteem integration.

    All public methods correspond 1:1 to MCP tools defined in tools.py.
    """

    def __init__(self):
        self._base_url = os.getenv("DSP_ZGW_BASE_URL", "").rstrip("/")
        self._client_id = os.getenv("DSP_ZGW_CLIENT_ID", "")
        self._client_secret = os.getenv("DSP_ZGW_CLIENT_SECRET", "")
        self._catalogi_url = os.getenv("DSP_ZGW_CATALOGI_URL", self._base_url)

    def _get_headers(self) -> dict[str, str]:
        """Build request headers with authentication."""
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self._client_id and self._client_secret:
            headers["Authorization"] = f"Bearer {self._client_secret}"
        return headers

    async def create_zaak(
        self,
        zaaktype_url: str,
        beschrijving: str,
        locatie: str = "",
        metadata: str = "{}",
        user_id: str = "",
        project_id: str = "",
        session_id: str = "",
        app_id: str = "",
    ) -> dict[str, Any]:
        """Maak een zaak aan in DSP met zaaktype, beschrijving, locatie en metadata."""
        if not self._base_url:
            raise RuntimeError("DSP_ZGW_BASE_URL is not configured")

        zaken_url = f"{self._base_url}/zaken/api/v1/zaken"
        payload: dict[str, Any] = {
            "zaaktype": zaaktype_url,
            "beschrijving": beschrijving,
            "bronorganisatie": os.getenv("DSP_ZGW_BRONORGANISATIE", ""),
            "verantwoordelijkeOrganisatie": os.getenv(
                "DSP_ZGW_VERANTWOORDELIJKE_ORGANISATIE", ""
            ),
        }

        if locatie:
            import json

            try:
                locatie_data = json.loads(locatie)
                payload["zaakgeometrie"] = locatie_data
            except (json.JSONDecodeError, TypeError):
                payload["locatie"] = locatie

        if metadata and metadata != "{}":
            import json

            try:
                meta_data = json.loads(metadata)
                payload["eigenschappen"] = meta_data
            except (json.JSONDecodeError, TypeError):
                pass

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                zaken_url, json=payload, headers=self._get_headers()
            )
            response.raise_for_status()
            data = response.json()

        zaak_id = data.get("url", "")
        zaak_nummer = data.get("identificatie", "")

        logger.info("Created zaak %s (type=%s)", zaak_nummer, zaaktype_url)

        return {
            "zaak_url": zaak_id,
            "zaak_nummer": zaak_nummer,
            "status": data.get("status", ""),
            "registratiedatum": data.get("registratiedatum", ""),
        }

    async def get_zaak_status(
        self,
        zaak_url: str,
        user_id: str = "",
        project_id: str = "",
        session_id: str = "",
        app_id: str = "",
    ) -> dict[str, Any]:
        """Haal actuele zaakstatus op inclusief laatste opmerking en historie."""
        if not self._base_url:
            raise RuntimeError("DSP_ZGW_BASE_URL is not configured")

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(zaak_url, headers=self._get_headers())
            response.raise_for_status()
            zaak_data = response.json()

            status_url = zaak_data.get("status")
            status_info = ""
            if status_url:
                try:
                    status_resp = await client.get(
                        status_url, headers=self._get_headers()
                    )
                    status_resp.raise_for_status()
                    status_data = status_resp.json()
                    status_info = status_data.get("statustype", "")
                except httpx.HTTPError:
                    logger.warning("Could not fetch status details for %s", status_url)

            result = {
                "zaak_nummer": zaak_data.get("identificatie", ""),
                "status": status_info,
                "registratiedatum": zaak_data.get("registratiedatum", ""),
                "einddatum": zaak_data.get("einddatum", ""),
                "toelichting": zaak_data.get("toelichting", ""),
            }

        return result

    async def list_zaaktypen(
        self,
        catalogus_url: str = "",
        user_id: str = "",
        project_id: str = "",
        session_id: str = "",
        app_id: str = "",
    ) -> dict[str, Any]:
        """Geef beschikbare zaaktypen terug uit de DSP-catalogus."""
        if not self._catalogi_url:
            raise RuntimeError("DSP_ZGW_CATALOGI_URL is not configured")

        url = f"{self._catalogi_url}/catalogi/api/v1/zaaktypen"
        params: dict[str, str] = {}
        if catalogus_url:
            params["catalogus"] = catalogus_url

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, params=params, headers=self._get_headers())
            response.raise_for_status()
            data = response.json()

        zaaktypen = []
        results = data.get("results", data) if isinstance(data, dict) else data
        for zt in results:
            zaaktypen.append(
                {
                    "url": zt.get("url", ""),
                    "omschrijving": zt.get("omschrijving", ""),
                    "identificatie": zt.get("identificatie", ""),
                    "catalogus": zt.get("catalogus", ""),
                }
            )

        return {"zaaktypen": zaaktypen, "aantal": len(zaaktypen)}

    async def link_zaak_document(
        self,
        zaak_url: str,
        document_url: str,
        titel: str = "",
        user_id: str = "",
        project_id: str = "",
        session_id: str = "",
        app_id: str = "",
    ) -> dict[str, Any]:
        """Koppel een document (bijv. foto) aan een bestaande zaak."""
        if not self._base_url:
            raise RuntimeError("DSP_ZGW_BASE_URL is not configured")

        url = f"{self._base_url}/zaken/api/v1/zaakinformatieobjecten"
        payload = {
            "zaak": zaak_url,
            "informatieobject": document_url,
        }
        if titel:
            payload["titel"] = titel

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, json=payload, headers=self._get_headers())
            response.raise_for_status()
            data = response.json()

        logger.info("Linked document to zaak %s", zaak_url)

        return {
            "zaakinformatieobject_url": data.get("url", ""),
            "zaak": zaak_url,
            "informatieobject": document_url,
        }
