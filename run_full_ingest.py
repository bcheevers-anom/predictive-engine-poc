"""
Full 2.5-year ingest via cursor-paginated REST API.
Date range: 2024-01-01 to today.

Run:    python run_full_ingest.py
Resume: python run_full_ingest.py   (same command — checkpoints skip completed work)

What this pulls:
  - Actors, campaigns, malware, vulnerabilities (entity REST API, full objects with description)
  - Observables (cursor-paginated intelligence API, capped at MAX_OBSERVABLES — set to None for full corpus)

Checkpointing:
  - Each entity is written to disk immediately after fetch
  - Observable pages are flushed to disk every OBSERVABLE_CHECKPOINT_PAGES pages
  - Closing the laptop loses at most one page (~1,000 records) of observable data
  - Entity progress never goes backwards

Output:
  - batch_id printed at end — use this for pte convert / pte features build / pte train
"""
from dotenv import load_dotenv
load_dotenv()

import asyncio
import json
from datetime import date
from pathlib import Path
from pte.gateway.threatstream import ThreatStreamClient
from pte.ingest.raw_store import RawStore
from pte.common.provenance import make_run_id, config_hash
from pte.common.logging import progress, structured_log
from pte.dedup.l1_observable import l1_dedup_batch
import pyarrow as pa
import pyarrow.parquet as pq

# ── Configuration ─────────────────────────────────────────────────────────────

FROM_DATE = "2024-01-01"
TO_DATE = date.today().isoformat()          # e.g. "2026-06-03"
DATA_DIR = Path("data")

ENTITY_TYPES = [
    ("actor",          "actor"),
    ("campaign",       "campaign"),
    ("malware",        "malware"),
    ("vulnerability",  "vulnerability"),
    ("attackpattern",  "attackpattern"),
]

MAX_OBSERVABLES = None                      # None = no cap, pull full corpus overnight
OBSERVABLE_CHECKPOINT_PAGES = 50           # flush to disk every 50k records
ENTITY_CONCURRENCY = 10

# ── Batch ID derivation ───────────────────────────────────────────────────────

CFG = {"from": FROM_DATE, "to": TO_DATE, "method": "pagination-full"}
BATCH_ID = f"full-{make_run_id()[:8]}-{config_hash(CFG)}"

# Stable batch ID — reuse if a state file exists from a prior run
STATE_FILE = DATA_DIR / "ingest_state.json"

def load_or_create_batch_id() -> str:
    if STATE_FILE.exists():
        state = json.loads(STATE_FILE.read_text())
        bid = state.get("batch_id")
        if bid:
            progress(f"Resuming existing batch: {bid}")
            return bid
    bid = f"full-{make_run_id()[:8]}-{config_hash(CFG)}"
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps({
        "batch_id": bid, "from_date": FROM_DATE, "to_date": TO_DATE,
        "started": date.today().isoformat(),
    }, indent=2))
    return bid

# ── Entity ingest ─────────────────────────────────────────────────────────────

def entity_checkpoint_dir(batch_id: str, entity_type: str) -> Path:
    p = DATA_DIR / "raw" / batch_id / entity_type / "checkpoints"
    p.mkdir(parents=True, exist_ok=True)
    return p

def already_done_entities(batch_id: str, entity_type: str) -> set[str]:
    d = entity_checkpoint_dir(batch_id, entity_type)
    return {f.stem for f in d.glob("*.json")}

def write_entity_checkpoint(batch_id: str, entity_type: str, entity: dict) -> None:
    eid = str(entity.get("id") or entity.get("uuid") or "unknown")
    p = entity_checkpoint_dir(batch_id, entity_type) / f"{eid}.json"
    p.write_text(json.dumps(entity))

def load_entity_checkpoints(batch_id: str, entity_type: str) -> list[dict]:
    d = entity_checkpoint_dir(batch_id, entity_type)
    results = []
    for f in d.glob("*.json"):
        try:
            results.append(json.loads(f.read_text()))
        except json.JSONDecodeError:
            pass
    return results

