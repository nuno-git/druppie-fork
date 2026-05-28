"""PDOK Module v1 — Public API.

Entry point for v1 business logic. One public method per MCP tool.
Imports from sibling files for complex logic.

Geocoding-module via PDOK BAG/BGT. Vertaalt coördinaten naar adressen
en ondersteunt adreszoekfuncties.
"""

import logging
import math
from typing import Any

import httpx

logger = logging.getLogger("pdok-mcp.v1")

# PDOK API endpoints
PDOK_LOCATE_URL = "https://api.pdok.nl/bzk/locatieserver/search/v3_1"
PDOK_SUGGEST_URL = "https://api.pdok.nl/bzk/locatieserver/search/v3_1/suggest"


class PDOKModule:
    """v1 business logic for PDOK geocoding.

    All public methods correspond 1:1 to MCP tools defined in tools.py.
    """

    def _rd_to_wgs84(self, x: float, y: float) -> tuple[float, float]:
        """Convert Rijksdriehoek (RD) coordinates to WGS84 (lat, lon).

        Uses simplified transformation. For production accuracy,
        consider using the official RD-transformation library.
        """
        # Approximate RD → WGS84 transformation
        dlat = (y - 463000) * 0.000008993
        dlon = (x - 155000) * 0.000008993 / math.cos(math.radians(52.0))
        lat = 52.0 + dlat * 1.11
        lon = 5.0 + dlon * 1.11
        return round(lat, 7), round(lon, 7)

    async def reverse_geocode(
        self,
        coordinaat: str,
        coord_systeem: str = "wgs84",
        user_id: str = "",
        project_id: str = "",
        session_id: str = "",
        app_id: str = "",
    ) -> dict[str, Any]:
        """Vertaal RD- of WGS84-coördinaten naar een BAG-adres."""
        try:
            parts = coordinaat.replace(" ", "").split(",")
            if len(parts) != 2:
                raise ValueError("Coordinaat moet 'lat,lon' of 'x,y' formaat hebben")
            c1, c2 = float(parts[0]), float(parts[1])
        except (ValueError, IndexError) as e:
            raise ValueError(f"Ongeldig coordinaat formaat: {e}")

        if coord_systeem.lower() == "rd":
            lat, lon = self._rd_to_wgs84(c1, c2)
        else:
            lat, lon = c1, c2

        params = {
            "q": f"POINT({lon} {lat})",
            "type": "adres",
            "rows": 1,
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(PDOK_LOCATE_URL, params=params)
            response.raise_for_status()
            data = response.json()

        docs = data.get("response", {}).get("docs", [])
        if not docs:
            return {
                "adres": "",
                "straat": "",
                "huisnummer": "",
                "postcode": "",
                "plaats": "",
                "gemeente": "",
                "bron": "pdok-bag",
            }

        doc = docs[0]
        return {
            "adres": doc.get("weergavenaam", ""),
            "straat": doc.get("straatnaam", ""),
            "huisnummer": doc.get("huis_nlt", ""),
            "postcode": doc.get("postcode", ""),
            "plaats": doc.get("woonplaatsnaam", ""),
            "gemeente": doc.get("gemeentenaam", ""),
            "bron": "pdok-bag",
        }

    async def search_address(
        self,
        zoekterm: str,
        max_resultaten: int = 5,
        user_id: str = "",
        project_id: str = "",
        session_id: str = "",
        app_id: str = "",
    ) -> dict[str, Any]:
        """Zoek adressen op tekstinput (type-ahead)."""
        if not zoekterm or len(zoekterm.strip()) < 2:
            raise ValueError("Zoekterm moet minimaal 2 tekens bevatten")

        params = {
            "q": zoekterm,
            "type": "adres",
            "rows": min(max_resultaten, 10),
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(PDOK_SUGGEST_URL, params=params)
            response.raise_for_status()
            data = response.json()

        docs = data.get("response", {}).get("docs", [])
        adressen = []
        for doc in docs:
            adressen.append(
                {
                    "adres": doc.get("weergavenaam", ""),
                    "id": doc.get("id", ""),
                    "type": doc.get("type", ""),
                    "score": doc.get("score", 0.0),
                }
            )

        return {"adressen": adressen, "aantal": len(adressen)}
