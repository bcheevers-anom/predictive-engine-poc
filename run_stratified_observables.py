"""
Stratified observable pull — equal quarterly coverage with recency weighting.

Pulls a fixed quota of observables per quarter, running all quarters in
parallel (one async cursor per quarter). Respects ThreatStream's 5 req/s
rate limit via a shared semaphore.

Quotas (raw records — ~6:1 dedup ratio gives unique counts):
  Q1-Q4 2024:  500k each  →  ~83k unique each
  Q1-Q4 2025:    1M each  →  ~167k unique each
  Q1-Q2 2026:    2M each  →  ~333k unique each
  Total raw:    ~10M      →  ~1.6M unique

Skips quarters already sufficiently covered in the existing batch.

Run:     python run_stratified_observables.py
Resume:  python run_stratified_observables.py  (safe to re-run)
Test:    python run_stratified_observables.py --test  (2 quarters, 10k each)
"""
from dotenv import load_dotenv
load_dotenv()

import argparse
import asyncio
import json
import time
from pathlib import Path
from collections import defaultdict

import httpx
import pyarrow as pa
import pyarrow.parquet as pq

from pte.common.logging import progress, structured_log
from pte.dedup.l1_observable import l1_dedup_batch, normalise_observable_key
from pte.ingest.raw_store import RawStore

# ── Config ────────────────────────────────────────────────────────────────────

BATCH_ID = "full-a1f4ddec-bc3e44ce3e31"
DATA_DIR = Path("data")
BASE_URL = "https://api.threatstream.com"

# Quarter definitions: (label, from_date, to_date, target_raw_records)
QUARTERS = [
    # 2024 — baseline coverage (Q1 skipped — already well covered)
    ("Q2-2024", "2024-04-01", "2024-07-01", 500_000),
    ("Q3-2024", "2024-07-01", "2024-10-01", 500_000),
    ("Q4-2024", "2024-10-01", "2025-01-01", 500_000),
    # 2025 — more weight (more predictive)
    ("Q1-2025", "2025-01-01", "2025-04-01", 1_000_000),
    ("Q2-2025", "2025-04-01", "2025-07-01", 1_000_000),
    ("Q3-2025", "2025-07-01", "2025-10-01", 1_000_000),
    ("Q4-2025", "2025-10-01", "2026-01-01", 1_000_000),
    # 2026 — heaviest weight (most recent, most predictive)
    ("Q1-2026", "2026-01-01", "2026-04-01", 2_000_000),
    ("Q2-2026", "2026-04-01", "2026-06-05", 2_000_000),
]

TEST_QUARTERS = [
    ("Q2-2024-test", "2024-04-01", "2024-07-01", 10_000),
    ("Q1-2026-test", "2026-01-01", "2026-04-01", 10_000),
]

# ThreatStream rate limit: 5 req/s burst across all parallel workers
API_RATE_LIMIT = 5   # requests per second
PAGE_SIZE = 1000

# ── State management ──────────────────────────────────────────────────────────

def state_file() -> Path:
    return DATA_DIR / "raw" / BATCH_ID / "stratified_state.json"

def load_state() -> dict:
    f = state_file()
    return json.loads(f.read_text()) if f.exists() else {}

def save_state(state: dict) -> None:
    f = state_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(state, indent=2))

def quarter_parquet(label: str) -> Path:
    p = DATA_DIR / "raw" / BATCH_ID / f"strat_{label}"
    p.mkdir(parents=True, exist_ok=True)
    return p / "bulk.parquet"

# ── Rate-limited page fetcher ─────────────────────────────────────────────────

