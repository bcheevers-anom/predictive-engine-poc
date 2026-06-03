"""
Download and process completed snapshot 8551547 (2024-01-01 onwards, json_v2 format).

Run:    python run_snapshot_download.py
Resume: python run_snapshot_download.py   (skips already-downloaded chunks)

The snapshot is currently in progress and producing chunks of 250k records each.
This script polls until complete then downloads all chunks with SHA-256 verification,
parses them, runs L1 dedup, and writes to the raw store.
"""
from dotenv import load_dotenv
load_dotenv()

import asyncio
import hashlib
import json
import time
from pathlib import Path

import httpx
import pyarrow as pa
import pyarrow.parquet as pq

from pte.common.logging import progress, structured_log
from pte.common.provenance import make_run_id, config_hash
from pte.dedup.l1_observable import l1_dedup_batch
from pte.ingest.raw_store import RawStore
from pte.ingest.frozen_batch import _parse_jsonl

SNAPSHOT_ID = "8551547"
DATA_DIR = Path("data")
BATCH_ID = f"snapshot-{SNAPSHOT_ID}"
MAX_CONCURRENT_DOWNLOADS = 3   # Snapshot API limit: 3 concurrent per org

def get_headers() -> dict:
    import os
    user = os.environ["TS_API_USER"]
    key = os.environ["TS_API_KEY"]
    return {"Authorization": f"apikey {user}:{key}"}

def verify_sha256(path: str, expected: str) -> bool:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest() == expected

def chunk_state_file() -> Path:
    p = DATA_DIR / "snapshots" / BATCH_ID
    p.mkdir(parents=True, exist_ok=True)
    return p / "download_state.json"

def load_state() -> dict:
    f = chunk_state_file()
    if f.exists():
        return json.loads(f.read_text())
    return {"downloaded_chunks": [], "processed_chunks": [], "complete": False}

def save_state(state: dict) -> None:
    chunk_state_file().write_text(json.dumps(state, indent=2))

async def poll_until_complete(snap_id: str) -> dict:
    """Poll snapshot until status=completed. Returns the completed snapshot dict."""
    headers = get_headers()
    url = f"https://api.threatstream.com/api/v1/snapshot/{snap_id}/"
    start = time.monotonic()
    poll = 0
    async with httpx.AsyncClient(headers=headers, timeout=30) as http:
        while True:
            resp = await http.get(url)
            resp.raise_for_status()
            data = resp.json()
            status = data.get("status")
            count = data.get("total_count", 0)
            files = len(data.get("files", []))
            elapsed = int(time.monotonic() - start)
            poll += 1
            if poll % 3 == 1:
                m, s = divmod(elapsed, 60)
                progress(f"  Snapshot {snap_id}: {status} — {count:,} records, {files} chunks ({m}m{s:02d}s elapsed)")
            if status == "completed":
                progress(f"  Snapshot COMPLETE: {count:,} records, {files} chunks, {elapsed}s total")
                return data
            if status == "errors":
                raise RuntimeError(f"Snapshot {snap_id} errored: {data.get('errors')}")
            await asyncio.sleep(10)

async def download_chunk(chunk: dict, idx: int, total: int, dest_dir: Path, state: dict) -> str | None:
    """Download one chunk file, verify SHA-256, return local path. Skip if already done."""
    chunk_id = chunk.get("id") or f"chunk_{idx:04d}"
    fname = dest_dir / f"chunk_{chunk_id}.json"

    if str(fname) in state.get("downloaded_chunks", []):
        progress(f"  Chunk {idx+1}/{total}: already downloaded, skipping")
        return str(fname)

    url = chunk.get("download_url")
    if not url:
        progress(f"  Chunk {idx+1}/{total}: no download URL, skipping")
        return None

    expected_sha = chunk.get("sha256sum")
    dl_start = time.monotonic()
    bytes_written = 0

    async with httpx.AsyncClient(timeout=600.0) as http:
        progress(f"  Chunk {idx+1}/{total}: downloading ({chunk.get('total_count', 0):,} records)...")
        async with http.stream("GET", url) as resp:
            resp.raise_for_status()
            with open(fname, "wb") as f:
                async for block in resp.aiter_bytes(65536):
                    f.write(block)
                    bytes_written += len(block)

    elapsed = time.monotonic() - dl_start
    mb = bytes_written / 1_048_576
    speed = mb / elapsed if elapsed > 0 else 0

    if expected_sha:
        progress(f"  Chunk {idx+1}/{total}: verifying SHA-256...")
        if not verify_sha256(str(fname), expected_sha):
            raise RuntimeError(f"SHA-256 mismatch for chunk {chunk_id}")

    structured_log("chunk_downloaded", chunk=chunk_id, bytes=bytes_written)
    progress(f"  Chunk {idx+1}/{total}: done — {mb:.1f} MB at {speed:.1f} MB/s, sha256=ok")

    state.setdefault("downloaded_chunks", []).append(str(fname))
    save_state(state)
    return str(fname)

