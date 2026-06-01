# Ingest Method Fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give `pte ingest` three interchangeable methods — Snapshot API (existing, kept intact), REST Pagination API (new, reliable fallback), and Database File (new, for data-team-supplied exports) — selectable via a `--method` flag, all producing the same batch output contract.

**Architecture:** `FrozenBatchRunner.run()` currently hard-codes the Snapshot path. This plan extracts that path into `SnapshotIngestor`, adds `PaginationIngestor` (cursor-paginated REST, no timeout risk) and `DatabaseFileIngestor` (loads JSONL/JSON/CSV files dropped by the data team), and routes between them via a `--method` CLI flag. All three produce the same `data/frozen/<batch_id>/manifest.json` and `data/raw/<batch_id>/observable/bulk.parquet` — everything downstream (convert, features, train) is unchanged.

**Tech Stack:** Python 3.12, httpx (async REST), pydantic v2, pyarrow/parquet, pytest, click; existing `ThreatStreamClient`, `RawStore`, `l1_dedup_batch`, `progress`, `structured_log`.

---

## Context for the implementer

### Why three methods?

| Method | When to use | Status |
|---|---|---|
| `snapshot` | Would be fastest for large corpora if ThreatStream builds it promptly. Currently times out after 60 min for org 2956. Keep it — it may work in future. | Existing, broken for this org |
| `pagination` | Cursor-paginated REST. Reliably works. ~20–30 s for 9,500 observables + entities. **Primary fallback.** | New |
| `db-file` | Data team supplies JSONL/JSON/CSV files when API is unavailable. Pipeline loads them directly. | New |

### What does NOT change

- `data/raw/<batch_id>/` layout
- `data/frozen/<batch_id>/manifest.json` schema
- `RawStore`, `l1_dedup_batch`, `_parse_jsonl`
- Everything downstream: `convert`, `features`, `predict`, `explain`, API, UI

### What changes

- `src/pte/ingest/frozen_batch.py` — refactored: extract snapshot path, add method routing
- `src/pte/ingest/pagination_ingestor.py` — new
- `src/pte/ingest/db_file_ingestor.py` — new
- `src/pte/cli.py` — add `--method` flag to `pte ingest`
- `tests/test_ingest.py` — new tests for both new ingestors

### Key behavioural constraints

- **Read-only**: no write methods on `ThreatStreamClient`. This plan does not add any.
- **`--method snapshot`** must continue to work exactly as before — no behaviour change.
- **`--method pagination`** fetches: observables via `/api/v2/intelligence/` with `created_ts__gte` / `created_ts__lte` date filters; entities (actor, campaign, malware, vulnerability, attackpattern) via `/api/v1/threat_model_search/` with the same date filter; full single-object GETs for description bodies.
- **`--method db-file`** reads from a directory of files supplied externally. The user points at the directory; the ingestor loads every file it recognises.
- `pte ingest --method pagination` is the **default** going forward (replacing snapshot as default), since it is proven to work on this org.

---

## File Structure

```
src/pte/ingest/
├── frozen_batch.py          MODIFY — extract snapshot path; add method router
├── pagination_ingestor.py   CREATE — cursor-paginated REST ingestor
├── db_file_ingestor.py      CREATE — local file ingestor for data-team exports
└── raw_store.py             NO CHANGE

src/pte/cli.py               MODIFY — add --method flag, update default

tests/
└── test_ingest.py           MODIFY — add tests for both new ingestors
```

---

## Task 1: Extract the snapshot path into `SnapshotIngestor`

Refactor `FrozenBatchRunner.run()` so the snapshot logic lives in its own class with a clean interface. Nothing changes externally — this is pure extraction, no new behaviour. It is the structural prerequisite for adding the other methods.

**Files:**
- Modify: `src/pte/ingest/frozen_batch.py`

- [ ] **Step 1: Write a failing test that imports `SnapshotIngestor`**

Append to `tests/test_ingest.py`:
```python
from pte.ingest.frozen_batch import SnapshotIngestor

def test_snapshot_ingestor_exists():
    # Just confirms the class is importable with the right interface
    import inspect
    assert hasattr(SnapshotIngestor, "run")
    sig = inspect.signature(SnapshotIngestor.run)
    assert "batch_id" in sig.parameters
    assert "from_date" in sig.parameters
    assert "to_date" in sig.parameters
```

