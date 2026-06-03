import os
from typing import AsyncIterator
import httpx

from pte.common.errors import CursorDriftError, RateLimitError
from pte.common.logging import structured_log, progress


class ThreatStreamClient:
    """Read-only ThreatStream REST client. No write methods implemented."""

    BASE = "https://api.threatstream.com"

    def __init__(self, api_user: str | None = None, api_key: str | None = None):
        self._user = api_user or os.environ["TS_API_USER"]
        self._key = api_key or os.environ["TS_API_KEY"]
        self._headers = {"Authorization": f"apikey {self._user}:{self._key}"}

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(headers=self._headers, timeout=60.0)

    async def iter_observables(
        self,
        params: dict | None = None,
        limit: int = 1000,
        max_retries: int = 3,
    ) -> AsyncIterator[list]:
        """Cursor-paginate /api/v2/intelligence/. Yields pages (lists of objects).

        Retries transient ReadTimeout / ConnectError up to max_retries times
        before giving up, so a single slow server response doesn't abort a
        multi-hour pull.
        """
        import asyncio as _asyncio
        url = f"{self.BASE}/api/v2/intelligence/"
        query = {**(params or {}), "limit": limit, "order_by": "created_ts,id"}
        async with self._client() as http:
            while url:
                for attempt in range(1, max_retries + 1):
                    try:
                        resp = await http.get(url, params=query)
                        break
                    except (httpx.ReadTimeout, httpx.ConnectError) as exc:
                        if attempt == max_retries:
                            raise
                        wait = attempt * 5
                        progress(f"  ReadTimeout on page — retrying in {wait}s (attempt {attempt}/{max_retries})")
                        await _asyncio.sleep(wait)
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
        page = 0
        async with self._client() as http:
            while True:
                resp = await http.get(url, params=query)
                resp.raise_for_status()
                data = resp.json()
                batch = data.get("objects", [])
                results.extend(batch)
                page += 1
                total = (data.get("meta") or {}).get("total_count", "?")
                if page == 1:
                    progress(f"Fetching {model_type} list", total=total)
                if not data.get("meta", {}).get("next"):
                    break
                query["offset"] = query.get("offset", 0) + 1000
                progress(f"  {model_type} list page {page}", fetched=len(results), total=total)
        progress(f"  {model_type} list complete", count=len(results))
        return results

    async def get_entity_full(self, model_type: str, entity_id: int | str) -> dict:
        """Fetch single full object (includes description body)."""
        url = f"{self.BASE}/api/v1/{model_type}/{entity_id}/"
        async with self._client() as http:
            resp = await http.get(url)
            if resp.status_code in (404, 400):
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
            count = data.get("meta", {}).get("total_count", 0)
            progress(f"  {model_type} count", total=count)
            return count