async def process_chunks(chunk_paths: list[str], batch_id: str) -> int:
    """Parse chunk files and dedup incrementally — never loads more than 2 chunks at once.

    Strategy: dedup each chunk against a running seen-keys set (value::itype).
    This keeps memory proportional to unique records, not total records.
    50M raw records with ~10:1 dedup ratio = ~5M unique = ~5GB peak RAM, manageable.
    """
    from pte.dedup.l1_observable import normalise_observable_key
    from pte.dedup.merge import build_canonical_record
    from collections import defaultdict

    store = RawStore(base_dir=str(DATA_DIR / "raw"))
    state = load_state()

    progress("Step 3: Parsing and deduplicating chunks (streaming — low memory)...")

    # Running dedup state: key -> list of records (for merge)
    seen: dict[str, list[dict]] = defaultdict(list)
    total_raw = 0
    chunk_idx = 0
    FLUSH_EVERY = 20  # write a parquet chunk every 20 source chunks (~5M records)

    for path in chunk_paths:
        if path in state.get("processed_chunks", []):
            continue
        records = _parse_jsonl(path)
        total_raw += len(records)
        for r in records:
            key = normalise_observable_key(r.get("value", ""), r.get("itype", ""))
            seen[key].append(r)

        state.setdefault("processed_chunks", []).append(path)
        save_state(state)
        progress(f"  Parsed {Path(path).name}: {len(records):,} records  (unique keys so far: {len(seen):,})")

        # Periodically flush to parquet to keep RAM bounded
        if len(state.get("processed_chunks", [])) % FLUSH_EVERY == 0:
            deduped_chunk = [build_canonical_record(group) for group in seen.values()]
            store.write_bulk(batch_id, f"snapshot_chunk_{chunk_idx:04d}", deduped_chunk)
            chunk_idx += 1
            progress(f"  Flushed {len(deduped_chunk):,} unique records to disk (freeing memory)")
            seen.clear()

    # Final flush
    if seen:
        deduped_chunk = [build_canonical_record(group) for group in seen.values()]
        store.write_bulk(batch_id, f"snapshot_chunk_{chunk_idx:04d}", deduped_chunk)
        chunk_idx += 1

    # Detect parquet chunks on disk (covers resume case where loop was skipped)
    raw_dir_check = DATA_DIR / "raw" / batch_id
    existing_pq = sorted(raw_dir_check.glob("snapshot_chunk_*/bulk.parquet"))
    if len(existing_pq) > chunk_idx:
        chunk_idx = len(existing_pq)

    # Consolidate all snapshot parquet chunks using DuckDB — handles data larger than RAM
    progress(f"  Consolidating {chunk_idx} parquet chunks using DuckDB (out-of-core dedup)...")
    import duckdb
    raw_dir = DATA_DIR / "raw" / batch_id
    chunk_pattern = str(raw_dir / "snapshot_chunk_*/bulk.parquet")

    dest_parquet = str(raw_dir / "observable" / "bulk.parquet")
    Path(dest_parquet).parent.mkdir(parents=True, exist_ok=True)

    # DuckDB: read all chunks, dedup by (value, itype), keep highest-confidence record, write parquet
    # This runs entirely out-of-core — no Python RAM spike
    con = duckdb.connect()
    con.execute(f"""
        COPY (
            SELECT * EXCLUDE(rn)
            FROM (
                SELECT *,
                       ROW_NUMBER() OVER (
                           PARTITION BY value, itype
                           ORDER BY COALESCE(confidence, 0) DESC
                       ) AS rn
                FROM read_parquet('{chunk_pattern}', union_by_name=true)
                WHERE value IS NOT NULL AND value != ''
                  AND itype IS NOT NULL AND itype != ''
            )
            WHERE rn = 1
        ) TO '{dest_parquet}' (FORMAT PARQUET, COMPRESSION SNAPPY)
    """)
    result = con.execute(f"SELECT COUNT(*) FROM read_parquet('{dest_parquet}')").fetchone()
    final_count = result[0] if result else 0
    con.close()

    progress(f"  DuckDB dedup complete: {final_count:,} unique records written to {dest_parquet}")
    structured_log("snapshot_observables_stored", total_raw=total_raw, total_deduplicated=final_count)
    return final_count

