import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq


class RawStore:
    def __init__(self, base_dir: str = "data/raw"):
        self._base = Path(base_dir)

    def _path(self, batch_id: str, record_type: str) -> Path:
        p = self._base / batch_id / record_type
        p.mkdir(parents=True, exist_ok=True)
        return p

    def write(self, batch_id: str, record_type: str, record: dict) -> None:
        p = self._path(batch_id, record_type) / f"{record['id']}.json"
        p.write_text(json.dumps(record))

    def write_bulk(self, batch_id: str, record_type: str, records: list[dict]) -> None:
        if not records:
            return
        table = pa.Table.from_pylist(records)
        dest = self._path(batch_id, record_type) / "bulk.parquet"
        pq.write_table(table, str(dest), compression="snappy")

    def read(self, batch_id: str, record_type: str) -> list[dict]:
        p = self._path(batch_id, record_type)
        rows = []
        for f in p.glob("*.json"):
            rows.append(json.loads(f.read_text()))
        parquet_file = p / "bulk.parquet"
        if parquet_file.exists():
            table = pq.read_table(str(parquet_file))
            rows.extend(table.to_pylist())
        return rows

    def write_sizing(self, batch_id: str, sizing: dict) -> None:
        p = self._base / batch_id
        p.mkdir(parents=True, exist_ok=True)
        (p / "sizing.json").write_text(json.dumps(sizing))

    def read_sizing(self, batch_id: str) -> dict:
        p = self._base / batch_id / "sizing.json"
        if not p.exists():
            return {}
        return json.loads(p.read_text())
