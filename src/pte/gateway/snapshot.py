import asyncio
import hashlib
import json
import time
from pathlib import Path
import httpx

from pte.common.errors import SnapshotError
from pte.common.logging import structured_log
from pte.gateway.threatstream import ThreatStreamClient


def verify_sha256(file_path: str, expected: str) -> bool:
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest() == expected


class SnapshotClient:
    MAX_CONCURRENT = 3  # Snapshot API limit: 3 concurrent per org

    def __init__(self, ts_client: ThreatStreamClient):
        self._ts = ts_client

    async def request_snapshot(
        self,
        fmt: str = "json_v2",
        chunk_ioc_count: int = 250000,
    ) -> str:
        """POST /api/v1/snapshot/ and return snapshot_id."""
        url = f"{self._ts.BASE}/api/v1/snapshot/"
        payload = {"format": fmt, "chunk_ioc_count": chunk_ioc_count}
        async with self._ts._client() as http:
            resp = await http.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            snapshot_id = data.get("id") or data.get("snapshot_id")
            if not snapshot_id:
                raise SnapshotError(f"No snapshot_id in response: {data}")
            structured_log("snapshot_requested", snapshot_id=snapshot_id)
            return str(snapshot_id)

    async def poll_until_complete(self, snapshot_id: str, poll_interval: float = 10.0, timeout: float = 3600.0) -> dict:
        """Poll GET /api/v1/snapshot/<id>/ until status=completed or error."""
        url = f"{self._ts.BASE}/api/v1/snapshot/{snapshot_id}/"
        deadline = time.monotonic() + timeout
        async with self._ts._client() as http:
            while time.monotonic() < deadline:
                resp = await http.get(url)
                resp.raise_for_status()
                data = resp.json()
                status = data.get("status")
                structured_log("snapshot_poll", snapshot_id=snapshot_id, status=status)
                if status == "completed":
                    if data.get("errors"):
                        raise SnapshotError(f"Snapshot errors: {data['errors']}")
                    return data
                if status in ("error", "failed"):
                    raise SnapshotError(f"Snapshot failed: {data}")
                await asyncio.sleep(poll_interval)
        raise SnapshotError(f"Snapshot {snapshot_id} timed out")

    async def download_chunks(self, snapshot_data: dict, dest_dir: str) -> list[str]:
        """Download all chunks within pre-signed URL TTL; verify sha256; return file paths."""
        chunks = snapshot_data.get("chunks", [])
        if not chunks:
            chunks = [snapshot_data]  # single-chunk snapshot

        dest = Path(dest_dir)
        dest.mkdir(parents=True, exist_ok=True)
        sem = asyncio.Semaphore(self.MAX_CONCURRENT)

        async def download_one(chunk: dict) -> str:
            url = chunk.get("download_url") or chunk.get("url")
            if not url:
                raise SnapshotError(f"No download URL in chunk: {chunk}")
            fname = dest / f"chunk_{chunk.get('id', 'single')}.jsonl"
            async with sem:
                async with httpx.AsyncClient(timeout=300.0) as http:
                    async with http.stream("GET", url) as resp:
                        resp.raise_for_status()
                        with open(fname, "wb") as f:
                            async for data in resp.aiter_bytes(65536):
                                f.write(data)

            expected_sha = chunk.get("sha256sum") or chunk.get("sha256")
            if expected_sha and not verify_sha256(str(fname), expected_sha):
                raise SnapshotError(f"SHA-256 mismatch for chunk {chunk.get('id')}")
            structured_log("chunk_downloaded", path=str(fname))
            return str(fname)

        paths = await asyncio.gather(*[download_one(c) for c in chunks])
        return list(paths)
