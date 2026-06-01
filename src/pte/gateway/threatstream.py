import os
from typing import AsyncIterator
import httpx

from pte.common.errors import CursorDriftError, RateLimitError
from pte.common.logging import structured_log


class ThreatStreamClient:
    """Read-only ThreatStream REST client. No write methods implemented."""

    BASE = "https://api.threatstream.com"

    def __init__(self, api_user: str | None = None, api_key: str | None = None):
        self._user = api_user or os.environ["TS_API_USER"]
        self._key = api_key or os.environ["TS_API_KEY"]
        self._headers = {"Authorization": f"apikey {self._user}:{self._key}"}

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(headers=self._headers, timeout=30.0)

    async def iter_observables(
        self,
        params: dict | None = None,
        limit: int = 1000,
    ) -> AsyncIterator[list]:
        """Cursor-paginate /api/v2/intelligence/. Yields pages (lists of objects)."""
        url = f"{self.BASE}/api/v2/intelligence/"
        query = {**(params or {}), "limit": limit, "order_by": "created_ts,id"}
        async with self._client() as http:
            while url:
                resp = await http.get(url, params=query)
                if resp.status_code == 429:
                    raise RateLimitError(backend="threatstream")
                resp.raise_for_status()
                data = resp.json()
                objects = data.get("objects", [])
                structured_log("observable_page", count=len(objects))
                yield objects
                next_url = (data.get("meta") or {}).get("next")
                if next_url:
                    url = f"{self.BASE}{next_url}"
                    query = {}  # next_url already contains query params
                else:
                    url = None

    async def get_entity_list(self, model_type: str, params: dict | None = None) -> list:
        url = f"{self.BASE}/api/v1/threat_model_search/"
        query = {**(params or {}), "model_type": model_type, "limit": 1000}
        results = []
        async with self._client() as http:
            while True:
                resp = await http.get(url, params=query)
                resp.raise_for_status()
                data = resp.json()
                results.extend(data.get("objects", []))
                if not data.get("meta", {}).get("next"):
                    break
                query["offset"] = query.get("offset", 0) + 1000
        return results

    async def get_entity_full(self, model_type: str, entity_id: int | str) -> dict:
        """Fetch single full object (includes description body)."""
        url = f"{self.BASE}/api/v1/{model_type}/{entity_id}/"
        async with self._client() as http:
            resp = await http.get(url)
            if resp.status_code == 404:
                return {}
            resp.raise_for_status()
            return resp.json()

    async def get_full_count(self, model_type: str) -> int:
        """Get true count via full_count=1 (never use capped live count)."""
        url = f"{self.BASE}/api/v1/threat_model_search/"
        async with self._client() as http:
            resp = await http.get(url, params={"model_type": model_type, "limit": 1, "full_count": 1})
            resp.raise_for_status()
            data = resp.json()
            return data.get("meta", {}).get("total_count", 0)
