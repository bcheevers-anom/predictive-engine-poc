import json
from pathlib import Path


def write_report(report: dict, batch_id: str, task_id: str, data_dir: str = "data") -> str:
    dest = Path(data_dir) / "models" / "reports" / batch_id
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / f"{task_id}_report.json"
    path.write_text(json.dumps(report, indent=2))
    return str(path)
