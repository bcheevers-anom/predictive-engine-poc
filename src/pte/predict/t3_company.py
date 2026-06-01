import json
from pathlib import Path
from pte.features.store import FeatureStore
from pte.predict.base import Task


class T3Company(Task):
    task_id = "t3_company"
    accepted_tiers = ["LLM_EXTRACTED"]
    aql_port_idiom = (
        "source pte_features | where entity_type=\"company\" "
        "| fit RandomForest company_sector_match tool_overlap geo_match into 'pte_t3' "
        "| apply pte_t3"
    )
    metric = "top_k_accuracy"
    horizon = "90d"

    def __init__(self, batch_id: str, data_dir: str = "data"):
        super().__init__(batch_id, data_dir)
        self._feature_store = FeatureStore(base_dir=str(Path(data_dir) / "features"))
        self._model_dir = Path(data_dir) / "models" / batch_id
        self._coverage_flag = "unknown"

    def fit(self) -> None:
        records = self._feature_store.read(self.batch_id, "industry_tool_cooccur")
        companies = [r for r in records if r.get("company")]
        self._coverage_flag = "sufficient" if len(companies) >= 20 else "sparse"
        (Path(self.data_dir) / "models" / self.batch_id).mkdir(parents=True, exist_ok=True)

    def predict(self, inputs: dict) -> dict:
        if self._coverage_flag == "sparse":
            return {"status": "not_supported", "reason": "Company-level signal sparse for this batch — fewer than 20 extracted company references. Use sector-level forecast instead."}
        return {"status": "unsupported_in_poc", "reason": "T3 company ranking requires additional engineering."}

    def explain(self, inputs: dict) -> dict:
        return {"coverage_flag": self._coverage_flag}

    def evaluate(self) -> dict:
        return {"task": self.task_id, "coverage_flag": self._coverage_flag, "passes_gate": False, "reason": "Conditional on coverage"}
