"""PDOK Geocode Module v1 — Public API.

Entry point for v1 business logic. One public method per MCP tool.
Wraps PDOK BAG/BGT REST API for address resolution.
"""

import logging
from typing import Any

import httpx

logger = logging.getLogger("pdok-geocode-mcp.v1")

# PDOK locatieserver endpoints
PDOK_REVERSE_URL = "https://api.pdok.nl/bzk/locatieserver/search/v3_1/reverse"
PDOK_SEARCH_URL = "https://api.pdok.nl/bzk/locatieserver/search/v3_1/free"


class PdokGeocodeModule:
    """v1 business logic for PDOK BAG/BGT address resolution.

    Provides reverse geocoding (coordinates to address) and address search
    (type-ahead for address fields).
    All public methods correspond 1:1 to MCP tools defined in tools.py.
    """

    def __init__(self):
        self._client = httpx.AsyncClient(timeout=15.0)

    async def reverse_geocode(
        self,
        lat: float,
        lon: float,
        user_id: str = "",
        project_id: str = "",
        session_id: str = "",
        app_id: str = "",
    ) -> dict[str, Any]:
        """Resolve coordinates to a BAG address.

        Args:
            lat: Latitude (WGS84).
            lon: Longitude (WGS84).

        Returns:
            Dictionary with straatnaam, huisnummer, huisletter, huisnummertoevoeging,
            postcode, woonplaatsnaam, and full address string.
        """
        params = {
            "lat": lat,
            "lon": lon,
            "type": "adres",
            "rows": 1,
        }
        response = await self._client.get(PDOK_REVERSE_URL, params=params)
        response.raise_for_status()
        data = response.json()

        docs = data.get("response", {}).get("docs", [])
        if not docs:
            return {
                "gevonden": False,
                "lat": lat,
                "lon": lon,
                "straatnaam": "",
                "huisnummer": "",
                "postcode": "",
                "woonplaatsnaam": "",
                "weergavenaam": "",
            }

        doc = docs[0]
        return {
            "gevonden": True,
            "lat": lat,
            "lon": lon,
            "straatnaam": doc.get("straatnaam", ""),
            "huisnummer": doc.get("huisnummer", ""),
            "huisletter": doc.get("huisletter", ""),
            "huisnummertoevoeging": doc.get("huisnummertoevoeging", ""),
            "postcode": doc.get("postcode", ""),
            "woonplaatsnaam": doc.get("woonplaatsnaam", ""),
            "weergavenaam": doc.get("weergavenaam", ""),
            "bag_id": doc.get("bag_adres_id", ""),
        }

    async def search_address(
        self,
        query: str,
        rows: int = 5,
        user_id: str = "",
        project_id: str = "",
        session_id: str = "",
        app_id: str = "",
    ) -> dict[str, Any]:
        """Search addresses by text input (type-ahead for address field).

        Args:
            query: Search text (partial address).
            rows: Maximum number of results to return (default 5, max 10).

        Returns:
            Dictionary with list of address suggestions.
        """
        if not query or len(query.strip()) < 2:
            raise ValueError("Search query must be at least 2 characters")

        rows = min(max(1, rows), 10)  # Clamp between 1 and 10

        params = {
            "q": query,
            "type": "adres",
            "rows": rows,
        }
        response = await self._client.get(PDOK_SEARCH_URL, params=params)
        response.raise_for_status()
        data = response.json()

        docs = data.get("response", {}).get("docs", [])
        resultaten = []
        for doc in docs:
            resultaten.append(
                {
                    "weergavenaam": doc.get("weergavenaam", ""),
                    "straatnaam": doc.get("straatnaam", ""),
                    "huisnummer": doc.get("huisnummer", ""),
                    "postcode": doc.get("postcode", ""),
                    "woonplaatsnaam": doc.get("woonplaatsnaam", ""),
                    "centroide_ll": doc.get("centroide_ll", ""),
                    "bag_id": doc.get("bag_adres_id", ""),
                }
            )

        return {
            "query": query,
            "aantal_resultaten": len(resultaten),
            "resultaten": resultaten,
        }
