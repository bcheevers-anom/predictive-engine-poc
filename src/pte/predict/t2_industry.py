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

        # Check whether TF-IDF scores are available in the feature table
        has_tfidf = any(r.get("tfidf_score") for r in records[:100])

        if has_tfidf:
            # Use summed TF-IDF score as the ranking signal — penalises ubiquitous tools
            from collections import defaultdict as _dd
            scores: dict[tuple, float] = _dd(float)
            for r in records:
                if r.get("tool"):
                    scores[(r.get("industry", ""), r.get("tool", ""))] += r.get("tfidf_score", 0.0)
            self._industry_tool_counts = dict(scores)
        else:
            # Fall back to raw counts for batches without TF-IDF
            counter: Counter = Counter()
            for r in records:
                if r.get("tool"):
                    counter[(r.get("industry", ""), r.get("tool", ""))] += 1
            self._industry_tool_counts = dict(counter)

        with open(self._model_dir / "t2ind_counts.json", "w") as f:
            json.dump({str(k): v for k, v in self._industry_tool_counts.items()}, f)

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
        dated = [r for r in records if r.get("created_ts")]

        if len(dated) >= 10:
            metrics = self._time_split_eval(dated)
        else:
            metrics = self._fraction_split_eval(records)

        report = {
            "task": self.task_id,
            "batch_id": self.batch_id,
            # Core accuracy
            "top_k_accuracy": round(metrics["top_k_accuracy"], 4),
            "sector_frequency_baseline_top_k": round(metrics["baseline_top_k"], 4),
            "lift_over_baseline": round(metrics["top_k_accuracy"] - metrics["baseline_top_k"], 4),
            # Full ranking metrics
            "precision_at_k": round(metrics["precision_at_k"], 4),
            "recall_at_k": round(metrics["recall_at_k"], 4),
            "f1_at_k": round(metrics["f1_at_k"], 4),
            "map_score": round(metrics["map_score"], 4),
            "ndcg_at_k": round(metrics["ndcg_at_k"], 4),
            # Provenance
            "model_type": "Co-occurrence frequency ranking (top-k)",
            "extraction_model": "Claude Opus 4.8 via AWS Bedrock (us.anthropic.claude-opus-4-8)",
            "feature_tier": "LLM_EXTRACTED (industry/tool pairs from actor and campaign descriptions)",
            "train_rows": metrics["train_rows"],
            "holdout_rows": metrics["holdout_rows"],
            "industries_evaluated": metrics["industries_evaluated"],
            # Coverage and meta
            "coverage_per_industry": dict(coverage_per_industry.most_common()),
            "coverage_reported": True,
            "passes_gate": metrics["top_k_accuracy"] > metrics["baseline_top_k"],
            "eval_note": metrics["eval_note"],
            "aql_port_idiom": self.aql_port_idiom,
        }
        (self._model_dir / "t2ind_report.json").write_text(json.dumps(report, indent=2))
        return report

    def _time_split_eval(self, records: list[dict]) -> dict:
        """3-week train / 1-week holdout evaluation. Returns a full metrics dict."""
        from pte.evaluate.metrics import (
            precision_at_k, recall_at_k, f1_at_k,
            mean_average_precision, ndcg_at_k,
        )
        import numpy as _np
        dates = sorted(r["created_ts"] for r in records)
        max_date = datetime.fromisoformat(dates[-1])
        holdout_start = max_date - timedelta(days=7)

        train = [r for r in records if r["created_ts"] < holdout_start.strftime("%Y-%m-%d")]
        holdout = [r for r in records if r["created_ts"] >= holdout_start.strftime("%Y-%m-%d")]

        if not train or not holdout:
            return self._fraction_split_eval(records)

        train_counts: dict[str, Counter] = defaultdict(Counter)
        for r in train:
            ind, tool = r.get("industry", ""), r.get("tool", "")
            if ind and tool:
                train_counts[ind][tool] += 1

        holdout_actuals: dict[str, set] = defaultdict(set)
        holdout_counts: dict[str, Counter] = defaultdict(Counter)
        for r in holdout:
            ind, tool = r.get("industry", ""), r.get("tool", "")
            if ind and tool:
                holdout_actuals[ind].add(tool)
                holdout_counts[ind][tool] += 1

        industries_evaluated = [ind for ind in holdout_actuals if ind in train_counts]
        if not industries_evaluated:
            return {
                "top_k_accuracy": 0.0, "baseline_top_k": 0.0,
                "precision_at_k": 0.0, "recall_at_k": 0.0,
                "f1_at_k": 0.0, "map_score": 0.0, "ndcg_at_k": 0.0,
                "train_rows": len(train), "holdout_rows": len(holdout),
                "industries_evaluated": 0,
                "eval_note": f"train={len(train)} holdout={len(holdout)} no overlapping industries",
            }

        all_train_tools = Counter(r.get("tool", "") for r in train if r.get("tool"))
        top3_baseline_global = [t for t, _ in all_train_tools.most_common(3)]

        hits = total = baseline_hits = 0
        per_sector_results = []
        ndcg_scores = []

        for ind in industries_evaluated:
            actual = holdout_actuals[ind]
            actual_cnt = holdout_counts[ind]
            top3_pred = [t for t, _ in train_counts[ind].most_common(3)]

            for t in top3_pred:
                total += 1
                if t in actual:
                    hits += 1
            for t in top3_baseline_global:
                if t in actual:
                    baseline_hits += 1

            per_sector_results.append({"predicted": top3_pred, "actual": actual})
            ndcg_scores.append(ndcg_at_k(top3_pred, dict(actual_cnt)))

        acc = hits / total if total > 0 else 0.0
        freq_acc = baseline_hits / (len(industries_evaluated) * 3) if industries_evaluated else 0.0

        p_scores = [precision_at_k(r["predicted"], r["actual"]) for r in per_sector_results]
        r_scores = [recall_at_k(r["predicted"], r["actual"]) for r in per_sector_results]
        f_scores = [f1_at_k(r["predicted"], r["actual"]) for r in per_sector_results]

        return {
            "top_k_accuracy": acc,
            "baseline_top_k": freq_acc,
            "precision_at_k": float(_np.mean(p_scores)) if p_scores else 0.0,
            "recall_at_k": float(_np.mean(r_scores)) if r_scores else 0.0,
            "f1_at_k": float(_np.mean(f_scores)) if f_scores else 0.0,
            "map_score": mean_average_precision(per_sector_results),
            "ndcg_at_k": float(_np.mean(ndcg_scores)) if ndcg_scores else 0.0,
            "train_rows": len(train),
            "holdout_rows": len(holdout),
            "industries_evaluated": len(industries_evaluated),
            "eval_note": (
                f"time-split: train={len(train)} rows, holdout={len(holdout)} rows, "
                f"holdout_start={holdout_start.date()}, industries_evaluated={len(industries_evaluated)}"
            ),
        }

    def _fraction_split_eval(self, records: list[dict]) -> dict:
        """Fallback: last 25% of records as holdout (no timestamps)."""
        from pte.evaluate.metrics import (
            precision_at_k, recall_at_k, f1_at_k,
            mean_average_precision, ndcg_at_k,
        )
        import numpy as _np
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
        holdout_counts: dict[str, Counter] = defaultdict(Counter)
        for r in holdout:
            ind, tool = r.get("industry", ""), r.get("tool", "")
            if ind and tool:
                holdout_actuals[ind].add(tool)
                holdout_counts[ind][tool] += 1

        industries_evaluated = [ind for ind in holdout_actuals if ind in train_counts]
        if not industries_evaluated:
            return {
                "top_k_accuracy": 0.0, "baseline_top_k": 0.0,
                "precision_at_k": 0.0, "recall_at_k": 0.0,
                "f1_at_k": 0.0, "map_score": 0.0, "ndcg_at_k": 0.0,
                "train_rows": len(train), "holdout_rows": len(holdout),
                "industries_evaluated": 0,
                "eval_note": "fraction-split: no overlapping industries in train/holdout",
            }

        all_train_tools = Counter(r.get("tool", "") for r in train if r.get("tool"))
        top3_baseline_global = [t for t, _ in all_train_tools.most_common(3)]

        hits = total = baseline_hits = 0
        per_sector_results = []
        ndcg_scores = []

        for ind in industries_evaluated:
            actual = holdout_actuals[ind]
            actual_cnt = holdout_counts[ind]
            top3 = [t for t, _ in train_counts[ind].most_common(3)]

            for t in top3:
                total += 1
                if t in actual:
                    hits += 1
            for t in top3_baseline_global:
                if t in actual:
                    baseline_hits += 1

            per_sector_results.append({"predicted": top3, "actual": actual})
            ndcg_scores.append(ndcg_at_k(top3, dict(actual_cnt)))

        acc = hits / total if total > 0 else 0.0
        freq_acc = baseline_hits / (len(industries_evaluated) * 3) if industries_evaluated else 0.0

        p_scores = [precision_at_k(r["predicted"], r["actual"]) for r in per_sector_results]
        r_scores = [recall_at_k(r["predicted"], r["actual"]) for r in per_sector_results]
        f_scores = [f1_at_k(r["predicted"], r["actual"]) for r in per_sector_results]

        return {
            "top_k_accuracy": acc,
            "baseline_top_k": freq_acc,
            "precision_at_k": float(_np.mean(p_scores)) if p_scores else 0.0,
            "recall_at_k": float(_np.mean(r_scores)) if r_scores else 0.0,
            "f1_at_k": float(_np.mean(f_scores)) if f_scores else 0.0,
            "map_score": mean_average_precision(per_sector_results),
            "ndcg_at_k": float(_np.mean(ndcg_scores)) if ndcg_scores else 0.0,
            "train_rows": len(train),
            "holdout_rows": len(holdout),
            "industries_evaluated": len(industries_evaluated),
            "eval_note": f"fraction-split (no timestamps): train={len(train)} holdout={len(holdout)}",
        }
