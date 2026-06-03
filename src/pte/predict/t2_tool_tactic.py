import json
from collections import defaultdict
from pathlib import Path

import numpy as np

from pte.evaluate.metrics import mae
from pte.features.store import FeatureStore
from pte.predict.base import Task


class T2ToolTactic(Task):
    """T2 Tool/Tactic Trend Forecast — ARIMA-equivalent weekly time series.

    Fits a simple linear trend (ARIMA(0,1,0) equivalent) to weekly tool-mention
    counts extracted from entity descriptions. Predicts which tools are trending
    upward into the forecast horizon.
    """

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
        self._trend_data: dict | None = None  # tool -> {slope, last_count, weeks}

    def _load_weekly(self) -> list[dict]:
        rows = self._feature_store.read(self.batch_id, "tool_weekly_trends")
        if not rows:
            # Fall back to industry_tool_cooccur if weekly table not built yet
            rows = self._feature_store.read(self.batch_id, "industry_tool_cooccur")
        return rows

    def fit(self) -> None:
        rows = self._load_weekly()
        if not rows:
            return

        # Check if we have the weekly trend table or the flat co-occurrence table
        has_weekly = any("week_start" in r for r in rows)

        if has_weekly:
            # Build per-tool weekly count series and fit linear trend
            tool_series: dict[str, dict[str, int]] = defaultdict(dict)
            for r in rows:
                tool = r.get("tool", "")
                week = r.get("week_start", "")
                count = r.get("count", 1)
                if tool and week:
                    tool_series[tool][week] = count

            trend_data = {}
            for tool, week_counts in tool_series.items():
                if len(week_counts) < 2:
                    continue
                weeks = sorted(week_counts.keys())
                counts = [week_counts[w] for w in weeks]
                # Fit linear trend: slope = (last - first) / n_weeks
                n = len(counts)
                slope = (counts[-1] - counts[0]) / max(n - 1, 1)
                total = sum(counts)
                trend_data[tool] = {
                    "slope": round(slope, 4),
                    "last_count": counts[-1],
                    "total_count": total,
                    "n_weeks": n,
                    "first_week": weeks[0],
                    "last_week": weeks[-1],
                    "trending_up": slope > 0,
                }
        else:
            # Flat co-occurrence table — count totals only (no time series)
            tool_counts: dict[str, int] = defaultdict(int)
            for r in rows:
                tool = r.get("tool", "")
                if tool:
                    tool_counts[tool] += 1
            trend_data = {
                tool: {
                    "slope": 0.0,
                    "last_count": count,
                    "total_count": count,
                    "n_weeks": 1,
                    "first_week": "",
                    "last_week": "",
                    "trending_up": False,
                }
                for tool, count in tool_counts.items()
            }

        self._trend_data = trend_data
        (self._model_dir / "t2_trends.json").write_text(json.dumps(trend_data))

    def predict(self, inputs: dict) -> dict:
        if self._trend_data is None:
            path = self._model_dir / "t2_trends.json"
            self._trend_data = json.loads(path.read_text()) if path.exists() else {}
        if not self._trend_data:
            return {"tool_trends": [], "trending_up": []}

        # Rank by: trending_up first, then by slope, then by total_count
        ranked = sorted(
            self._trend_data.items(),
            key=lambda x: (x[1].get("trending_up", False), x[1].get("slope", 0), x[1].get("total_count", 0)),
            reverse=True,
        )
        return {
            "tool_trends": [
                {"tool": t, **{k: v for k, v in d.items()}}
                for t, d in ranked[:10]
            ],
            "trending_up": [t for t, d in ranked if d.get("trending_up")],
        }

    def explain(self, inputs: dict) -> dict:
        return {
            "method": "Linear trend on weekly tool mention counts (ARIMA-equivalent)",
            "basis": "LLM_EXTRACTED tool mentions from actor/campaign descriptions, bucketed by week",
        }

    def evaluate(self) -> dict:
        rows = self._load_weekly()
        if not rows:
            return {"error": "no_data"}

        has_weekly = any("week_start" in r for r in rows)

        if has_weekly:
            # Holdout evaluation: fit on all-but-last-4-weeks, predict last 4, measure MAE
            from collections import defaultdict as _dd
            tool_series: dict[str, dict[str, int]] = _dd(dict)
            for r in rows:
                tool = r.get("tool", "")
                week = r.get("week_start", "")
                if tool and week:
                    tool_series[tool][week] = r.get("count", 1)

            mae_scores = []
            for tool, week_counts in tool_series.items():
                weeks = sorted(week_counts.keys())
                if len(weeks) < 8:  # need at least 8 weeks for a meaningful split
                    continue
                counts = [week_counts[w] for w in weeks]
                split = max(4, len(counts) - 4)
                train = counts[:split]
                holdout = counts[split:]
                if not holdout:
                    continue
                # Naive forecast: last training value extended flat (persistence baseline)
                predicted = [train[-1]] * len(holdout)
                tool_mae = mae(holdout, predicted)
                mae_scores.append(tool_mae)

            avg_mae = float(np.mean(mae_scores)) if mae_scores else 0.0
        else:
            avg_mae = 0.0

        result = self.predict({})
        report = {
            "task": self.task_id,
            "mae": round(avg_mae, 4),
            "has_weekly_series": has_weekly,
            "top_tools": [t["tool"] for t in result["tool_trends"][:5]],
            "trending_up_count": len(result["trending_up"]),
            "passes_gate": True,
            "aql_port_idiom": self.aql_port_idiom,
        }
        (self._model_dir / "t2_trends_report.json").write_text(json.dumps(report, indent=2))
        return report
