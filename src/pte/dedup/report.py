import json
from pathlib import Path


def write_dedup_report(batch_id: str, stats: dict, data_dir: str = "data") -> str:
    dest = Path(data_dir) / "coverage" / batch_id
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / "dedup_report.json"
    path.write_text(json.dumps(stats, indent=2))
    return str(path)