class RateLimitedFetcher:
    """Shared semaphore enforcing API_RATE_LIMIT req/s across all workers."""

    def __init__(self, api_user: str, api_key: str, rps: int = API_RATE_LIMIT):
        self._headers = {"Authorization": f"apikey {api_user}:{api_key}"}
        self._sem = asyncio.Semaphore(rps)
        self._last_requests: list[float] = []
        self._lock = asyncio.Lock()

    async def get(self, url: str, params: dict = None) -> dict:
        """Rate-limited GET — max API_RATE_LIMIT req/s globally."""
        async with self._sem:
            # Simple token bucket: ensure we don't exceed rps
            async with self._lock:
                now = time.monotonic()
                # Remove timestamps older than 1 second
                self._last_requests = [t for t in self._last_requests if now - t < 1.0]
                if len(self._last_requests) >= API_RATE_LIMIT:
                    wait = 1.0 - (now - self._last_requests[0])
                    if wait > 0:
                        await asyncio.sleep(wait)
                self._last_requests.append(time.monotonic())

            for attempt in range(4):
                try:
                    async with httpx.AsyncClient(
                        headers=self._headers, timeout=60.0
                    ) as http:
                        resp = await http.get(
                            url, params=params or {}
                        )
                        resp.raise_for_status()
                        return resp.json()
                except (httpx.ReadTimeout, httpx.ConnectError, httpx.ReadError) as e:
                    if attempt == 3:
                        raise
                    wait = (attempt + 1) * 5
                    await asyncio.sleep(wait)
        return {}

# ── Quarter puller ────────────────────────────────────────────────────────────

async def pull_quarter(
    label: str,
    from_date: str,
    to_date: str,
    target: int,
    fetcher: RateLimitedFetcher,
    state: dict,
) -> int:
    """Pull up to `target` records for one quarter. Returns count fetched."""

    pq_path = quarter_parquet(label)

    # Skip if already complete
    if state.get(f"{label}_complete"):
        existing = pq.read_metadata(str(pq_path)).num_rows if pq_path.exists() else 0
        progress(f"  [{label}] already complete ({existing:,} records), skipping")
        return existing

    # Resume from saved cursor if available
    resume_url = state.get(f"{label}_cursor")
    url = resume_url or f"{BASE_URL}/api/v2/intelligence/"
    params = {
        "limit": PAGE_SIZE,
        "order_by": "-created_ts,-id",  # newest first within each quarter
        "status": "active",
        "created_ts__gte": from_date,
        "created_ts__lte": to_date,
    } if not resume_url else {}

    records: list[dict] = []
    fetched = state.get(f"{label}_fetched", 0)
    pages = 0

    progress(f"  [{label}] starting — target={target:,}, already_fetched={fetched:,}")

    while url and fetched < target:
        data = await fetcher.get(url, params)
        objects = data.get("objects", [])
        if not objects:
            break

        records.extend(objects)
        fetched += len(objects)
        pages += 1

        next_url = (data.get("meta") or {}).get("next")
        url = f"{BASE_URL}{next_url}" if next_url else None
        params = {}  # cursor URL already has params

        if pages % 10 == 0:
            progress(f"  [{label}] page {pages}, fetched={fetched:,}/{target:,}")

        # Checkpoint every 50 pages
        if pages % 50 == 0:
            deduped = l1_dedup_batch(records)
            _append_parquet(pq_path, deduped)
            state[f"{label}_fetched"] = fetched
            state[f"{label}_cursor"] = url
            save_state(state)
            progress(f"  [{label}] checkpoint: {fetched:,} fetched, {len(deduped):,} unique flushed")
            records = []

    # Final flush
    if records:
        deduped = l1_dedup_batch(records)
        _append_parquet(pq_path, deduped)

    state[f"{label}_complete"] = True
    state[f"{label}_fetched"] = fetched
    state[f"{label}_cursor"] = None
    save_state(state)

    final_count = pq.read_metadata(str(pq_path)).num_rows if pq_path.exists() else 0
    progress(f"  [{label}] DONE -- {fetched:,} raw -> {final_count:,} unique")
    return final_count


def _append_parquet(path: Path, records: list[dict]) -> None:
    """Append records to a parquet file, creating it if needed."""
    if not records:
        return
    new_table = pa.Table.from_pylist(records)
    if path.exists():
        existing = pq.read_table(str(path))
        combined = pa.concat_tables([existing, new_table])
        # Final dedup on combined
        rows = combined.to_pylist()
        seen = {}
        for r in rows:
            key = normalise_observable_key(r.get("value", ""), r.get("itype", ""))
            if key not in seen:
                seen[key] = r
        pq.write_table(pa.Table.from_pylist(list(seen.values())), str(path), compression="snappy")
    else:
        pq.write_table(new_table, str(path), compression="snappy")

