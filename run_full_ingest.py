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

MAX_OBSERVABLES = 1_000_000                 # cap to avoid multi-hour pulls
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

# ── Observable ingest ─────────────────────────────────────────────────────────

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

async def ingest_observables(ts: ThreatStreamClient, batch_id: str) -> int:
    state = load_observable_state(batch_id)
    if state.get("complete"):
        progress(f"Observables already complete: {state['records_written']:,} records on disk")
        return state["records_written"]

    already_written = state["records_written"]
    resume_cursor = state.get("next_cursor")  # saved cursor URL for exact resume

    if already_written > 0 and resume_cursor:
        progress(f"Resuming observables from cursor (skipping {already_written:,} already written)...")
    elif already_written > 0:
        progress(f"Resuming observables: {already_written:,} already written (no cursor — will re-fetch and dedup)")

    params = {
        "created_ts__gte": FROM_DATE,
        "created_ts__lte": TO_DATE,
        "status": "active",
    }

    store = RawStore(base_dir=str(DATA_DIR / "raw"))
    buffer: list[dict] = []
    page = state.get("pages_written", 0)  # continue page counter from last checkpoint
    total_fetched = already_written        # count already-written records toward cap
    chunk_number = state.get("chunks_written", 0)
    capped = False

    # If we have a saved cursor, pass it as the starting URL override
    iter_params = dict(params)
    if resume_cursor:
        # Pass cursor as a special override — iter_observables will use it as the first URL
        iter_params["_resume_cursor"] = resume_cursor

    async for records, next_cursor in ts.iter_observables_with_cursor(params=iter_params, limit=1000, resume_url=resume_cursor):
        buffer.extend(records)
        total_fetched += len(records)
        page += 1

        if page % 5 == 0:
            progress(f"  observables page {page}", fetched=f"{total_fetched:,}")

        # Checkpoint every OBSERVABLE_CHECKPOINT_PAGES pages
        if page % OBSERVABLE_CHECKPOINT_PAGES == 0:
            deduped = l1_dedup_batch(buffer)
            store.write_bulk(batch_id, f"observable_chunk_{chunk_number:04d}", deduped)
            chunk_number += 1
            already_written += len(deduped)
            buffer = []
            save_observable_state(batch_id, {
                "pages_written": page,
                "records_written": already_written,
                "chunks_written": chunk_number,
                "next_cursor": next_cursor,  # save exact cursor for clean resume
                "complete": False,
            })
            progress(f"  Checkpoint: {already_written:,} unique observables on disk so far")

        if MAX_OBSERVABLES is not None and total_fetched >= MAX_OBSERVABLES:
            # Save cursor so next run with higher cap resumes exactly here
            save_observable_state(batch_id, {
                "pages_written": page,
                "records_written": already_written,
                "chunks_written": chunk_number,
                "next_cursor": next_cursor,
                "complete": False,
                "capped_at": MAX_OBSERVABLES,
            })
            progress(f"  Cap of {MAX_OBSERVABLES:,} reached — stopping (raise MAX_OBSERVABLES and rerun to extend)")
            capped = True
            break

    # Write remaining buffer
    if buffer:
        deduped = l1_dedup_batch(buffer)
        store.write_bulk(batch_id, f"observable_chunk_{chunk_number:04d}", deduped)
        chunk_number += 1
        already_written += len(deduped)

    if not capped:
        # Consolidate all chunks into one final parquet
        progress("Consolidating observable chunks...")
        raw_dir = DATA_DIR / "raw" / batch_id
        all_records: list[dict] = []
        for chunk_file in sorted(raw_dir.glob("observable_chunk_*/bulk.parquet")):
            rows = pq.read_table(str(chunk_file)).to_pylist()
            all_records.extend(rows)

        final_deduped = l1_dedup_batch(all_records)
        store.write_bulk(batch_id, "observable", final_deduped)
        progress(f"  Final dedup: {len(all_records):,} raw -> {len(final_deduped):,} unique")

        save_observable_state(batch_id, {
            "pages_written": page,
            "records_written": len(final_deduped),
            "chunks_written": chunk_number,
            "next_cursor": None,
            "complete": True,
        })
        return len(final_deduped)
    else:
        # Capped — chunks are on disk, don't consolidate yet
        # next_cursor was already saved in the cap branch above
        return already_written

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