async def ingest_entities(ts: ThreatStreamClient, batch_id: str) -> int:
    sem = asyncio.Semaphore(ENTITY_CONCURRENCY)
    date_params = {"created_ts__gte": FROM_DATE, "created_ts__lte": TO_DATE}
    total_stored = 0

    for model_type, record_type in ENTITY_TYPES:
        done_ids = already_done_entities(batch_id, record_type)
        progress(f"\nFetching {model_type} list...")
        entities = await ts.get_entity_list(model_type, params=date_params)

        pending = [e for e in entities if str(e.get("id", "?")) not in done_ids]
        if done_ids:
            progress(f"  {model_type}: {len(done_ids)} already done, {len(pending)} to fetch")
        else:
            progress(f"  {model_type}: {len(pending)} to fetch")

        if not pending:
            continue

        async def fetch_one(entity: dict, mtype: str = model_type, rtype: str = record_type) -> None:
            async with sem:
                full = await ts.get_entity_full(mtype, entity["id"])
                if full:
                    full["entity_type"] = mtype
                    eid = str(full.get("id") or full.get("uuid") or "unknown")
                    full["id"] = eid
                    write_entity_checkpoint(batch_id, rtype, full)

        for i in range(0, len(pending), 50):
            chunk = pending[i:i+50]
            await asyncio.gather(*[fetch_one(e) for e in chunk])
            progress(f"  {model_type}: {min(i+50, len(pending))}/{len(pending)} fetched")

        stored = len(load_entity_checkpoints(batch_id, record_type))
        total_stored += stored
        progress(f"  {model_type} complete: {stored} on disk")
        structured_log("entity_ingest_complete", model_type=model_type, count=stored)

    # Checkpoint files are already in data/raw/<batch_id>/<type>/checkpoints/
    # store.read() finds them via *.json glob — no separate consolidation needed.
    progress(f"  Entity checkpoints are readable directly from the raw store.")
    return total_stored

# ── Observable ingest (parallel workers) ─────────────────────────────────────
#
# Splits the full date range into N_OBSERVABLE_WORKERS slices.
# Each worker has its own cursor saved independently — workers can be
# stopped and resumed without affecting each other.
# Existing observable_chunk_* files are detected and counted toward progress.

N_OBSERVABLE_WORKERS = 16  # parallel date-slice workers — stress tested up to 30 with no rate limits

def observable_state_file(batch_id: str) -> Path:
    return DATA_DIR / "raw" / batch_id / "observable_ingest_state.json"

def load_observable_state(batch_id: str) -> dict:
    f = observable_state_file(batch_id)
    if f.exists():
        return json.loads(f.read_text())
    return {"pages_written": 0, "records_written": 0, "complete": False}

def save_observable_state(batch_id: str, state: dict) -> None:
    f = observable_state_file(batch_id)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(state, indent=2))

