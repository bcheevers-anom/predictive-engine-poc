import json
import pytest
from pathlib import Path
from pte.ingest.raw_store import RawStore

def test_raw_store_write_read(tmp_path):
    store = RawStore(base_dir=str(tmp_path))
    record = {"id": "test_1", "value": "10.0.0.1", "itype": "ip"}
    store.write("batch_001", "observable", record)
    rows = store.read("batch_001", "observable")
    assert any(r["id"] == "test_1" for r in rows)

def test_raw_store_records_sizing(tmp_path):
    store = RawStore(base_dir=str(tmp_path))
    store.write_sizing("batch_001", {"snapshot_total": 50000, "actor_count": 120})
    sizing = store.read_sizing("batch_001")
    assert sizing["snapshot_total"] == 50000


from pte.ingest.frozen_batch import SnapshotIngestor
import inspect


def test_snapshot_ingestor_exists():
    assert hasattr(SnapshotIngestor, "run")
    sig = inspect.signature(SnapshotIngestor.run)
    assert "batch_id" in sig.parameters
    assert "from_date" in sig.parameters
    assert "to_date" in sig.parameters


def test_frozen_batch_runner_method_param():
    import inspect
    from pte.ingest.frozen_batch import FrozenBatchRunner
    sig = inspect.signature(FrozenBatchRunner.run)
    assert "method" in sig.parameters
    assert sig.parameters["method"].default == "pagination"


def test_frozen_batch_runner_unknown_method_raises():
    import asyncio
    from unittest.mock import AsyncMock
    from pte.ingest.frozen_batch import FrozenBatchRunner
    mock_ts = AsyncMock()
    mock_ts.get_full_count = AsyncMock(return_value=100)
    runner = FrozenBatchRunner(ts_client=mock_ts, data_dir="/tmp/test_pte")
    with pytest.raises(ValueError, match="Unknown ingest method"):
        asyncio.run(runner.run("2026-05-01", "2026-06-01", method="telepathy"))


from unittest.mock import AsyncMock
from pte.ingest.pagination_ingestor import PaginationIngestor

@pytest.mark.asyncio
async def test_pagination_ingestor_fetches_observables(tmp_path):
    mock_ts = AsyncMock()
    async def fake_iter(params=None, limit=1000):
        yield [{"value": "1.1.1.1", "itype": "ip", "status": "active"}]
        yield [{"value": "2.2.2.2", "itype": "ip", "status": "active"}]
    mock_ts.iter_observables = fake_iter
    mock_ts.get_entity_list = AsyncMock(return_value=[])

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
        yield
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


import csv as csv_module
from pte.ingest.db_file_ingestor import DatabaseFileIngestor

@pytest.mark.asyncio
async def test_db_file_ingestor_loads_jsonl(tmp_path):
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
        writer = csv_module.DictWriter(f, fieldnames=["id", "name", "cvss3_score", "epss_score"])
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