Run: `pytest tests/test_ingest.py::test_snapshot_ingestor_exists -v`
Expected: FAIL with `ImportError`

- [ ] **Step 2: Refactor `frozen_batch.py` to extract `SnapshotIngestor`**

Replace the contents of `src/pte/ingest/frozen_batch.py` with:

```python
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
        progress("=== Batch complete ===",
                 batch_id=batch_id,
                 observables=f"{stats.get('total_deduplicated', '?'):,}" if isinstance(stats.get('total_deduplicated'), int) else "?",
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
```

- [ ] **Step 3: Run test**

Run: `pytest tests/test_ingest.py -v`
Expected: all 3 tests PASS (including the new one)

- [ ] **Step 4: Commit**

```bash
git add src/pte/ingest/frozen_batch.py tests/test_ingest.py
git commit -m "refactor(ingest): extract SnapshotIngestor; add method routing to FrozenBatchRunner"
```

---

## Task 2: Implement `PaginationIngestor`

Cursor-paginated REST pull. Fetches observables via `/api/v2/intelligence/` with date filter, then fetches entity list + full objects for actor, campaign, malware, vulnerability, attackpattern. No timeout risk — each HTTP call is a single page of ≤1,000 records completing in <2 seconds.

**Files:**
- Create: `src/pte/ingest/pagination_ingestor.py`
- Modify: `tests/test_ingest.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_ingest.py`:
```python
from unittest.mock import AsyncMock, MagicMock, patch
from pte.ingest.pagination_ingestor import PaginationIngestor
from pte.ingest.raw_store import RawStore

@pytest.mark.asyncio
async def test_pagination_ingestor_fetches_observables(tmp_path):
    mock_ts = AsyncMock()
    # iter_observables yields two pages then stops
    async def fake_iter(params=None, limit=1000):
        yield [{"value": "1.1.1.1", "itype": "ip", "status": "active"}]
        yield [{"value": "2.2.2.2", "itype": "ip", "status": "active"}]
    mock_ts.iter_observables = fake_iter
    mock_ts.get_entity_list = AsyncMock(return_value=[])
    mock_ts.get_full_count = AsyncMock(return_value=2)

    store = RawStore(base_dir=str(tmp_path / "raw"))
    ingestor = PaginationIngestor(mock_ts, store, tmp_path)
    stats = await ingestor.run("batch001", "2026-05-01", "2026-06-01")

    assert stats["total_raw"] == 2
    assert stats["total_deduplicated"] == 2
    rows = store.read("batch001", "observable")
    assert len(rows) == 2

@pytest.mark.asyncio
async def test_pagination_ingestor_fetches_entities(tmp_path):
    mock_ts = AsyncMock()
    async def fake_iter(params=None, limit=1000):
        return
        yield  # make it an async generator
    mock_ts.iter_observables = fake_iter
    mock_ts.get_entity_list = AsyncMock(return_value=[{"id": "42", "name": "APT29"}])
    mock_ts.get_entity_full = AsyncMock(return_value={"id": "42", "name": "APT29", "description": "Russian actor"})

    store = RawStore(base_dir=str(tmp_path / "raw"))
    ingestor = PaginationIngestor(mock_ts, store, tmp_path)
    await ingestor.run("batch001", "2026-05-01", "2026-06-01")

    actors = store.read("batch001", "actor")
    assert len(actors) == 1
    assert actors[0]["name"] == "APT29"

@pytest.mark.asyncio
async def test_pagination_ingestor_respects_date_filter(tmp_path):
    """Verifies the date params are passed through to iter_observables."""
    mock_ts = AsyncMock()
    captured_params = {}
    async def fake_iter(params=None, limit=1000):
        captured_params.update(params or {})
        return
        yield
    mock_ts.iter_observables = fake_iter
    mock_ts.get_entity_list = AsyncMock(return_value=[])

    store = RawStore(base_dir=str(tmp_path / "raw"))
    ingestor = PaginationIngestor(mock_ts, store, tmp_path)
    await ingestor.run("batch001", "2026-05-18", "2026-06-01")

    assert captured_params.get("created_ts__gte") == "2026-05-18"
    assert captured_params.get("created_ts__lte") == "2026-06-01"
    assert captured_params.get("status") == "active"
```

