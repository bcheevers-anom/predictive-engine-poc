import asyncio
import hashlib
import json
import time
from pathlib import Path
import httpx

from pte.common.errors import SnapshotError
from pte.common.logging import structured_log, progress
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
        """POST /api/v1/snapshot/ and return snapshot_id.

        The format parameter is sent as a hint but some org configurations
        ignore it and produce a custom export format instead — that is fine,
        the download_chunks method handles both JSON arrays and JSONL.
        """
        url = f"{self._ts.BASE}/api/v1/snapshot/"
        # Send minimal payload; omit format if default — some orgs reject unknown values
        payload: dict = {}
        if fmt and fmt != "json_v2":
            payload["format"] = fmt
        if chunk_ioc_count != 250000:
            payload["chunk_ioc_count"] = chunk_ioc_count
        async with self._ts._client() as http:
            resp = await http.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            snapshot_id = data.get("id") or data.get("snapshot_id")
            if not snapshot_id:
                raise SnapshotError(f"No snapshot_id in response: {data}")
            structured_log("snapshot_requested", snapshot_id=snapshot_id)
            progress(f"Snapshot {snapshot_id} requested - waiting for ThreatStream to build it (typically 5-30 min)")
            return str(snapshot_id)

    async def poll_until_complete(self, snapshot_id: str, poll_interval: float = 10.0, timeout: float = 3600.0) -> dict:
        """Poll GET /api/v1/snapshot/<id>/ until status=completed or error."""
        url = f"{self._ts.BASE}/api/v1/snapshot/{snapshot_id}/"
        start = time.monotonic()
        deadline = start + timeout
        poll_count = 0
        # Report every N polls so the terminal isn't flooded
        REPORT_EVERY = 6  # every ~60 seconds
        async with self._ts._client() as http:
            while time.monotonic() < deadline:
                resp = await http.get(url)
                resp.raise_for_status()
                data = resp.json()
                status = data.get("status")
                poll_count += 1
                elapsed_s = int(time.monotonic() - start)
                remaining_s = int(deadline - time.monotonic())
                structured_log("snapshot_poll", snapshot_id=snapshot_id, status=status,
                               elapsed_s=elapsed_s, poll=poll_count)
                if status == "completed":
                    if data.get("errors"):
                        raise SnapshotError(f"Snapshot errors: {data['errors']}")
                    progress(f"Snapshot {snapshot_id} completed", elapsed_s=elapsed_s, polls=poll_count)
                    return data
                if status in ("error", "failed"):
                    raise SnapshotError(f"Snapshot failed: {data}")
                # Human-readable update every REPORT_EVERY polls
                if poll_count % REPORT_EVERY == 1 or poll_count == 1:
                    m, s = divmod(elapsed_s, 60)
                    rm, rs = divmod(remaining_s, 60)
                    progress(
                        f"Snapshot {snapshot_id} still building...",
                        waited=f"{m}m{s:02d}s",
                        timeout_in=f"{rm}m{rs:02d}s",
                    )
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
        n_chunks = len(chunks)
        progress(f"Downloading {n_chunks} chunk(s) to {dest_dir}")

        async def download_one(chunk: dict, idx: int) -> str:
            url = chunk.get("download_url") or chunk.get("url")
            if not url:
                raise SnapshotError(f"No download URL in chunk: {chunk}")
            chunk_id = chunk.get("id", "single")
            fname = dest / f"chunk_{chunk_id}.jsonl"
            dl_start = time.monotonic()
            bytes_written = 0
            async with sem:
                progress(f"  chunk {idx+1}/{n_chunks} starting download", chunk_id=chunk_id)
                async with httpx.AsyncClient(timeout=300.0) as http:
                    async with http.stream("GET", url) as resp:
                        resp.raise_for_status()
                        total = int(resp.headers.get("content-length", 0))
                        with open(fname, "wb") as f:
                            async for block in resp.aiter_bytes(65536):
                                f.write(block)
                                bytes_written += len(block)

            elapsed = time.monotonic() - dl_start
            mb = bytes_written / 1_048_576
            speed = mb / elapsed if elapsed > 0 else 0
            expected_sha = chunk.get("sha256sum") or chunk.get("sha256")
            if expected_sha:
                progress(f"  chunk {idx+1}/{n_chunks} verifying SHA-256…")
                if not verify_sha256(str(fname), expected_sha):
                    raise SnapshotError(f"SHA-256 mismatch for chunk {chunk_id}")
            structured_log("chunk_downloaded", path=str(fname), bytes=bytes_written)
            progress(
                f"  chunk {idx+1}/{n_chunks} done",
                size=f"{mb:.1f} MB",
                speed=f"{speed:.1f} MB/s",
                sha256="ok" if expected_sha else "n/a",
            )
            return str(fname)

        paths = await asyncio.gather(*[download_one(c, i) for i, c in enumerate(chunks)])
        return list(paths)
