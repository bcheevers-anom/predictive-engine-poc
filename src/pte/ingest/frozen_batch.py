import asyncio
import json
from pathlib import Path

from pte.common.provenance import make_run_id, config_hash
from pte.common.logging import structured_log, progress
from pte.gateway.snapshot import SnapshotClient
from pte.gateway.threatstream import ThreatStreamClient
from pte.ingest.raw_store import RawStore
from pte.dedup.l1_observable import l1_dedup_batch


class SnapshotIngestor:
    """Ingest observables via the ThreatStream Snapshot bulk export API."""

    def __init__(self, ts_client: ThreatStreamClient, store: RawStore, data_dir: Path):
        self._ts = ts_client
        self._store = store
        self._snapshot = SnapshotClient(ts_client)
        self._data_dir = data_dir

    async def run(self, batch_id: str, from_date: str, to_date: str, fmt: str = "json_v2") -> dict:
        """Pull observables via snapshot. Returns stats dict with total_raw and total_deduplicated."""
        progress("Step 2/4  Requesting snapshot from ThreatStream...")
        snapshot_dir = str(self._data_dir / "snapshots" / batch_id)
        snapshot_id = await self._snapshot.request_snapshot(fmt=fmt)
        snapshot_data = await self._snapshot.poll_until_complete(snapshot_id)
        chunk_paths = await self._snapshot.download_chunks(snapshot_data, snapshot_dir)

        progress("Step 3/4  Parsing snapshot and running L1 dedup...")
        all_observables = []
        for chunk_path in chunk_paths:
            records = _parse_jsonl(chunk_path)
            all_observables.extend(records)
            progress(f"  Parsed {chunk_path}", records=f"{len(records):,}")

        deduped = l1_dedup_batch(all_observables)
        dupes = len(all_observables) - len(deduped)
        progress("  L1 dedup complete",
                 raw=f"{len(all_observables):,}",
                 unique=f"{len(deduped):,}",
                 dupes_removed=f"{dupes:,}")
        self._store.write_bulk(batch_id, "observable", deduped)
        return {
            "snapshot_id": snapshot_id,
            "total_raw": len(all_observables),
            "total_deduplicated": len(deduped),
        }


class FrozenBatchRunner:
    def __init__(
        self,
        ts_client: ThreatStreamClient,
        raw_store: RawStore | None = None,
        data_dir: str = "data",
    ):
        self._ts = ts_client
        self._store = raw_store or RawStore(base_dir=f"{data_dir}/raw")
        self._data_dir = Path(data_dir)

    async def run(
        self,
        from_date: str,
        to_date: str,
        feeds: list[str] | None = None,
        fmt: str = "json_v2",
        method: str = "pagination",
    ) -> str:
        run_id = make_run_id()
        cfg = {"from": from_date, "to": to_date, "feeds": feeds, "method": method}
        batch_id = f"{run_id[:8]}-{config_hash(cfg)}"
        structured_log("batch_start", batch_id=batch_id,
                       from_date=from_date, to_date=to_date, method=method)
        progress("=== PTE Ingest ===", batch_id=batch_id,
                 from_date=from_date, to_date=to_date, method=method)

        # 1. Sizing calibration (all methods)
        progress("Step 1/4  Sizing calibration (true counts via full_count=1)...")
        sizing = {}
        for mtype in ["actor", "campaign", "malware", "tool", "vulnerability"]:
            count = await self._ts.get_full_count(mtype)
            sizing[f"{mtype}_count"] = count
        self._store.write_sizing(batch_id, sizing)
        progress("  Sizing done", **{k: f"{v:,}" for k, v in sizing.items()})

        # 2+3. Pull data — method-dependent
        if method == "snapshot":
            ingestor = SnapshotIngestor(self._ts, self._store, self._data_dir)
            stats = await ingestor.run(batch_id, from_date, to_date, fmt=fmt)
        elif method == "pagination":
            from pte.ingest.pagination_ingestor import PaginationIngestor
            ingestor = PaginationIngestor(self._ts, self._store, self._data_dir)
            stats = await ingestor.run(batch_id, from_date, to_date)
        elif method == "db-file":
            from pte.ingest.db_file_ingestor import DatabaseFileIngestor
            ingestor = DatabaseFileIngestor(self._store, self._data_dir)
            stats = await ingestor.run(batch_id, from_date, to_date)
        else:
            raise ValueError(f"Unknown ingest method '{method}'. Choose: snapshot, pagination, db-file")

        # 4. Write manifest
        progress("Step 4/4  Writing manifest...")
        manifest = {
            "batch_id": batch_id,
            "run_id": run_id,
            "from_date": from_date,
            "to_date": to_date,
            "method": method,
            "config_hash": config_hash(cfg),
            **stats,
        }
        frozen_dir = self._data_dir / "frozen" / batch_id
        frozen_dir.mkdir(parents=True, exist_ok=True)
        (frozen_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
        structured_log("batch_complete", batch_id=batch_id, manifest=manifest)
        total_dedup = stats.get("total_deduplicated")
        progress("=== Batch complete ===",
                 batch_id=batch_id,
                 observables=f"{total_dedup:,}" if isinstance(total_dedup, int) else "?",
                 method=method)
        return batch_id


def _parse_jsonl(path: str) -> list[dict]:
    """Parse a file that is either a JSON array or newline-delimited JSON."""
    with open(path, encoding="utf-8", errors="replace") as f:
        content = f.read().strip()
    if not content:
        return []
    if content.startswith("["):
        try:
            data = json.loads(content)
            return data if isinstance(data, list) else []
        except json.JSONDecodeError:
            pass
    records = []
    for line in content.splitlines():
        line = line.strip()
        if line:
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return records