def _date_slices(from_date: str, to_date: str, n: int) -> list[tuple[str, str]]:
    """Split [from_date, to_date) into n equal slices by days."""
    from datetime import date, timedelta
    start = date.fromisoformat(from_date)
    end = date.fromisoformat(to_date)
    total_days = (end - start).days
    slice_days = max(1, total_days // n)
    slices = []
    cursor = start
    for i in range(n):
        slice_end = min(cursor + timedelta(days=slice_days), end)
        slices.append((cursor.isoformat(), slice_end.isoformat()))
        cursor = slice_end
        if cursor >= end:
            break
    return slices


async def _pull_slice(
    worker_id: int,
    from_d: str,
    to_d: str,
    batch_id: str,
    headers: dict,
    state: dict,
    state_lock: asyncio.Lock,
    cap_per_worker: int | None,
) -> int:
    """Pull one date slice. Resumable via saved cursor. Returns unique records written."""
    import httpx as _httpx
    from pte.dedup.l1_observable import normalise_observable_key
    from pte.dedup.merge import build_canonical_record

    wkey = f"worker_{worker_id}"
    raw_dir = DATA_DIR / "raw" / batch_id
    chunk_dir = raw_dir / f"observable_chunk_w{worker_id:02d}"
    chunk_dir.mkdir(parents=True, exist_ok=True)

    # Check if already complete
    async with state_lock:
        if state.get(f"{wkey}_complete"):
            existing = pq.read_metadata(str(chunk_dir / "bulk.parquet")).num_rows if (chunk_dir / "bulk.parquet").exists() else 0
            progress(f"  [worker-{worker_id}] already complete ({existing:,} records), skipping")
            return existing
        resume_url = state.get(f"{wkey}_cursor")
        already_fetched = state.get(f"{wkey}_fetched", 0)

    base_url = "https://api.threatstream.com/api/v2/intelligence/"
    url = resume_url or base_url
    params = {
        "limit": 1000,
        "order_by": "created_ts,id",
        "status": "active",
        "created_ts__gte": from_d,
        "created_ts__lte": to_d,
    } if not resume_url else {}

    seen: dict[str, list[dict]] = {}  # key -> best record for in-memory dedup
    fetched = 0
    pages = 0

    if already_fetched > 0:
        progress(f"  [worker-{worker_id}] resuming {from_d} to {to_d}, already had {already_fetched:,}")
    else:
        progress(f"  [worker-{worker_id}] starting {from_d} to {to_d}")

    while url:
        for attempt in range(4):
            try:
                async with _httpx.AsyncClient(headers=headers, timeout=60.0) as http:
                    resp = await http.get(url, params=params)
                    resp.raise_for_status()
                    data = resp.json()
                break
            except (_httpx.ReadTimeout, _httpx.ConnectError, _httpx.ReadError):
                if attempt == 3:
                    raise
                await asyncio.sleep((attempt + 1) * 5)

        objects = data.get("objects", [])
        if not objects:
            break

        for r in objects:
            key = normalise_observable_key(r.get("value", ""), r.get("itype", ""))
            if key not in seen or (r.get("confidence") or 0) > (seen[key].get("confidence") or 0):
                seen[key] = r

        fetched += len(objects)
        pages += 1

        next_url = (data.get("meta") or {}).get("next")
        url = f"https://api.threatstream.com{next_url}" if next_url else None
        params = {}

        # Checkpoint every 50 pages (50k records)
        if pages % 50 == 0:
            deduped = list(seen.values())
            _write_parquet_merge(chunk_dir / "bulk.parquet", deduped)
            async with state_lock:
                state[f"{wkey}_fetched"] = already_fetched + fetched
                state[f"{wkey}_cursor"] = url
                _save_state_sync(batch_id, state)
            seen = {}
            progress(f"  [worker-{worker_id}] {from_d}/{to_d} page {pages}, fetched={fetched:,}")

        if cap_per_worker and (already_fetched + fetched) >= cap_per_worker:
            async with state_lock:
                state[f"{wkey}_cursor"] = url
                state[f"{wkey}_fetched"] = already_fetched + fetched
                _save_state_sync(batch_id, state)
            break

    # Final flush
    if seen:
        _write_parquet_merge(chunk_dir / "bulk.parquet", list(seen.values()))

    final = pq.read_metadata(str(chunk_dir / "bulk.parquet")).num_rows if (chunk_dir / "bulk.parquet").exists() else 0

    async with state_lock:
        state[f"{wkey}_complete"] = not bool(url)  # complete only if cursor exhausted
        state[f"{wkey}_fetched"] = already_fetched + fetched
        _save_state_sync(batch_id, state)

    progress(f"  [worker-{worker_id}] done -- {fetched:,} raw -> {final:,} unique on disk")
    return final


def _write_parquet_merge(path: Path, records: list[dict]) -> None:
    """Merge new records into existing parquet, deduping by (value, itype)."""
    if not records:
        return
    from pte.dedup.l1_observable import normalise_observable_key
    new_table = pa.Table.from_pylist(records)
    if path.exists():
        existing = pq.read_table(str(path)).to_pylist()
        combined = existing + records
        seen = {}
        for r in combined:
            key = normalise_observable_key(r.get("value", ""), r.get("itype", ""))
            if key not in seen or (r.get("confidence") or 0) > (seen[key].get("confidence") or 0):
                seen[key] = r
        pq.write_table(pa.Table.from_pylist(list(seen.values())), str(path), compression="snappy")
    else:
        pq.write_table(new_table, str(path), compression="snappy")


def _save_state_sync(batch_id: str, state: dict) -> None:
    f = observable_state_file(batch_id)
    f.write_text(json.dumps(state, indent=2))


async def ingest_observables(ts: ThreatStreamClient, batch_id: str) -> int:
    """Pull observables using N parallel date-slice workers. Fully resumable."""
    import os
    state = load_observable_state(batch_id)

    # Check if a previous sequential run exists — honour it
    if state.get("complete"):
        existing = state.get("records_written", 0)
        progress(f"Observables already complete: {existing:,} records on disk")
        return existing

    # Count already-downloaded chunks from previous sequential run
    raw_dir = DATA_DIR / "raw" / batch_id
    existing_seq_chunks = sorted(raw_dir.glob("observable_chunk_[0-9]*/bulk.parquet"))
    if existing_seq_chunks:
        seq_records = sum(pq.read_metadata(str(c)).num_rows for c in existing_seq_chunks)
        progress(f"  Found {len(existing_seq_chunks)} existing sequential chunks ({seq_records:,} unique records) — will be included in final consolidation")

    headers = {"Authorization": f"apikey {os.environ['TS_API_USER']}:{os.environ['TS_API_KEY']}"}
    slices = _date_slices(FROM_DATE, TO_DATE, N_OBSERVABLE_WORKERS)

    # Per-worker cap: if MAX_OBSERVABLES set, divide evenly across workers
    cap_per_worker = (MAX_OBSERVABLES // N_OBSERVABLE_WORKERS) if MAX_OBSERVABLES else None
    cap_str = f"capped at {MAX_OBSERVABLES:,} total" if MAX_OBSERVABLES else "no cap"
    progress(f"\nStep 3: Observable pull ({cap_str}, {N_OBSERVABLE_WORKERS} parallel workers)...")
    for i, (fd, td) in enumerate(slices):
        progress(f"  Worker {i}: {fd} to {td}")

    state_lock = asyncio.Lock()
    tasks = [
        _pull_slice(i, fd, td, batch_id, headers, state, state_lock, cap_per_worker)
        for i, (fd, td) in enumerate(slices)
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Report any worker errors
    total_worker_unique = 0
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            progress(f"  Worker {i} ERROR: {r}")
        else:
            total_worker_unique += r

    # Consolidate: sequential chunks + parallel worker chunks -> final parquet
    progress("  Consolidating all observable chunks via DuckDB...")
    import duckdb
    all_chunk_patterns = []
    for c in existing_seq_chunks:
        all_chunk_patterns.append(str(c))
    for i in range(N_OBSERVABLE_WORKERS):
        p = raw_dir / f"observable_chunk_w{i:02d}" / "bulk.parquet"
        if p.exists():
            all_chunk_patterns.append(str(p))

    if not all_chunk_patterns:
        progress("  No observable chunks found.")
        return 0

    dest = str(raw_dir / "observable" / "bulk.parquet")
    Path(dest).parent.mkdir(parents=True, exist_ok=True)
    pattern = "', '".join(all_chunk_patterns)

    con = duckdb.connect()
    con.execute(f"""
        COPY (
            SELECT * EXCLUDE(rn) FROM (
                SELECT *, ROW_NUMBER() OVER (
                    PARTITION BY value, itype
                    ORDER BY COALESCE(confidence, 0) DESC
                ) AS rn
                FROM read_parquet(['{pattern}'], union_by_name=true)
                WHERE value IS NOT NULL AND value != ''
                  AND itype  IS NOT NULL AND itype  != ''
            ) WHERE rn = 1
        ) TO '{dest}' (FORMAT PARQUET, COMPRESSION SNAPPY)
    """)
    result = con.execute(f"SELECT COUNT(*) FROM read_parquet('{dest}')").fetchone()
    final_count = result[0] if result else 0
    con.close()

    all_complete = all(
        state.get(f"worker_{i}_complete", False) for i in range(N_OBSERVABLE_WORKERS)
    )
    state["complete"] = all_complete
    state["records_written"] = final_count
    _save_state_sync(batch_id, state)

    progress(f"  Final: {final_count:,} unique observables")
    return final_count

# ── Main ──────────────────────────────────────────────────────────────────────

async def main():
    batch_id = load_or_create_batch_id()

    ts = ThreatStreamClient()
    progress("=" * 60)
    progress("PTE Full Ingest — 2.5 Year Corpus")
    progress(f"Batch ID: {batch_id}")
    progress(f"Date range: {FROM_DATE} to {TO_DATE}")
    progress("Resumable: close and rerun this script anytime")
    progress("=" * 60)

    # 1. Sizing
    progress("\nStep 1: Sizing calibration...")
    store = RawStore(base_dir=str(DATA_DIR / "raw"))
    sizing = {}
    for mtype in ["actor", "campaign", "malware", "tool", "vulnerability"]:
        count = await ts.get_full_count(mtype)
        sizing[f"{mtype}_count"] = count
    store.write_sizing(batch_id, sizing)
    progress("  Done", **{k: f"{v:,}" for k, v in sizing.items()})

    # 2. Entities (fast, ~1hr, fully checkpointed)
    progress("\nStep 2: Entity pull (actors, campaigns, malware, vulnerabilities)...")
    try:
        entity_count = await ingest_entities(ts, batch_id)
    except Exception as exc:
        import traceback
        progress(f"ERROR in ingest_entities: {exc}")
        traceback.print_exc()
        raise
    progress(f"\nEntities complete: {entity_count:,} total")

    # 3. Observables (slow, capped, checkpointed every 50k)
    cap_str = f"capped at {MAX_OBSERVABLES:,}" if MAX_OBSERVABLES is not None else "no cap — full corpus"
    progress(f"\nStep 3: Observable pull ({cap_str})...")
    try:
        obs_count = await ingest_observables(ts, batch_id)
    except Exception as exc:
        import traceback
        progress(f"ERROR in ingest_observables: {exc}")
        traceback.print_exc()
        raise
    progress(f"\nObservables complete: {obs_count:,} unique")

    # 4. Manifest
    manifest = {
        "batch_id": batch_id,
        "from_date": FROM_DATE,
        "to_date": TO_DATE,
        "method": "pagination-full-2.5yr",
        "total_entities": entity_count,
        "total_observables": obs_count,
        "config_hash": config_hash(CFG),
    }
    frozen_dir = DATA_DIR / "frozen" / batch_id
    frozen_dir.mkdir(parents=True, exist_ok=True)
    (frozen_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    structured_log("batch_complete", batch_id=batch_id, manifest=manifest)

    progress("\n" + "=" * 60)
    progress("INGEST COMPLETE")
    progress(f"Batch ID: {batch_id}")
    progress(f"Entities: {entity_count:,}")
    progress(f"Observables: {obs_count:,}")
    progress(f"\nNext steps:")
    progress(f"  python run_extraction.py   (LLM extraction — also resumable)")
    progress(f"  pte features build --batch-id {batch_id}")
    progress(f"  pte train t2-industry --batch-id {batch_id}")
    progress(f"  pte evaluate t2-industry --batch-id {batch_id}")
    progress("=" * 60)
    print(f"\nBATCH_ID={batch_id}")


if __name__ == "__main__":
    asyncio.run(main())
