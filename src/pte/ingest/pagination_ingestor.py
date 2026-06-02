import asyncio
import json
from pathlib import Path

from pte.common.logging import progress, structured_log
from pte.dedup.l1_observable import l1_dedup_batch
from pte.gateway.threatstream import ThreatStreamClient
from pte.ingest.raw_store import RawStore

# Entity types to fetch via the entity list + full-object API.
# Each tuple is (model_type, record_type_in_store).
_ENTITY_TYPES = [
    ("actor", "actor"),
    ("campaign", "campaign"),
    ("malware", "malware"),
    ("vulnerability", "vulnerability"),
    ("attackpattern", "attackpattern"),
]

# How many full-object GETs to run concurrently (polite default).
_ENTITY_CONCURRENCY = 10


class PaginationIngestor:
    """Ingest via cursor-paginated REST API — no snapshot, no timeout risk.

    Observables: GET /api/v2/intelligence/ with created_ts date filter.
    Entities:    GET /api/v1/threat_model_search/ list, then full single-object
                 GETs in batches for the description body.
    """

    def __init__(self, ts_client: ThreatStreamClient, store: RawStore, data_dir: Path):
        self._ts = ts_client
        self._store = store
        self._data_dir = data_dir

    async def run(
        self,
        batch_id: str,
        from_date: str,
        to_date: str,
        max_observables: int | None = None,
    ) -> dict:
        """Fetch all data and write to the raw store. Returns stats dict.

        max_observables: if set, stop pulling observables after this many records.
        Pages are checkpointed to disk every 50 pages so a crash doesn't lose work.
        """
        obs_stats = await self._fetch_observables(batch_id, from_date, to_date, max_observables)
        await self._fetch_entities(batch_id, from_date, to_date)
        return obs_stats

    async def _fetch_observables(
        self,
        batch_id: str,
        from_date: str,
        to_date: str,
        max_observables: int | None = None,
    ) -> dict:
        cap_msg = f" (capped at {max_observables:,})" if max_observables else ""
        progress(f"Step 2/4  Fetching observables via cursor pagination{cap_msg}...")
        params = {
            "created_ts__gte": from_date,
            "created_ts__lte": to_date,
            "status": "active",
        }

        CHECKPOINT_EVERY = 50  # flush to disk every 50 pages = 50k records
        all_records: list[dict] = []
        checkpoint_buffer: list[dict] = []
        page = 0
        total_written = 0
        capped = False

        async for records in self._ts.iter_observables(params=params, limit=1000):
            all_records.extend(records)
            checkpoint_buffer.extend(records)
            page += 1

            # Checkpoint to disk periodically so progress is never fully lost
            if page % CHECKPOINT_EVERY == 0:
                deduped_chunk = l1_dedup_batch(checkpoint_buffer)
                self._store.write_bulk(batch_id, f"observable_chunk_{page}", deduped_chunk)
                total_written += len(deduped_chunk)
                checkpoint_buffer = []
                progress(f"  checkpoint written", pages=page,
                         fetched=f"{len(all_records):,}", on_disk=f"{total_written:,}")

            if page % 5 == 0 or page == 1:
                progress(f"  observables page {page}", fetched=f"{len(all_records):,}")

            if max_observables and len(all_records) >= max_observables:
                progress(f"  cap of {max_observables:,} reached — stopping observable pull")
                capped = True
                break

        # Write any remaining buffer
        if checkpoint_buffer:
            deduped_chunk = l1_dedup_batch(checkpoint_buffer)
            self._store.write_bulk(batch_id, f"observable_chunk_{page}", deduped_chunk)
            total_written += len(deduped_chunk)

        # Consolidate all chunks into one final bulk parquet
        progress("Step 3/4  Consolidating and running final L1 dedup...")
        deduped = l1_dedup_batch(all_records)
        dupes = len(all_records) - len(deduped)
        progress("  L1 dedup complete",
                 raw=f"{len(all_records):,}",
                 unique=f"{len(deduped):,}",
                 dupes_removed=f"{dupes:,}",
                 capped=capped)
        self._store.write_bulk(batch_id, "observable", deduped)
        structured_log("pagination_observables_complete",
                       total_raw=len(all_records), total_deduplicated=len(deduped), capped=capped)
        return {"total_raw": len(all_records), "total_deduplicated": len(deduped)}

    async def _fetch_entities(self, batch_id: str, from_date: str, to_date: str) -> None:
        """Fetch entity lists then pull full objects (includes description body)."""
        date_params = {
            "created_ts__gte": from_date,
            "created_ts__lte": to_date,
        }
        sem = asyncio.Semaphore(_ENTITY_CONCURRENCY)

        for model_type, record_type in _ENTITY_TYPES:
            progress(f"  Fetching {model_type} entities...")
            entities = await self._ts.get_entity_list(model_type, params=date_params)
            if not entities:
                progress(f"  No {model_type} entities in date window")
                continue

            async def fetch_full(entity: dict, mtype: str = model_type) -> dict | None:
                async with sem:
                    full = await self._ts.get_entity_full(mtype, entity["id"])
                    if full:
                        full["entity_type"] = mtype
                    return full or None

            results = await asyncio.gather(
                *[fetch_full(e) for e in entities],
                return_exceptions=False,
            )
            full_entities = [r for r in results if r]

            for entity in full_entities:
                entity_id = str(entity.get("id", entity.get("uuid", "unknown")))
                entity["id"] = entity_id
                self._store.write(batch_id, record_type, entity)

            progress(f"  {model_type} done", stored=len(full_entities))
            structured_log("pagination_entities_complete",
                           model_type=model_type, count=len(full_entities))