# ── Consolidate ───────────────────────────────────────────────────────────────

def consolidate(quarters: list[tuple]) -> int:
    """Merge all quarter parquets into the main observable table."""
    import duckdb
    raw_dir = DATA_DIR / "raw" / BATCH_ID

    # Collect all parquet paths: existing chunks + new stratified quarters
    sources = []
    # Existing pagination chunks
    for c in sorted(raw_dir.glob("observable_chunk_*/bulk.parquet")):
        sources.append(str(c))
    # New stratified quarters
    for label, *_ in quarters:
        p = quarter_parquet(label)
        if p.exists():
            sources.append(str(p))

    if not sources:
        progress("No parquet files to consolidate")
        return 0

    # Write to a separate file — does NOT overwrite observable/bulk.parquet
    # so run_full_ingest chunks are preserved and can be resumed independently
    dest = str(raw_dir / "observable_stratified" / "bulk.parquet")
    Path(dest).parent.mkdir(parents=True, exist_ok=True)

    pattern = "', '".join(sources)
    progress(f"Consolidating {len(sources)} parquet files via DuckDB...")

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
                FROM read_parquet(['{pattern}'], union_by_name=true)
                WHERE value IS NOT NULL AND value != ''
                  AND itype  IS NOT NULL AND itype  != ''
            )
            WHERE rn = 1
        ) TO '{dest}' (FORMAT PARQUET, COMPRESSION SNAPPY)
    """)
    result = con.execute(f"SELECT COUNT(*) FROM read_parquet('{dest}')").fetchone()
    count = result[0] if result else 0
    con.close()
    progress(f"Consolidation complete: {count:,} unique observables -> {dest}")
    progress(f"NOTE: observable/bulk.parquet (full pagination run) is untouched.")
    return count

# ── Main ──────────────────────────────────────────────────────────────────────

async def main(test_mode: bool = False) -> None:
    import os
    api_user = os.environ["TS_API_USER"]
    api_key = os.environ["TS_API_KEY"]

    quarters = TEST_QUARTERS if test_mode else QUARTERS

    if test_mode:
        progress("=== STRATIFIED PULL — TEST MODE (2 quarters, 10k each) ===")
        progress("Testing parallelism and rate limiting before full run.")
    else:
        progress("=== STRATIFIED OBSERVABLE PULL ===")
        progress(f"Pulling {len(quarters)} quarters in parallel")
        total_target = sum(q[3] for q in quarters)
        progress(f"Total target: {total_target:,} raw records")

    progress("")

    state = load_state()
    fetcher = RateLimitedFetcher(api_user, api_key)

    # Run all quarters in parallel
    t0 = time.monotonic()
    tasks = [
        pull_quarter(label, from_d, to_d, target, fetcher, state)
        for label, from_d, to_d, target in quarters
    ]
    results = await asyncio.gather(*tasks)
    elapsed = time.monotonic() - t0

    progress("")
    progress(f"All quarters complete in {elapsed/60:.1f} minutes")
    progress("")

    # Summary
    for (label, *_), count in zip(quarters, results):
        progress(f"  {label}: {count:,} unique records")

    if not test_mode:
        progress("")
        progress("Consolidating all data into final observable table...")
        total = consolidate(quarters)
        progress(f"Final corpus: {total:,} unique observables")

        # Update manifest
        manifest_path = DATA_DIR / "frozen" / BATCH_ID / "manifest.json"
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text())
            manifest["total_observables_stratified"] = total
            manifest["observable_stratified_path"] = "data/raw/full-a1f4ddec-bc3e44ce3e31/observable_stratified/bulk.parquet"
            manifest["stratified_quarters"] = [q[0] for q in quarters]
            manifest_path.write_text(json.dumps(manifest, indent=2))

    print(f"\nBATCH_ID={BATCH_ID}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Stratified observable pull")
    parser.add_argument("--test", action="store_true",
                        help="Test mode: 2 quarters, 10k records each")
    args = parser.parse_args()
    asyncio.run(main(test_mode=args.test))
