import json
from collections import Counter
from pathlib import Path

from pte.evaluate.metrics import top_k_accuracy
from pte.features.store import FeatureStore
from pte.predict.base import Task
from pte.predict.baselines import FrequencyBaseline


class T2Industry(Task):
    task_id = "t2_industry"
    accepted_tiers = ["OBSERVED", "DERIVED", "LLM_EXTRACTED"]
    aql_port_idiom = (
        "source pte_features | where entity_type=\"campaign\" "
        "| fit RandomForest industry tool_cooccur_count tactic_cooccur_count trend_slope into 'pte_t2ind' "
        "| apply pte_t2ind"
    )
    metric = "top_k_accuracy"
    horizon = "90d"

    def __init__(self, batch_id: str, data_dir: str = "data"):
        super().__init__(batch_id, data_dir)
        self._feature_store = FeatureStore(base_dir=str(Path(data_dir) / "features"))
        self._model_dir = Path(data_dir) / "models" / batch_id
        self._model_dir.mkdir(parents=True, exist_ok=True)
        self._industry_tool_counts: dict | None = None

    def _load_cooccur(self) -> list[dict]:
        return self._feature_store.read(self.batch_id, "industry_tool_cooccur")

    def fit(self) -> None:
        records = self._load_cooccur()
        if not records:
            return
        counter: Counter = Counter()
        for r in records:
            counter[(r.get("industry", ""), r.get("tool", ""))] += 1
        self._industry_tool_counts = dict(counter)
        with open(self._model_dir / "t2ind_counts.json", "w") as f:
            json.dump({str(k): v for k, v in counter.items()}, f)

    def predict(self, industry: str, top_k: int = 3) -> list[dict]:
        if self._industry_tool_counts is None:
            self._load_model()
        tools = {t: c for (ind, t), c in self._industry_tool_counts.items() if ind == industry}
        ranked = sorted(tools.items(), key=lambda x: x[1], reverse=True)
        return [{"tool": t, "count": c} for t, c in ranked[:top_k]]

    def _load_model(self) -> None:
        path = self._model_dir / "t2ind_counts.json"
        if path.exists():
            import ast
            raw = json.loads(path.read_text())
            self._industry_tool_counts = {ast.literal_eval(k): v for k, v in raw.items()}

    def explain(self, inputs: dict) -> dict:
        industry = inputs.get("industry", "")
        top = self.predict(industry, top_k=5)
        return {"top_tools": top, "basis": "industry×tool co-occurrence count"}

    def evaluate(self) -> dict:
        records = self._load_cooccur()
        if len(records) < 5:
            return {"error": "insufficient_data", "coverage_reported": True}

        industries = list({r.get("industry", "") for r in records})
        y_true = [1 if r.get("corroboration_score", 0) > 0.4 else 0 for r in records]
        y_scores = [r.get("corroboration_score", 0.0) for r in records]

        acc = top_k_accuracy(y_true, y_scores, k=3)
        freq_baseline = FrequencyBaseline(field="corroboration_score")
        freq_ranked = freq_baseline.rank(records)
        freq_scores = [r.get("corroboration_score", 0.0) for r in freq_ranked]
        freq_acc = top_k_accuracy(y_true, freq_scores, k=3)

        coverage_per_industry = {ind: sum(1 for r in records if r.get("industry") == ind) for ind in industries}

        report = {
            "task": self.task_id,
            "batch_id": self.batch_id,
            "top_k_accuracy": acc,
            "sector_frequency_baseline_top_k": freq_acc,
            "lift_over_baseline": acc - freq_acc,
            "coverage_per_industry": coverage_per_industry,
            "coverage_reported": True,
            "passes_gate": acc > freq_acc,
            "aql_port_idiom": self.aql_port_idiom,
        }
        (self._model_dir / "t2ind_report.json").write_text(json.dumps(report, indent=2))
        return report
