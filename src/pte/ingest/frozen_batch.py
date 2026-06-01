import asyncio
import json
from pathlib import Path

from pte.common.provenance import make_run_id, config_hash
from pte.common.logging import structured_log
from pte.gateway.snapshot import SnapshotClient
from pte.gateway.threatstream import ThreatStreamClient
from pte.ingest.raw_store import RawStore
from pte.dedup.l1_observable import l1_dedup_batch


class FrozenBatchRunner:
    def __init__(
        self,
        ts_client: ThreatStreamClient,
        raw_store: RawStore | None = None,
        data_dir: str = "data",
    ):
        self._ts = ts_client
        self._store = raw_store or RawStore(base_dir=f"{data_dir}/raw")
        self._snapshot = SnapshotClient(ts_client)
        self._data_dir = Path(data_dir)

    async def run(
        self,
        from_date: str,
        to_date: str,
        feeds: list[str] | None = None,
        fmt: str = "json_v2",
    ) -> str:
        run_id = make_run_id()
        cfg = {"from": from_date, "to": to_date, "feeds": feeds}
        batch_id = f"{run_id[:8]}-{config_hash(cfg)}"
        structured_log("batch_start", batch_id=batch_id, from_date=from_date, to_date=to_date)

        # 1. Sizing calibration
        sizing = {}
        for mtype in ["actor", "campaign", "malware", "tool", "vulnerability"]:
            count = await self._ts.get_full_count(mtype)
            sizing[f"{mtype}_count"] = count
        self._store.write_sizing(batch_id, sizing)

        # 2. Snapshot
        snapshot_dir = str(self._data_dir / "snapshots" / batch_id)
        snapshot_id = await self._snapshot.request_snapshot(fmt=fmt)
        snapshot_data = await self._snapshot.poll_until_complete(snapshot_id)
        chunk_paths = await self._snapshot.download_chunks(snapshot_data, snapshot_dir)

        # 3. Parse and store with L1 dedup
        all_observables = []
        for chunk_path in chunk_paths:
            records = _parse_jsonl(chunk_path)
            all_observables.extend(records)

        deduped = l1_dedup_batch(all_observables)
        self._store.write_bulk(batch_id, "observable", deduped)

        # 4. Write frozen corpus manifest
        manifest = {
            "batch_id": batch_id,
            "run_id": run_id,
            "from_date": from_date,
            "to_date": to_date,
            "snapshot_id": snapshot_id,
            "total_raw": len(all_observables),
            "total_deduplicated": len(deduped),
            "config_hash": config_hash(cfg),
        }
        frozen_dir = self._data_dir / "frozen" / batch_id
        frozen_dir.mkdir(parents=True, exist_ok=True)
        (frozen_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
        structured_log("batch_complete", batch_id=batch_id, manifest=manifest)
        return batch_id


def _parse_jsonl(path: str) -> list[dict]:
    """Parse a file that is either a JSON array or newline-delimited JSON."""
    with open(path, encoding="utf-8", errors="replace") as f:
        content = f.read().strip()
    if not content:
        return []
    # JSON array format (ThreatStream custom export)
    if content.startswith("["):
        try:
            data = json.loads(content)
            return data if isinstance(data, list) else []
        except json.JSONDecodeError:
            pass
    # JSONL format — one record per line
    records = []
    for line in content.splitlines():
        line = line.strip()
        if line:
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return records
