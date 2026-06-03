import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta
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
            if r.get("tool"):  # skip empty-tool rows
                counter[(r.get("industry", ""), r.get("tool", ""))] += 1
        self._industry_tool_counts = dict(counter)
        with open(self._model_dir / "t2ind_counts.json", "w") as f:
            json.dump({str(k): v for k, v in counter.items()}, f)

    def predict(self, industry: str, top_k: int = 3) -> list[dict]:
        if self._industry_tool_counts is None:
            self._load_model()
        if not self._industry_tool_counts:
            return []
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
        return {"top_tools": top, "basis": "industry x tool co-occurrence count"}

    def evaluate(self) -> dict:
        records = [r for r in self._load_cooccur() if r.get("tool")]
        if len(records) < 5:
            return {"error": "insufficient_data", "coverage_reported": True}

        coverage_per_industry = Counter(r.get("industry", "") for r in records)

        # --- Time-split evaluation: 3w train / 1w holdout ---
        # Only possible if records have created_ts dates
        dated = [r for r in records if r.get("created_ts")]

        if len(dated) >= 10:
            acc, freq_acc, eval_note = self._time_split_eval(dated)
        else:
            # No timestamps available — fall back to held-out fraction
            acc, freq_acc, eval_note = self._fraction_split_eval(records)

        report = {
            "task": self.task_id,
            "batch_id": self.batch_id,
            "top_k_accuracy": round(acc, 4),
            "sector_frequency_baseline_top_k": round(freq_acc, 4),
            "lift_over_baseline": round(acc - freq_acc, 4),
            "coverage_per_industry": dict(coverage_per_industry.most_common()),
            "coverage_reported": True,
            "passes_gate": acc > freq_acc,
            "eval_note": eval_note,
            "aql_port_idiom": self.aql_port_idiom,
        }
        (self._model_dir / "t2ind_report.json").write_text(json.dumps(report, indent=2))
        return report

    def _time_split_eval(self, records: list[dict]) -> tuple[float, float, str]:
        """3-week train / 1-week holdout evaluation on dated records.

        For each industry in the holdout week:
          - top-3 predicted tools from training window
          - actual tools seen in holdout week
          - score = fraction of predictions that appeared in actuals
        """
        dates = sorted(r["created_ts"] for r in records)
        max_date = datetime.fromisoformat(dates[-1])
        holdout_start = max_date - timedelta(days=7)
        train_cutoff = holdout_start

        train = [r for r in records if r["created_ts"] < holdout_start.strftime("%Y-%m-%d")]
        holdout = [r for r in records if r["created_ts"] >= holdout_start.strftime("%Y-%m-%d")]

        if not train or not holdout:
            return self._fraction_split_eval(records)

        # Build training co-occurrence counts
        train_counts: dict[str, Counter] = defaultdict(Counter)
        for r in train:
            ind = r.get("industry", "")
            tool = r.get("tool", "")
            if ind and tool:
                train_counts[ind][tool] += 1

        # Build holdout actuals: industry -> set of tools seen
        holdout_actuals: dict[str, set] = defaultdict(set)
        for r in holdout:
            ind = r.get("industry", "")
            tool = r.get("tool", "")
            if ind and tool:
                holdout_actuals[ind].add(tool)

        # Evaluate: for each industry in holdout, did top-3 train predictions appear?
        industries_evaluated = [ind for ind in holdout_actuals if ind in train_counts]
        if not industries_evaluated:
            return 0.0, 0.0, f"train={len(train)} holdout={len(holdout)} no overlapping industries"

        hits = 0
        total = 0
        baseline_hits = 0
        for ind in industries_evaluated:
            actual_tools = holdout_actuals[ind]
            top3_pred = [t for t, _ in train_counts[ind].most_common(3)]
            # Baseline: most frequent tools overall in training (not industry-specific)
            all_train_tools = Counter(r.get("tool", "") for r in train if r.get("tool"))
            top3_baseline = [t for t, _ in all_train_tools.most_common(3)]

            for t in top3_pred:
                total += 1
                if t in actual_tools:
                    hits += 1
            for t in top3_baseline:
                if t in actual_tools:
                    baseline_hits += 1

        acc = hits / total if total > 0 else 0.0
        freq_acc = baseline_hits / (len(industries_evaluated) * 3) if industries_evaluated else 0.0
        note = (f"time-split: train={len(train)} rows, holdout={len(holdout)} rows, "
                f"holdout_start={holdout_start.date()}, industries_evaluated={len(industries_evaluated)}")
        return acc, freq_acc, note

    def _fraction_split_eval(self, records: list[dict]) -> tuple[float, float, str]:
        """Fallback: last 25% of records as holdout (no timestamps)."""
        n = len(records)
        split = int(n * 0.75)
        train = records[:split]
        holdout = records[split:]

        train_counts: dict[str, Counter] = defaultdict(Counter)
        for r in train:
            ind, tool = r.get("industry", ""), r.get("tool", "")
            if ind and tool:
                train_counts[ind][tool] += 1

        holdout_actuals: dict[str, set] = defaultdict(set)
        for r in holdout:
            ind, tool = r.get("industry", ""), r.get("tool", "")
            if ind and tool:
                holdout_actuals[ind].add(tool)

        industries_evaluated = [ind for ind in holdout_actuals if ind in train_counts]
        if not industries_evaluated:
            return 0.0, 0.0, f"fraction-split: no overlapping industries in train/holdout"

        hits = total = baseline_hits = 0
        all_train_tools = Counter(r.get("tool", "") for r in train if r.get("tool"))
        for ind in industries_evaluated:
            actual = holdout_actuals[ind]
            top3 = [t for t, _ in train_counts[ind].most_common(3)]
            top3_baseline = [t for t, _ in all_train_tools.most_common(3)]
            for t in top3:
                total += 1
                if t in actual:
                    hits += 1
            for t in top3_baseline:
                if t in actual:
                    baseline_hits += 1

        acc = hits / total if total > 0 else 0.0
        freq_acc = baseline_hits / (len(industries_evaluated) * 3) if industries_evaluated else 0.0
        return acc, freq_acc, f"fraction-split (no timestamps): train={len(train)} holdout={len(holdout)}"