Run: `pytest tests/test_ingest.py -k "pagination" -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 2: Write `src/pte/ingest/pagination_ingestor.py`**

```python
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

            # Pull full objects concurrently (description body only in single-object view)
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

            # Write each entity individually (supports per-record lookup by id)
            for entity in full_entities:
                entity_id = str(entity.get("id", entity.get("uuid", "unknown")))
                entity["id"] = entity_id
                self._store.write(batch_id, record_type, entity)

            progress(f"  {model_type} done", stored=len(full_entities))
            structured_log("pagination_entities_complete",
                           model_type=model_type, count=len(full_entities))
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/test_ingest.py -k "pagination" -v`
Expected: all 3 pagination tests PASS

- [ ] **Step 4: Run full test suite**

Run: `pytest tests/ -v`
Expected: all 52 + 3 new = 55 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/pte/ingest/pagination_ingestor.py tests/test_ingest.py
git commit -m "feat(ingest): PaginationIngestor — cursor-paginated REST with date filter, no snapshot timeout"
```

---

## Task 3: Implement `DatabaseFileIngestor`

Loads JSONL/JSON/CSV files supplied by the data team. The user points at a directory; the ingestor reads every recognised file and loads it into the raw store. Entity type is inferred from the filename (e.g. `campaigns.jsonl` → entity type `campaign`).

**Files:**
- Create: `src/pte/ingest/db_file_ingestor.py`
- Modify: `tests/test_ingest.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_ingest.py`:
```python
import csv
from pte.ingest.db_file_ingestor import DatabaseFileIngestor

@pytest.mark.asyncio
async def test_db_file_ingestor_loads_jsonl(tmp_path):
    # Create a fake data directory with observables.jsonl
    data_dir = tmp_path / "db_export"
    data_dir.mkdir()
    records = [
        {"value": "evil.com", "itype": "mal_domain", "status": "active"},
        {"value": "10.0.0.1", "itype": "ip", "status": "active"},
    ]
    (data_dir / "observables.jsonl").write_text(
        "\n".join(json.dumps(r) for r in records)
    )

    store = RawStore(base_dir=str(tmp_path / "raw"))
    ingestor = DatabaseFileIngestor(store, tmp_path, db_export_dir=str(data_dir))
    stats = await ingestor.run("batch001", "2026-05-01", "2026-06-01")

    rows = store.read("batch001", "observable")
    assert len(rows) == 2
    assert stats["total_raw"] == 2

@pytest.mark.asyncio
async def test_db_file_ingestor_loads_json_array(tmp_path):
    data_dir = tmp_path / "db_export"
    data_dir.mkdir()
    records = [{"id": "c1", "name": "APT Campaign", "description": "test"}]
    (data_dir / "campaigns.json").write_text(json.dumps(records))

    store = RawStore(base_dir=str(tmp_path / "raw"))
    ingestor = DatabaseFileIngestor(store, tmp_path, db_export_dir=str(data_dir))
    await ingestor.run("batch001", "2026-05-01", "2026-06-01")

    campaigns = store.read("batch001", "campaign")
    assert len(campaigns) == 1
    assert campaigns[0]["name"] == "APT Campaign"

@pytest.mark.asyncio
async def test_db_file_ingestor_loads_csv(tmp_path):
    data_dir = tmp_path / "db_export"
    data_dir.mkdir()
    csv_path = data_dir / "vulnerabilities.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "name", "cvss3_score", "epss_score"])
        writer.writeheader()
        writer.writerow({"id": "v1", "name": "CVE-2026-0001", "cvss3_score": "9.1", "epss_score": "0.043"})

    store = RawStore(base_dir=str(tmp_path / "raw"))
    ingestor = DatabaseFileIngestor(store, tmp_path, db_export_dir=str(data_dir))
    await ingestor.run("batch001", "2026-05-01", "2026-06-01")

    vulns = store.read("batch001", "vulnerability")
    assert len(vulns) == 1
    assert vulns[0]["name"] == "CVE-2026-0001"

@pytest.mark.asyncio
async def test_db_file_ingestor_missing_dir_raises(tmp_path):
    store = RawStore(base_dir=str(tmp_path / "raw"))
    ingestor = DatabaseFileIngestor(store, tmp_path, db_export_dir=str(tmp_path / "nonexistent"))
    with pytest.raises(FileNotFoundError):
        await ingestor.run("batch001", "2026-05-01", "2026-06-01")
```

