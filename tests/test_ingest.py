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
