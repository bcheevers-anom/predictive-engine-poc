import json
import threading
from pathlib import Path


class Quarantine:
    def __init__(self):
        self._records: list[dict] = []
        self._lock = threading.Lock()

    def add(self, record_id: str, reason: str, context: dict | None = None) -> None:
        with self._lock:
            self._records.append({"record_id": record_id, "reason": reason, "context": context or {}})

    def count(self) -> int:
        return len(self._records)

    def rate(self, total: int) -> float:
        if total == 0:
            return 0.0
        return self.count() / total

    def dump(self, path: str) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(self._records, f, indent=2)