Run: `pytest tests/test_ingest.py -k "db_file" -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 2: Write `src/pte/ingest/db_file_ingestor.py`**

```python
import csv
import json
from pathlib import Path

from pte.common.logging import progress, structured_log
from pte.dedup.l1_observable import l1_dedup_batch
from pte.ingest.raw_store import RawStore

# Maps filename stem (case-insensitive) to raw store record_type
_FILENAME_TO_RECORD_TYPE: dict[str, str] = {
    "observables":    "observable",
    "observable":     "observable",
    "campaigns":      "campaign",
    "campaign":       "campaign",
    "actors":         "actor",
    "actor":          "actor",
    "malware":        "malware",
    "vulnerabilities": "vulnerability",
    "vulnerability":  "vulnerability",
    "attack_patterns": "attackpattern",
    "attackpatterns": "attackpattern",
    "attackpattern":  "attackpattern",
    "sizing_counts":  "_sizing",   # special: written via write_sizing
    "sizing":         "_sizing",
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
        # Default: data/db_export/ — or pass an explicit path via --db-export-dir
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

        total_raw = 0
        total_deduplicated = 0
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
                # sizing_counts.json is a dict, not a list of records
                if isinstance(records, list) and len(records) == 1:
                    self._store.write_sizing(batch_id, records[0])
                elif isinstance(records, dict):
                    self._store.write_sizing(batch_id, records)
            elif record_type == "observable":
                obs_raw.extend(records)
            else:
                # Entity types — write individually
                for r in records:
                    rec_id = str(r.get("id") or r.get("uuid") or r.get("value") or "unknown")
                    r["id"] = rec_id
                    r.setdefault("entity_type", record_type)
                    self._store.write(batch_id, record_type, r)

            structured_log("db_file_loaded", file=file_path.name, count=len(records), record_type=record_type)

        # L1 dedup on observables
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

    # JSON object (e.g. sizing_counts.json)
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
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/test_ingest.py -k "db_file" -v`
Expected: all 4 db_file tests PASS

- [ ] **Step 4: Run full suite**

Run: `pytest tests/ -v`
Expected: all 55 + 4 new = 59 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/pte/ingest/db_file_ingestor.py tests/test_ingest.py
git commit -m "feat(ingest): DatabaseFileIngestor — load data-team JSONL/JSON/CSV exports"
```

---

## Task 4: Wire `--method` flag into the CLI

Update `pte ingest` to accept `--method` (default: `pagination`), `--db-export-dir` (for `db-file` method), and document the three options.

**Files:**
- Modify: `src/pte/cli.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_ingest.py`:
```python
from click.testing import CliRunner
from pte.cli import main

def test_cli_ingest_method_flag():
    runner = CliRunner()
    result = runner.invoke(main, ["ingest", "--help"])
    assert "--method" in result.output
    assert "pagination" in result.output
    assert "snapshot" in result.output
    assert "db-file" in result.output

def test_cli_ingest_rejects_unknown_method():
    runner = CliRunner()
    # --method is validated by click choices, so it should fail fast
    result = runner.invoke(main, [
        "ingest", "--from", "2026-05-01", "--to", "2026-06-01",
        "--method", "telepathy"
    ])
    assert result.exit_code != 0
```

Run: `pytest tests/test_ingest.py -k "cli_ingest" -v`
Expected: FAIL (no `--method` flag yet)

- [ ] **Step 2: Update `src/pte/cli.py`**

Replace the `ingest` command:

```python
@main.command()
@click.option("--from", "from_date", required=True, help="Start date inclusive, e.g. 2026-05-01")
@click.option("--to", "to_date", required=True, help="End date exclusive, e.g. 2026-06-01")
@click.option("--feeds", default=None, help="Comma-separated feed names or 'all'")
@click.option(
    "--method",
    default="pagination",
    type=click.Choice(["pagination", "snapshot", "db-file"], case_sensitive=False),
    show_default=True,
    help=(
        "pagination: cursor-paginated REST API (reliable, recommended). "
        "snapshot: ThreatStream Snapshot bulk export (may time out for large orgs). "
        "db-file: load files supplied by the data team (place in data/db_export/ or use --db-export-dir)."
    ),
)
@click.option(
    "--db-export-dir",
    default=None,
    help="Path to directory containing data-team export files. Only used with --method db-file. Defaults to data/db_export/.",
)
@click.option("--format", "fmt", default="json_v2", hidden=True, help="Snapshot format (snapshot method only)")
def ingest(from_date, to_date, feeds, method, db_export_dir, fmt):
    """Pull ThreatStream data into a frozen corpus.

    Three methods are available:\n
    \b
      pagination  Cursor-paginated REST API. Reliable. Recommended default.
                  Fetches observables + entities with date filter.
      snapshot    ThreatStream Snapshot bulk export. Fast for large corpora
                  if it completes, but may time out for large orgs (>60 min).
      db-file     Load files provided by the data team. Place files in
                  data/db_export/ before running, or specify --db-export-dir.
    """
    from pte.gateway.threatstream import ThreatStreamClient
    from pte.ingest.frozen_batch import FrozenBatchRunner

    feed_list = feeds.split(",") if feeds and feeds != "all" else None
    ts = ThreatStreamClient()

    if method == "db-file":
        # DatabaseFileIngestor doesn't need a live ThreatStream connection
        # but FrozenBatchRunner still calls get_full_count() for sizing.
        # Pass db_export_dir through to the runner.
        import asyncio
        from pte.ingest.db_file_ingestor import DatabaseFileIngestor
        from pte.ingest.raw_store import RawStore
        from pte.common.provenance import make_run_id, config_hash
        import json
        from pathlib import Path

        run_id = make_run_id()
        cfg = {"from": from_date, "to": to_date, "feeds": feed_list, "method": method}
        batch_id = f"{run_id[:8]}-{config_hash(cfg)}"
        data_dir = Path("data")
        store = RawStore(base_dir=str(data_dir / "raw"))
        db_dir = db_export_dir or str(data_dir / "db_export")

        async def run_db():
            from pte.common.logging import progress, structured_log
            progress("=== PTE Ingest (db-file) ===",
                     batch_id=batch_id, from_date=from_date, to_date=to_date)
            progress("Step 1/4  Sizing calibration skipped (no live API in db-file mode)")
            ingestor = DatabaseFileIngestor(store, data_dir, db_export_dir=db_dir)
            stats = await ingestor.run(batch_id, from_date, to_date)
            progress("Step 4/4  Writing manifest...")
            manifest = {
                "batch_id": batch_id, "run_id": run_id,
                "from_date": from_date, "to_date": to_date,
                "method": method, "config_hash": config_hash(cfg), **stats,
            }
            frozen_dir = data_dir / "frozen" / batch_id
            frozen_dir.mkdir(parents=True, exist_ok=True)
            (frozen_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
            structured_log("batch_complete", batch_id=batch_id, manifest=manifest)
            progress("=== Batch complete ===", batch_id=batch_id,
                     observables=f"{stats.get('total_deduplicated', '?'):,}" if isinstance(stats.get('total_deduplicated'), int) else "?",
                     method=method)
            return batch_id

        result_id = asyncio.run(run_db())
        click.echo(f"Batch complete: {result_id}")
    else:
        runner = FrozenBatchRunner(ts_client=ts)
        import asyncio
        batch_id = asyncio.run(
            runner.run(from_date=from_date, to_date=to_date,
                       feeds=feed_list, fmt=fmt, method=method)
        )
        click.echo(f"Batch complete: {batch_id}")
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/test_ingest.py -k "cli_ingest" -v`
Expected: both CLI tests PASS

- [ ] **Step 4: Smoke test the help output in a shell**

Run: `pte ingest --help`

Expected output includes:
```
  --method [pagination|snapshot|db-file]
                                  pagination: cursor-paginated REST API...
```

- [ ] **Step 5: Run full suite**

Run: `pytest tests/ -v`
Expected: all 59 + 2 new = 61 tests PASS

- [ ] **Step 6: Commit**

```bash
git add src/pte/cli.py tests/test_ingest.py
git commit -m "feat(cli): add --method flag to pte ingest with pagination/snapshot/db-file options"
```

---

## Task 5: Update README with the three methods

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Replace the ingest step in the quickstart**

In `README.md`, find the **Running the full pipeline** section. Replace step 1 (the single `pte ingest` command) with:

```markdown
### Step-by-step (example: 1 month, 3w train / 1w eval)

```bash
# Choose your ingest method:

# Method A — REST pagination (recommended, always works)
pte ingest --from 2026-05-01 --to 2026-06-01 --method pagination

# Method B — Snapshot (faster for large corpora, but may time out for some orgs)
pte ingest --from 2026-05-01 --to 2026-06-01 --method snapshot

# Method C — Data-team file drop (when API is unavailable)
#   1. Place files from the data team in data/db_export/:
#      observables.jsonl, campaigns.jsonl, actors.jsonl,
#      malware.jsonl, vulnerabilities.jsonl, attack_patterns.jsonl
#   2. Then run:
pte ingest --from 2026-05-01 --to 2026-06-01 --method db-file

# Each method prints the batch_id on completion, e.g.:
# Batch complete: a1b2c3d4-f5e6g7h8
export BATCH=<your-batch-id>
```
```

- [ ] **Step 2: Add a Method comparison table to README**

Add a new section just before **Configuration reference**:

```markdown
## Ingest methods

| Method | Command | When to use | Requires live API |
|---|---|---|---|
| `pagination` | `--method pagination` | Default. Cursor-paginated REST — reliable, no timeout risk, ~30s for a typical corpus | Yes |
| `snapshot` | `--method snapshot` | Bulk Snapshot API — faster for very large corpora if ThreatStream builds it in time. May time out (>60 min) for some org configurations | Yes |
| `db-file` | `--method db-file` | Data team has supplied export files. No API connection needed for the ingest step | No |

For `db-file`: place the files in `data/db_export/` (or specify `--db-export-dir <path>`). See `docs/data_request_threatstream_export.md` for the exact files and fields to request from the data team.
```

- [ ] **Step 3: Verify README renders correctly**

```bash
python -c "
import re
text = open('README.md').read()
assert '--method pagination' in text
assert '--method snapshot' in text
assert '--method db-file' in text
assert 'data/db_export' in text
print('README checks pass')
"
```

Expected: `README checks pass`

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: document three ingest methods (pagination, snapshot, db-file) in README"
```

---

## Task 6: Push and verify

- [ ] **Step 1: Run the full test suite one final time**

Run: `pytest tests/ -v`
Expected: 61 tests PASS

- [ ] **Step 2: Smoke test pagination method with live credentials**

```bash
# Requires: .env with TS_API_USER/TS_API_KEY, AWS SSO session active
pte ingest --from 2026-05-18 --to 2026-06-01 --method pagination
```

Expected terminal output (approximately):
```
[00:00] === PTE Ingest ===  batch_id=...  from_date=2026-05-18  to_date=2026-06-01  method=pagination
[00:00] Step 1/4  Sizing calibration...
[00:05]   Sizing done  actor_count=12,699  ...
[00:05] Step 2/4  Fetching observables via cursor pagination...
[00:06]   observables page 1  fetched=1,000
[00:07]   observables page 5  fetched=5,000
[00:10] Step 3/4  Running L1 dedup on observables...
[00:10]   L1 dedup complete  raw=9,xxx  unique=9,xxx  ...
[00:10]   Fetching actor entities...
...
[00:45] === Batch complete ===  batch_id=...  method=pagination
```

- [ ] **Step 3: Push**

```bash
git push
```

---

## Self-Review

**Spec coverage:**
- ✅ Snapshot method preserved intact — `SnapshotIngestor` wraps existing logic, `FrozenBatchRunner` routes to it when `method="snapshot"`
- ✅ REST pagination method — `PaginationIngestor` with date filter on observables and entities
- ✅ Database file method — `DatabaseFileIngestor` loading JSONL/JSON/CSV from a drop directory
- ✅ `--method` CLI flag with three choices and a sensible default (`pagination`)
- ✅ `--db-export-dir` override for non-default file locations
- ✅ All downstream unchanged — same manifest contract, same raw store layout
- ✅ README updated with all three methods documented

**Placeholder scan:** None found.

**Type consistency:**
- `SnapshotIngestor.run()`, `PaginationIngestor.run()`, `DatabaseFileIngestor.run()` all return `dict` with at minimum `total_raw: int` and `total_deduplicated: int` — used uniformly by `FrozenBatchRunner` to write the manifest.
- `_FILENAME_TO_RECORD_TYPE` maps to the same `record_type` strings used by `RawStore.write()` and `RawStore.read()` throughout the codebase.
