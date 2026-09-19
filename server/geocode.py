"""Client for Code for Dayton's parcel geocoder (a separate service).

https://github.com/codefordayton/geocoder — a small FastAPI app over a SQLite
index of every Montgomery County parcel with its centroid. The MCP server is
one of its clients; other CfD projects use it directly.

Set GEOCODER_URL to the service base URL (Railway private networking in
production, e.g. http://geocoder.railway.internal:8080). Unset = tool
reports unavailable.
"""

from __future__ import annotations

import os
import re
from typing import Any

import httpx

GEOCODER_URL = os.environ.get("GEOCODER_URL", "").rstrip("/")
MAX_RESULTS = 25

# "275 Linden Avenue, Dayton, OH 45403" -> "275 LINDEN AVE"
_SUFFIXES = {
    "AVENUE": "AVE", "STREET": "ST", "ROAD": "RD", "DRIVE": "DR", "BOULEVARD": "BLVD",
    "LANE": "LN", "COURT": "CT", "PLACE": "PL", "CIRCLE": "CIR", "PARKWAY": "PKWY",
    "HIGHWAY": "HWY", "TERRACE": "TER", "TRAIL": "TRL", "PIKE": "PIKE", "WAY": "WAY",
}
_DIRS = {"NORTH": "N", "SOUTH": "S", "EAST": "E", "WEST": "W"}
_STRIP_TAIL = re.compile(r",.*$|\b(DAYTON|OHIO|OH)\b.*$|\b\d{5}(-\d{4})?\b.*$", re.IGNORECASE)


class GeocodeError(RuntimeError):
    pass


def normalize_address(text: str) -> str:
    """Reduce a free-text address to the geocoder's 'NBR DIR STREET SUFFIX' form."""
    s = _STRIP_TAIL.sub("", text.strip()).upper()
    s = re.sub(r"[.#]", " ", s)
    words = [w for w in s.split() if w]
    words = [_DIRS.get(w, _SUFFIXES.get(w, w)) for w in words]
    # Numbered street ordinals: "5TH" stays; "FIFTH" is how the County spells some — leave as typed.
    return " ".join(words)


class GeocoderClient:
    def __init__(self, base_url: str = GEOCODER_URL, timeout: float = 15.0):
        self.base_url = base_url
        self._http = httpx.AsyncClient(timeout=timeout, headers={"User-Agent": "OpenDayton MCP"}) if base_url else None

    @property
    def available(self) -> bool:
        return self._http is not None

    async def aclose(self) -> None:
        if self._http:
            await self._http.aclose()

    async def geocode(self, *, address: str | None = None, parcel_id: str | None = None, limit: int = 10) -> dict[str, Any]:
        if not self._http:
            raise GeocodeError("geocoder is not configured on this server (GEOCODER_URL unset)")
        if bool(address) == bool(parcel_id):
            raise GeocodeError("provide exactly one of address or parcel_id")
        params: dict[str, Any] = {"limit": max(1, min(int(limit), MAX_RESULTS))}
        query_used = None
        if parcel_id:
            params["parcel_id"] = parcel_id.strip().upper()
        else:
            query_used = normalize_address(address or "")
            if not query_used:
                raise GeocodeError("address is empty after normalization")
            params["address"] = query_used
        try:
            resp = await self._http.get(f"{self.base_url}/geocode", params=params)
        except httpx.HTTPError as e:
            raise GeocodeError(f"geocoder unreachable: {e}") from e
        if resp.status_code == 404:
            return {"query": query_used or parcel_id, "count": 0, "results": [],
                    "hint": "No parcel matched. Try just the house number and street name (e.g. '275 LINDEN'), without city or ZIP."}
        if resp.status_code >= 400:
            raise GeocodeError(f"geocoder error HTTP {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        return {
            "query": query_used or parcel_id,
            "count": data.get("count", 0),
            "results": data.get("results", []),
            "source": {
                "dataset": "Montgomery County parcel centroids (Code for Dayton geocoder)",
                "publisher": "Montgomery County Auditor GIS",
                "source_page": "https://gis.mcohio.org/server/rest/services/TestData/mc_parcel_polygon/FeatureServer/0",
            },
        }
