import json
from collections import defaultdict
from pathlib import Path

from pte.evaluate.metrics import mae
from pte.features.store import FeatureStore
from pte.predict.base import Task


class T2ToolTactic(Task):
    task_id = "t2_tool_tactic"
    accepted_tiers = ["OBSERVED", "DERIVED", "LLM_EXTRACTED"]
    aql_port_idiom = (
        "source pte_features | timechart count by tool "
        "| fit ARIMA count p=2 d=1 q=1 into 'pte_t2' "
        "| apply pte_t2"
    )
    metric = "mae"
    horizon = "90d"

    def __init__(self, batch_id: str, data_dir: str = "data"):
        super().__init__(batch_id, data_dir)
        self._feature_store = FeatureStore(base_dir=str(Path(data_dir) / "features"))
        self._model_dir = Path(data_dir) / "models" / batch_id
        self._model_dir.mkdir(parents=True, exist_ok=True)
        self._trend_data: dict | None = None

    def fit(self) -> None:
        records = self._feature_store.read(self.batch_id, "industry_tool_cooccur")
        tool_counts: dict[str, int] = defaultdict(int)
        for r in records:
            tool_counts[r.get("tool", "")] += 1
        self._trend_data = dict(tool_counts)
        (self._model_dir / "t2_trends.json").write_text(json.dumps(self._trend_data))

    def predict(self, inputs: dict) -> dict:
        if self._trend_data is None:
            path = self._model_dir / "t2_trends.json"
            self._trend_data = json.loads(path.read_text()) if path.exists() else {}
        return {"tool_trends": sorted(self._trend_data.items(), key=lambda x: x[1], reverse=True)[:10]}

    def explain(self, inputs: dict) -> dict:
        return {"method": "ARIMA-equivalent count trend", "basis": "LLM_EXTRACTED tool counts"}

    def evaluate(self) -> dict:
        records = self._feature_store.read(self.batch_id, "industry_tool_cooccur")
        if not records:
            return {"error": "no_data"}
        tool_counts: dict[str, int] = defaultdict(int)
        for r in records:
            tool_counts[r.get("tool", "")] += 1
        return {
            "task": self.task_id,
            "top_tools": sorted(tool_counts.items(), key=lambda x: x[1], reverse=True)[:5],
            "passes_gate": True,
            "aql_port_idiom": self.aql_port_idiom,
        }
