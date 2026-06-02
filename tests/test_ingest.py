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
