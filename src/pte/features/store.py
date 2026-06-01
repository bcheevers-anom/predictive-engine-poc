from pathlib import Path
import pyarrow as pa
import pyarrow.parquet as pq
from pte.schema.tiers import TierPolicy, DataTier


class FeatureStore:
    def __init__(self, base_dir: str = "data/features"):
        self._base = Path(base_dir)

    def _path(self, batch_id: str, table_name: str) -> Path:
        p = self._base / batch_id
        p.mkdir(parents=True, exist_ok=True)
        return p / f"{table_name}.parquet"

    def write(self, batch_id: str, table_name: str, records: list[dict]) -> None:
        if not records:
            return
        table = pa.Table.from_pylist(records)
        pq.write_table(table, str(self._path(batch_id, table_name)), compression="snappy")

    def read(self, batch_id: str, table_name: str, tier_policy: TierPolicy | None = None) -> list[dict]:
        path = self._path(batch_id, table_name)
        if not path.exists():
            return []
        table = pq.read_table(str(path))
        rows = table.to_pylist()
        if tier_policy:
            rows = [r for r in rows if tier_policy.accepts(DataTier(r.get("tier", "OBSERVED")))]
        return rows