async def main():
    progress("=" * 60)
    progress(f"PTE Snapshot Download — Snapshot {SNAPSHOT_ID}")
    progress(f"Batch ID: {BATCH_ID}")
    progress(f"Format: json_v2, filter: created_ts >= 2024-01-01")
    progress("Resumable: close and rerun this script anytime")
    progress("=" * 60)

    state = load_state()
    if state.get("complete"):
        progress("Download already complete per state file.")
        return BATCH_ID

    dest_dir = DATA_DIR / "snapshots" / BATCH_ID
    dest_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: Wait for snapshot to complete
    headers = get_headers()
    progress("\nStep 1: Polling snapshot until complete...")
    async with httpx.AsyncClient(headers=headers, timeout=30) as http:
        r = await http.get(f"https://api.threatstream.com/api/v1/snapshot/{SNAPSHOT_ID}/")
        snap_data = r.json()

    if snap_data.get("status") != "completed":
        progress(f"  Currently: {snap_data.get('status')} — {snap_data.get('total_count', 0):,} records, {len(snap_data.get('files', []))} chunks so far")
        progress("  Waiting for completion...")
        snap_data = await poll_until_complete(SNAPSHOT_ID)
    else:
        count = snap_data.get("total_count", 0)
        files = len(snap_data.get("files", []))
        progress(f"  Already complete: {count:,} records, {files} chunks")

    chunks = snap_data.get("files", [])
    if not chunks:
        chunks = [snap_data] if snap_data.get("download_url") else []

    progress(f"\nStep 2: Downloading {len(chunks)} chunk(s)...")
    sem = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)

    async def bounded_download(chunk: dict, idx: int) -> str | None:
        async with sem:
            return await download_chunk(chunk, idx, len(chunks), dest_dir, state)

    paths = await asyncio.gather(*[bounded_download(c, i) for i, c in enumerate(chunks)])
    valid_paths = [p for p in paths if p]

    if not valid_paths:
        raise RuntimeError("No chunks downloaded successfully")

    # Step 3: Parse, dedup, store
    n_unique = await process_chunks(valid_paths, BATCH_ID)

    # Step 4: Write manifest
    manifest = {
        "batch_id": BATCH_ID,
        "snapshot_id": SNAPSHOT_ID,
        "from_date": "2024-01-01",
        "to_date": "2026-06-03",
        "method": "snapshot",
        "format": "json_v2",
        "total_raw": snap_data.get("total_count", 0),
        "total_deduplicated": n_unique,
        "chunks": len(chunks),
    }
    frozen_dir = DATA_DIR / "frozen" / BATCH_ID
    frozen_dir.mkdir(parents=True, exist_ok=True)
    (frozen_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))

    state["complete"] = True
    save_state(state)
    structured_log("snapshot_download_complete", batch_id=BATCH_ID, manifest=manifest)

    progress("\n" + "=" * 60)
    progress("SNAPSHOT DOWNLOAD COMPLETE")
    progress(f"Batch ID: {BATCH_ID}")
    progress(f"Unique observables: {n_unique:,}")
    progress(f"\nNOTE: Snapshot contains OBSERVABLES only.")
    progress(f"Entity data (actors/campaigns/malware) is being pulled")
    progress(f"in parallel by run_full_ingest.py")
    progress("=" * 60)
    print(f"\nSNAPSHOT_BATCH_ID={BATCH_ID}")
    return BATCH_ID


if __name__ == "__main__":
    asyncio.run(main())
