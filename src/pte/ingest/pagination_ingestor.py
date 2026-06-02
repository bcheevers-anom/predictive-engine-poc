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

    async def run(self, batch_id: str, from_date: str, to_date: str) -> dict:
        """Fetch all data and write to the raw store. Returns stats dict."""
        obs_stats = await self._fetch_observables(batch_id, from_date, to_date)
        await self._fetch_entities(batch_id, from_date, to_date)
        return obs_stats

    async def _fetch_observables(self, batch_id: str, from_date: str, to_date: str) -> dict:
        progress("Step 2/4  Fetching observables via cursor pagination...")
        params = {
            "created_ts__gte": from_date,
            "created_ts__lte": to_date,
            "status": "active",
        }
        all_records: list[dict] = []
        page = 0
        async for records in self._ts.iter_observables(params=params, limit=1000):
            all_records.extend(records)
            page += 1
            if page % 5 == 0 or page == 1:
                progress(f"  observables page {page}", fetched=f"{len(all_records):,}")

        progress("Step 3/4  Running L1 dedup on observables...")
        deduped = l1_dedup_batch(all_records)
        dupes = len(all_records) - len(deduped)
        progress("  L1 dedup complete",
                 raw=f"{len(all_records):,}",
                 unique=f"{len(deduped):,}",
                 dupes_removed=f"{dupes:,}")
        self._store.write_bulk(batch_id, "observable", deduped)
        structured_log("pagination_observables_complete",
                       total_raw=len(all_records), total_deduplicated=len(deduped))
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
