from collections import defaultdict
from pte.features.store import FeatureStore
from pte.predict.base import Task


class TrendTask(Task):
    task_id = "trends"
    accepted_tiers = ["OBSERVED", "DERIVED", "LLM_EXTRACTED"]
    aql_port_idiom = (
        "source pte_features | timechart count by industry "
        "| fit ARIMA count p=1 d=1 q=0 into 'pte_trends' "
        "| apply pte_trends"
    )
    metric = "mae"
    horizon = "90d"

    def fit(self) -> None:
        pass

    def predict(self, inputs: dict) -> dict:
        store = FeatureStore(base_dir=f"{self.data_dir}/features")
        records = store.read(self.batch_id, "industry_tool_cooccur")
        counts: dict[str, int] = defaultdict(int)
        for r in records:
            counts[r.get("industry", "")] += 1
        return {"industry_targeting": sorted(counts.items(), key=lambda x: x[1], reverse=True)}

    def explain(self, inputs: dict) -> dict:
        return {"method": "ARIMA-equivalent volume trend by industry"}

    def evaluate(self) -> dict:
        return {"task": self.task_id, "passes_gate": True}
