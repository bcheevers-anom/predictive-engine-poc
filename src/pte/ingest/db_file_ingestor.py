import csv
import json
from pathlib import Path

from pte.common.logging import progress, structured_log
from pte.dedup.l1_observable import l1_dedup_batch
from pte.ingest.raw_store import RawStore

# Maps filename stem (case-insensitive) to raw store record_type
_FILENAME_TO_RECORD_TYPE: dict[str, str] = {
    "observables":     "observable",
    "observable":      "observable",
    "campaigns":       "campaign",
    "campaign":        "campaign",
    "actors":          "actor",
    "actor":           "actor",
    "malware":         "malware",
    "vulnerabilities": "vulnerability",
    "vulnerability":   "vulnerability",
    "attack_patterns": "attackpattern",
    "attackpatterns":  "attackpattern",
    "attackpattern":   "attackpattern",
    "sizing_counts":   "_sizing",
    "sizing":          "_sizing",
}

_SUPPORTED_EXTENSIONS = {".jsonl", ".json", ".csv"}


class DatabaseFileIngestor:
    """Load data-team-supplied export files into the raw store.

    The data team drops files into a directory (db_export_dir) following the
    naming convention from docs/data_request_threatstream_export.md:
        observables.jsonl, campaigns.jsonl, actors.jsonl,
        malware.jsonl, vulnerabilities.jsonl, attack_patterns.jsonl,
        sizing_counts.json

    Supported formats: JSONL (one record per line), JSON array, CSV with header.
    The record type is inferred from the filename stem.
    """

    def __init__(self, store: RawStore, data_dir: Path, db_export_dir: str | None = None):
        self._store = store
        self._data_dir = data_dir
        self._export_dir = Path(db_export_dir) if db_export_dir else data_dir / "db_export"

    async def run(self, batch_id: str, from_date: str, to_date: str) -> dict:
        if not self._export_dir.exists():
            raise FileNotFoundError(
                f"DB export directory not found: {self._export_dir}\n"
                f"Place the data-team export files there before running with --method db-file.\n"
                f"Expected files: observables.jsonl, campaigns.jsonl, actors.jsonl, "
                f"malware.jsonl, vulnerabilities.jsonl, attack_patterns.jsonl"
            )

        progress(f"Step 2/4  Loading data-team export files from {self._export_dir}...")
        files = sorted(self._export_dir.iterdir())
        recognised = [f for f in files if f.suffix in _SUPPORTED_EXTENSIONS]
        if not recognised:
            raise FileNotFoundError(
                f"No recognised files (.jsonl, .json, .csv) found in {self._export_dir}"
            )

        obs_raw: list[dict] = []

        for file_path in recognised:
            stem = file_path.stem.lower()
            record_type = _FILENAME_TO_RECORD_TYPE.get(stem)
            if record_type is None:
                progress(f"  Skipping unrecognised file: {file_path.name} (stem '{stem}' not in known list)")
                continue

            records = _load_file(file_path)
            progress(f"  Loaded {file_path.name}", records=f"{len(records):,}", type=record_type)

            if record_type == "_sizing":
                if isinstance(records, list) and len(records) == 1:
                    self._store.write_sizing(batch_id, records[0])
                elif isinstance(records, dict):
                    self._store.write_sizing(batch_id, records)
            elif record_type == "observable":
                obs_raw.extend(records)
            else:
                for r in records:
                    rec_id = str(r.get("id") or r.get("uuid") or r.get("value") or "unknown")
                    r["id"] = rec_id
                    r.setdefault("entity_type", record_type)
                    self._store.write(batch_id, record_type, r)

            structured_log("db_file_loaded", file=file_path.name,
                           count=len(records), record_type=record_type)

        progress("Step 3/4  Running L1 dedup on observables...")
        deduped = l1_dedup_batch(obs_raw)
        dupes = len(obs_raw) - len(deduped)
        progress("  L1 dedup complete",
                 raw=f"{len(obs_raw):,}",
                 unique=f"{len(deduped):,}",
                 dupes_removed=f"{dupes:,}")
        self._store.write_bulk(batch_id, "observable", deduped)

        return {"total_raw": len(obs_raw), "total_deduplicated": len(deduped)}


def _load_file(path: Path) -> list[dict]:
    """Load a JSONL, JSON array, or CSV file into a list of dicts."""
    if path.suffix == ".csv":
        with open(path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            return list(reader)

    with open(path, encoding="utf-8", errors="replace") as f:
        content = f.read().strip()

    if not content:
        return []

    # JSON array
    if content.startswith("["):
        try:
            data = json.loads(content)
            return data if isinstance(data, list) else [data]
        except json.JSONDecodeError:
            pass

    # JSON object (e.g. sizing_counts.json — a dict, not a list)
    if content.startswith("{"):
        try:
            return [json.loads(content)]
        except json.JSONDecodeError:
            pass

    # JSONL
    records = []
    for line in content.splitlines():
        line = line.strip()
        if line:
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return records
