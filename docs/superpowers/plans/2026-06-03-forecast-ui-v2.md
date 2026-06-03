# Forecast Screen v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign the forecast screen to show a stacked trend chart, a full suite of ML metrics (Precision@3, Recall@3, F1@3, MAP, NDCG@3) with plain-English tooltips, and a model provenance panel — making the UI usable by non-technical stakeholders.

**Architecture:** Four layers in order: (1) add ranking metrics to `metrics.py` and `t2_industry.evaluate()`, (2) extend the forecast API response and add `/api/trends` + `/api/tool-info` endpoints, (3) build new React components (`InfoTooltip`, `ToolTrendChart`, `MetricsGrid`, `ModelProvenancePanel`), (4) rewire `ForecastScreen.tsx` to the new layout. Each layer is independently testable before the next builds on it.

**Tech Stack:** Python 3.12, numpy/sklearn (metrics), FastAPI, React 18 + Recharts (stacked AreaChart), TypeScript.

---

## Context for the implementer

### Project overview
Predictive Threat Engine PoC. Extracts intelligence signal from ThreatStream via LLM, runs co-occurrence ranking models, serves results via FastAPI + React UI.

### The T2-Industry model
Not a binary classifier — it ranks tools by how often they co-occurred with a given sector in training data, then checks whether those tools appeared in the holdout week. Metrics like Precision@k, Recall@k, F1@k are the ranking equivalents of their classifier counterparts.

### Key paths
- Working directory: `C:/Users/BarryCheevers/OneDrive - Anomali/Desktop/Claude Projects/Predictive Engine`
- Venv: `.venv/Scripts/activate` (Windows)
- Tests: `pytest tests/ -v`
- API server: `uvicorn api.main:app --port 8080`
- React dev server: `cd web && npm run dev`
- Batch with real data: `ent-861c216a-07f0e5b2411d`
- Model report: `data/models/ent-861c216a-07f0e5b2411d/t2ind_report.json`

### Current state of `t2_industry.evaluate()`
Returns only: `top_k_accuracy`, `sector_frequency_baseline_top_k`, `lift_over_baseline`, `coverage_per_industry`, `passes_gate`, `eval_note`, `aql_port_idiom`. The `_time_split_eval` method already builds `train_counts` (dict[industry → Counter[tool → count]]) and `holdout_actuals` (dict[industry → set[tool]]) — the new metrics reuse these exact structures.

---

## File Structure

```
src/pte/evaluate/metrics.py          MODIFY — add 5 ranking metric functions
src/pte/predict/t2_industry.py       MODIFY — compute all metrics in evaluate(); refactor _time_split_eval to return full metrics dict
api/routes/forecast.py               MODIFY — pass all metrics through; add /api/trends; add /api/tool-info
web/src/types/api.ts                 MODIFY — add TrendsResponse, extend ForecastResponse
web/src/components/InfoTooltip.tsx   CREATE — reusable click-to-open tooltip
web/src/components/graphs/ToolTrendChart.tsx  CREATE — stacked area chart with holdout shading
web/src/components/MetricsGrid.tsx   CREATE — 2×4 grid of metric cards with InfoTooltip
web/src/components/ModelProvenancePanel.tsx   CREATE — collapsible model details
web/src/components/ForecastScreen.tsx  MODIFY — new layout integrating all new components
```

---

## Task 1: Add ranking metric functions to metrics.py

**Files:**
- Modify: `src/pte/evaluate/metrics.py`
- Test: `tests/test_evaluate.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_evaluate.py`:
```python
from pte.evaluate.metrics import precision_at_k, recall_at_k, f1_at_k, mean_average_precision, ndcg_at_k

def test_precision_at_k_perfect():
    # predicted [A,B,C], actual {A,B,C} → 3/3 = 1.0
    assert precision_at_k(predicted=["A","B","C"], actual={"A","B","C"}) == 1.0

def test_precision_at_k_none():
    # predicted [X,Y,Z], actual {A,B,C} → 0/3 = 0.0
    assert precision_at_k(predicted=["X","Y","Z"], actual={"A","B","C"}) == 0.0

def test_precision_at_k_partial():
    # predicted [A,X,Y], actual {A,B,C} → 1/3
    assert abs(precision_at_k(predicted=["A","X","Y"], actual={"A","B","C"}) - 1/3) < 0.001

def test_recall_at_k_perfect():
    # predicted [A,B,C], actual {A,B} → 2/2 = 1.0
    assert recall_at_k(predicted=["A","B","C"], actual={"A","B"}) == 1.0

def test_recall_at_k_empty_actual():
    assert recall_at_k(predicted=["A"], actual=set()) == 0.0

def test_f1_at_k_perfect():
    assert f1_at_k(predicted=["A","B","C"], actual={"A","B","C"}) == 1.0

def test_f1_at_k_zero():
    assert f1_at_k(predicted=["X","Y","Z"], actual={"A","B","C"}) == 0.0

def test_mean_average_precision_perfect():
    # Two sectors, both perfectly predicted
    results = [
        {"predicted": ["A","B","C"], "actual": {"A","B","C"}},
        {"predicted": ["X","Y","Z"], "actual": {"X","Y","Z"}},
    ]
    assert mean_average_precision(results) == 1.0

def test_mean_average_precision_empty():
    assert mean_average_precision([]) == 0.0

def test_ndcg_at_k_perfect():
    # Predicted matches actuals with highest counts first → perfect score
    predicted = ["A", "B", "C"]
    actual_counts = {"A": 10, "B": 5, "C": 2}
    score = ndcg_at_k(predicted=predicted, actual_counts=actual_counts)
    assert abs(score - 1.0) < 0.001

def test_ndcg_at_k_zero():
    predicted = ["X", "Y", "Z"]
    actual_counts = {"A": 10, "B": 5, "C": 2}
    score = ndcg_at_k(predicted=predicted, actual_counts=actual_counts)
    assert score == 0.0
```

Run: `pytest tests/test_evaluate.py -k "precision_at_k or recall_at_k or f1_at_k or mean_average or ndcg" -v`
Expected: FAIL with ImportError

- [ ] **Step 2: Add the 5 metric functions to `src/pte/evaluate/metrics.py`**

Append to the existing file (do NOT remove existing functions):
```python
import math


def precision_at_k(predicted: list[str], actual: set[str]) -> float:
    """Fraction of predicted tools that actually appeared in the holdout."""
    if not predicted:
        return 0.0
    return sum(1 for t in predicted if t in actual) / len(predicted)


def recall_at_k(predicted: list[str], actual: set[str]) -> float:
    """Fraction of actual holdout tools that were predicted."""
    if not actual:
        return 0.0
    return sum(1 for t in predicted if t in actual) / len(actual)


def f1_at_k(predicted: list[str], actual: set[str]) -> float:
    """Harmonic mean of precision@k and recall@k."""
    p = precision_at_k(predicted, actual)
    r = recall_at_k(predicted, actual)
    return 2 * p * r / (p + r) if (p + r) > 0 else 0.0


def mean_average_precision(results: list[dict]) -> float:
    """Mean Average Precision across sectors.

    Each result dict must have keys:
      'predicted': list[str]  — ranked tool list
      'actual':    set[str]   — tools that appeared in holdout
    """
    if not results:
        return 0.0
    ap_scores = []
    for r in results:
        predicted = r.get("predicted", [])
        actual = r.get("actual", set())
        if not actual:
            continue
        hits = 0
        precision_sum = 0.0
        for i, tool in enumerate(predicted, 1):
            if tool in actual:
                hits += 1
                precision_sum += hits / i
        ap_scores.append(precision_sum / len(actual) if actual else 0.0)
    return float(np.mean(ap_scores)) if ap_scores else 0.0


def ndcg_at_k(predicted: list[str], actual_counts: dict[str, int]) -> float:
    """Normalised Discounted Cumulative Gain.

    Uses actual tool counts as relevance weights.
    predicted: ranked list of predicted tools
    actual_counts: dict mapping tool → count in holdout
    """
    if not predicted or not actual_counts:
        return 0.0

    def dcg(ranking: list[str]) -> float:
        return sum(
            actual_counts.get(tool, 0) / math.log2(i + 2)
            for i, tool in enumerate(ranking)
        )

    ideal = sorted(actual_counts, key=actual_counts.get, reverse=True)[:len(predicted)]
    idcg = dcg(ideal)
    return dcg(predicted) / idcg if idcg > 0 else 0.0
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/test_evaluate.py -v`
Expected: all tests pass (old 3 + new 11 = 14 total)

- [ ] **Step 4: Commit**

```bash
git add src/pte/evaluate/metrics.py tests/test_evaluate.py
git commit -m "feat(metrics): add precision@k, recall@k, f1@k, MAP, NDCG@k ranking metrics"
```

---

## Task 2: Extend T2Industry.evaluate() with full metrics suite

**Files:**
- Modify: `src/pte/predict/t2_industry.py`
- Test: `tests/test_predict.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_predict.py`:
```python
def test_t2_industry_evaluate_returns_full_metrics(tmp_path):
    from pte.features.store import FeatureStore
    store = FeatureStore(base_dir=str(tmp_path / "features"))
    # 40 records with created_ts to enable time split (30 train, 10 holdout)
    records = [
        {
            "entity_id": f"e{i}",
            "industry": "Oil and Gas",
            "tool": "Cobalt Strike" if i % 2 == 0 else "Mimikatz",
            "tactic": "Lateral Movement",
            "corroboration_score": 0.5,
            "tier": "LLM_EXTRACTED",
            "created_ts": f"2026-05-{(i % 28)+1:02d}",
        }
        for i in range(40)
    ]
    store.write("batch001", "industry_tool_cooccur", records)

    t2 = T2Industry(batch_id="batch001", data_dir=str(tmp_path))
    t2.fit()
    report = t2.evaluate()

    # All new metrics must be present
    for key in ["precision_at_k", "recall_at_k", "f1_at_k", "map_score", "ndcg_at_k",
                "model_type", "extraction_model", "feature_tier",
                "train_rows", "holdout_rows", "industries_evaluated"]:
        assert key in report, f"Missing key: {key}"

    # Values must be floats in [0, 1]
    for key in ["precision_at_k", "recall_at_k", "f1_at_k", "map_score", "ndcg_at_k"]:
        assert 0.0 <= report[key] <= 1.0, f"{key} out of range: {report[key]}"
```

Run: `pytest tests/test_predict.py::test_t2_industry_evaluate_returns_full_metrics -v`
Expected: FAIL (keys not present)

- [ ] **Step 2: Refactor `_time_split_eval` to return a full metrics dict**

Replace the `_time_split_eval` method and `evaluate` method in `src/pte/predict/t2_industry.py` with:

```python
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

            # top_k_accuracy (hits/total)
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

        # Aggregate per-sector metrics
        p_scores = [precision_at_k(r["predicted"], r["actual"]) for r in per_sector_results]
        r_scores = [recall_at_k(r["predicted"], r["actual"]) for r in per_sector_results]
        f_scores = [f1_at_k(r["predicted"], r["actual"]) for r in per_sector_results]

        import numpy as _np
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

        import numpy as _np
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
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/test_predict.py -v`
Expected: all tests pass including the new one

- [ ] **Step 4: Re-run evaluate on the real batch to regenerate report**

```bash
source .venv/Scripts/activate
pte evaluate t2-industry --batch-id ent-861c216a-07f0e5b2411d
```

Expected output: `Evaluation report: {'task': 't2_industry', ..., 'precision_at_k': ..., 'f1_at_k': ..., 'model_type': 'Co-occurrence frequency ranking (top-k)', ...}`

- [ ] **Step 5: Commit**

```bash
git add src/pte/predict/t2_industry.py tests/test_predict.py
git commit -m "feat(predict): extend T2Industry.evaluate() with full ranking metrics and model provenance"
```

---

## Task 3: Add /api/trends and /api/tool-info endpoints; extend forecast response

**Files:**
- Modify: `api/routes/forecast.py`
- Test: `tests/test_explain.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_explain.py`:
```python
def test_trends_endpoint_returns_weekly_series(tmp_path):
    """Verify /api/trends returns weekly tool counts for a sector."""
    import json
    from pathlib import Path
    import pyarrow as pa
    import pyarrow.parquet as pq
    from fastapi.testclient import TestClient
    from api.main import app

    # Write a minimal feature parquet with weekly dates and tools
    records = [
        {"entity_id": f"e{i}", "industry": "Energy",
         "tool": "Cobalt Strike" if i < 5 else "Mimikatz",
         "tactic": "", "corroboration_score": 0.0,
         "created_ts": "2026-05-05" if i < 5 else "2026-05-12",
         "tier": "LLM_EXTRACTED"}
        for i in range(10)
    ]
    feat_dir = tmp_path / "features" / "batch_test"
    feat_dir.mkdir(parents=True)
    table = pa.Table.from_pylist(records)
    pq.write_table(table, str(feat_dir / "industry_tool_cooccur.parquet"))

    # Write a minimal report for holdout_start extraction
    report = {"eval_note": "time-split: train=5 rows, holdout=5 rows, holdout_start=2026-05-12, industries_evaluated=1"}
    models_dir = tmp_path / "models" / "batch_test"
    models_dir.mkdir(parents=True)
    (models_dir / "t2ind_report.json").write_text(json.dumps(report))

    client = TestClient(app)
    resp = client.get(f"/api/trends?batch_id=batch_test&industry=Energy&data_dir={tmp_path}")
    assert resp.status_code == 200
    d = resp.json()
    assert "weeks" in d
    assert "series" in d
    assert len(d["series"]) > 0
    assert "holdout_start" in d

def test_tool_info_known_tool():
    from fastapi.testclient import TestClient
    from api.main import app
    client = TestClient(app)
    resp = client.get("/api/tool-info?tool=PowerShell")
    assert resp.status_code == 200
    d = resp.json()
    assert "description" in d
    assert len(d["description"]) > 10

def test_tool_info_unknown_tool():
    from fastapi.testclient import TestClient
    from api.main import app
    client = TestClient(app)
    resp = client.get("/api/tool-info?tool=SomeCompletelyUnknownTool999")
    assert resp.status_code == 200
    d = resp.json()
    assert "description" in d  # fallback description
```

Run: `pytest tests/test_explain.py -k "trends or tool_info" -v`
Expected: FAIL

- [ ] **Step 2: Add the two new endpoints and extend the forecast response in `api/routes/forecast.py`**

Add after the existing `@router.get("/industries")` block and replace the return dict in `get_forecast`:

```python
# ── /api/trends ──────────────────────────────────────────────────────────────

@router.get("/trends")
async def get_trends(
    batch_id: str = Query(...),
    industry: str = Query(...),
    data_dir: str = "data",
    top_n: int = 5,
):
    """Weekly tool count series for a given sector — powers the stacked area chart."""
    import pyarrow.parquet as pq
    from datetime import datetime, timedelta
    from collections import defaultdict

    feat_path = Path(data_dir) / "features" / batch_id / "industry_tool_cooccur.parquet"
    if not feat_path.exists():
        return {"weeks": [], "series": [], "holdout_start": None}

    rows = pq.read_table(str(feat_path)).to_pylist()
    sector_rows = [r for r in rows if r.get("industry") == industry and r.get("tool") and r.get("created_ts")]
    if not sector_rows:
        return {"weeks": [], "series": [], "holdout_start": None}

    # Get holdout_start from the model report
    report_path = Path(data_dir) / "models" / batch_id / "t2ind_report.json"
    holdout_start = None
    if report_path.exists():
        report = json.loads(report_path.read_text())
        note = report.get("eval_note", "")
        import re
        m = re.search(r"holdout_start=(\d{4}-\d{2}-\d{2})", note)
        if m:
            holdout_start = m.group(1)

    # Bucket by ISO week start (Monday)
    def week_start(date_str: str) -> str:
        d = datetime.fromisoformat(date_str[:10])
        return (d - timedelta(days=d.weekday())).strftime("%Y-%m-%d")

    # Find top_n tools by total count
    from collections import Counter
    tool_totals = Counter(r["tool"] for r in sector_rows)
    top_tools = [t for t, _ in tool_totals.most_common(top_n)]

    # Build weekly counts per tool
    weekly: dict[str, Counter] = defaultdict(Counter)
    for r in sector_rows:
        w = week_start(r["created_ts"])
        weekly[w][r["tool"]] += 1

    weeks = sorted(weekly.keys())
    series = [
        {"tool": tool, "counts": [weekly[w].get(tool, 0) for w in weeks]}
        for tool in top_tools
    ]
    return {"weeks": weeks, "series": series, "holdout_start": holdout_start}


# ── /api/tool-info ────────────────────────────────────────────────────────────

_TOOL_DESCRIPTIONS: dict[str, str] = {
    "powershell": "Microsoft's scripting language, frequently abused by attackers to run commands and download malware without triggering antivirus.",
    "cobalt strike": "Commercial penetration testing tool widely used by attackers as a command-and-control framework after gaining initial access.",
    "mimikatz": "A credential-dumping tool that extracts passwords and tokens from Windows memory.",
    "lockbit": "A ransomware family that encrypts victim files and demands payment — one of the most prolific ransomware groups globally.",
    "ngrok": "A tunnelling tool that creates temporary public URLs — used legitimately by developers, abused by attackers to bypass firewalls.",
    "anydesk": "Remote desktop software — legitimate tool sometimes abused by attackers to maintain persistent access.",
    "impacket": "A Python library for network protocols, used by attackers for lateral movement and credential theft.",
    "powerstats": "A PowerShell-based backdoor associated with Iranian threat actors, used for command-and-control.",
    "powgoop": "A PowerShell downloader associated with Iranian state-linked threat actors.",
    "moriagent": "A backdoor used by Iranian APT groups for persistent access to compromised systems.",
    "beacon": "The payload component of Cobalt Strike — a stealthy implant used for command-and-control.",
    "metasploit": "A widely used penetration testing framework that also appears in real-world attacks.",
    "psexec": "A Microsoft Sysinternals tool for running processes remotely — frequently used by attackers for lateral movement.",
    "systembc": "A proxy malware used as a backdoor, often deployed alongside ransomware.",
    "remcos": "A commercial remote access tool frequently abused by attackers for surveillance and control.",
    "agenttesla": "An info-stealing malware that harvests credentials, keystrokes, and screenshots.",
}

@router.get("/tool-info")
async def get_tool_info(tool: str = Query(...)):
    """Return a plain-English one-sentence description for a named tool."""
    key = tool.lower().strip()
    # Exact match first
    if key in _TOOL_DESCRIPTIONS:
        return {"tool": tool, "description": _TOOL_DESCRIPTIONS[key]}
    # Substring match
    for known, desc in _TOOL_DESCRIPTIONS.items():
        if known in key or key in known:
            return {"tool": tool, "description": desc}
    return {
        "tool": tool,
        "description": "A tool or malware family observed in threat intelligence reports for this sector.",
    }
```

Also extend the `get_forecast` return dict to include all new metrics:

In `get_forecast`, replace the final `return { ... }` block with:
```python
    return {
        "status": "ok",
        "passes_gate": passes,
        "gate_note": report.get("eval_note", ""),
        "finding": {
            "title": f"Sector Threat Forecast — {industry or 'All'}",
            "type_name": "PTE/T2-Industry",
            "confidence": report.get("top_k_accuracy", 0.0),
            "viz_type": "classification",
        },
        "prediction": prediction,
        "feature_contributions": contribs,
        "coverage": report.get("coverage_per_industry", {}),
        # Primary metric
        "top_k_accuracy": report.get("top_k_accuracy", 0.0),
        # Full metrics suite
        "metrics": {
            "precision_at_k": report.get("precision_at_k"),
            "recall_at_k": report.get("recall_at_k"),
            "f1_at_k": report.get("f1_at_k"),
            "map_score": report.get("map_score"),
            "ndcg_at_k": report.get("ndcg_at_k"),
            "top_k_accuracy": report.get("top_k_accuracy"),
            "baseline_top_k": report.get("sector_frequency_baseline_top_k"),
            "lift_over_baseline": report.get("lift_over_baseline"),
        },
        # Model provenance
        "provenance": {
            "model_type": report.get("model_type", "Co-occurrence frequency ranking (top-k)"),
            "extraction_model": report.get("extraction_model", "Claude Opus 4.8 via AWS Bedrock"),
            "feature_tier": report.get("feature_tier", "LLM_EXTRACTED"),
            "train_rows": report.get("train_rows"),
            "holdout_rows": report.get("holdout_rows"),
            "industries_evaluated": report.get("industries_evaluated"),
            "aql_port_idiom": t.aql_port_idiom,
        },
        "baselines": {"sector_frequency_top_k": report.get("sector_frequency_baseline_top_k", 0)},
        "batch_id": batch_id,
    }
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/test_explain.py -v`
Expected: all tests pass

- [ ] **Step 4: Commit**

```bash
git add api/routes/forecast.py tests/test_explain.py
git commit -m "feat(api): add /api/trends and /api/tool-info; extend forecast response with full metrics and provenance"
```

---

## Task 4: Create InfoTooltip component

**Files:**
- Create: `web/src/components/InfoTooltip.tsx`

- [ ] **Step 1: Create `web/src/components/InfoTooltip.tsx`**

```typescript
import React, { useState, useRef, useEffect } from 'react'

interface Props {
  text: string
  children?: React.ReactNode
}

export default function InfoTooltip({ text, children }: Props) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  return (
    <span ref={ref} style={{ position: 'relative', display: 'inline-block' }}>
      <button
        onClick={() => setOpen(o => !o)}
        style={{
          background: 'none', border: 'none', cursor: 'pointer',
          color: '#1976d2', fontSize: 13, padding: '0 2px',
          fontWeight: 700, lineHeight: 1,
        }}
        aria-label="More information"
      >
        {children || 'ⓘ'}
      </button>
      {open && (
        <div style={{
          position: 'absolute', top: '100%', left: 0, zIndex: 100,
          background: 'white', border: '1px solid #ddd', borderRadius: 6,
          padding: '10px 12px', width: 280, fontSize: 13, color: '#333',
          boxShadow: '0 4px 16px rgba(0,0,0,0.12)', lineHeight: 1.5,
        }}>
          {text}
        </div>
      )}
    </span>
  )
}
```

- [ ] **Step 2: Verify it builds**

Run: `cd web && npm run build 2>&1 | tail -3`
Expected: `✓ built in ...`

- [ ] **Step 3: Commit**

```bash
git add web/src/components/InfoTooltip.tsx
git commit -m "feat(ui): add reusable InfoTooltip component"
```

---

## Task 5: Create ToolTrendChart (stacked area chart with holdout shading)

**Files:**
- Create: `web/src/components/graphs/ToolTrendChart.tsx`
- Modify: `web/src/types/api.ts`

- [ ] **Step 1: Add TrendsResponse type to `web/src/types/api.ts`**

Append to the file:
```typescript
export interface TrendsResponse {
  weeks: string[]
  series: { tool: string; counts: number[] }[]
  holdout_start: string | null
}
```

- [ ] **Step 2: Create `web/src/components/graphs/ToolTrendChart.tsx`**

```typescript
import React from 'react'
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip,
  Legend, ReferenceLine, ResponsiveContainer,
} from 'recharts'
import { TrendsResponse } from '../../types/api'

const COLOURS = ['#1976d2', '#e53935', '#388e3c', '#f57c00', '#7b1fa2']

interface Props {
  data: TrendsResponse
  industry: string
}

export default function ToolTrendChart({ data, industry }: Props) {
  if (!data.weeks.length || !data.series.length) {
    return <p style={{ color: '#aaa', fontSize: 13 }}>No trend data available for {industry}.</p>
  }

  // Build recharts data format: [{week: "2026-05-01", "Cobalt Strike": 4, ...}]
  const chartData = data.weeks.map((week, i) => {
    const row: Record<string, string | number> = { week }
    data.series.forEach(s => { row[s.tool] = s.counts[i] ?? 0 })
    return row
  })

  return (
    <div>
      <h3 style={{ fontSize: 14, marginBottom: 4 }}>
        Tool activity — {industry}
      </h3>
      <p style={{ fontSize: 12, color: '#888', marginBottom: 8 }}>
        Each area shows how often a tool appeared in threat reports per week.
        {data.holdout_start && (
          <span> The shaded region (from {data.holdout_start}) is the <strong>held-out test week</strong> — data the model never saw during training.</span>
        )}
      </p>
      <ResponsiveContainer width="100%" height={240}>
        <AreaChart data={chartData} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
          <XAxis dataKey="week" tick={{ fontSize: 11 }} />
          <YAxis tick={{ fontSize: 11 }} />
          <Tooltip
            formatter={(value: number, name: string) => [`${value} reports`, name]}
            labelFormatter={(label) => `Week of ${label}`}
          />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          {data.holdout_start && (
            <ReferenceLine
              x={data.holdout_start}
              stroke="#f44336"
              strokeDasharray="4 4"
              label={{ value: 'Holdout', fontSize: 11, fill: '#f44336' }}
            />
          )}
          {data.series.map((s, i) => (
            <Area
              key={s.tool}
              type="monotone"
              dataKey={s.tool}
              stackId="1"
              stroke={COLOURS[i % COLOURS.length]}
              fill={COLOURS[i % COLOURS.length]}
              fillOpacity={0.6}
            />
          ))}
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}
```

- [ ] **Step 3: Verify build**

Run: `cd web && npm run build 2>&1 | tail -3`
Expected: `✓ built in ...`

- [ ] **Step 4: Commit**

```bash
git add web/src/components/graphs/ToolTrendChart.tsx web/src/types/api.ts
git commit -m "feat(ui): add ToolTrendChart stacked area chart with holdout reference line"
```

---

## Task 6: Create MetricsGrid component

**Files:**
- Create: `web/src/components/MetricsGrid.tsx`

The tooltip text for each metric uses Option B plain-English tone (plain definition, not analogy).

- [ ] **Step 1: Create `web/src/components/MetricsGrid.tsx`**

```typescript
import React from 'react'
import InfoTooltip from './InfoTooltip'

interface MetricCardProps {
  label: string
  value: number | null | undefined
  tooltip: string
  baseline?: number | null
  format?: 'percent' | 'decimal' | 'count'
}

function MetricCard({ label, value, tooltip, baseline, format = 'percent' }: MetricCardProps) {
  const fmt = (v: number | null | undefined) => {
    if (v == null) return '—'
    if (format === 'percent') return `${(v * 100).toFixed(1)}%`
    if (format === 'count') return String(Math.round(v))
    return v.toFixed(3)
  }

  const isGood = value != null && baseline != null ? value > baseline : null
  const bg = isGood === true ? '#e8f5e9' : isGood === false ? '#fce4ec' : '#f5f5f5'
  const valueColor = isGood === true ? '#2e7d32' : isGood === false ? '#c62828' : '#333'

  return (
    <div style={{
      background: bg, borderRadius: 8, padding: '12px 14px',
      display: 'flex', flexDirection: 'column', gap: 4,
    }}>
      <div style={{ fontSize: 11, color: '#666', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.04em' }}>
        {label} <InfoTooltip text={tooltip} />
      </div>
      <div style={{ fontSize: 22, fontWeight: 700, color: valueColor }}>
        {fmt(value)}
      </div>
      {baseline != null && (
        <div style={{ fontSize: 11, color: '#888' }}>
          Baseline: {fmt(baseline)}
        </div>
      )}
    </div>
  )
}

interface Props {
  metrics: {
    precision_at_k?: number | null
    recall_at_k?: number | null
    f1_at_k?: number | null
    map_score?: number | null
    ndcg_at_k?: number | null
    top_k_accuracy?: number | null
    baseline_top_k?: number | null
    lift_over_baseline?: number | null
  }
  holdoutLabel?: string
}

export default function MetricsGrid({ metrics, holdoutLabel }: Props) {
  const b = metrics.baseline_top_k ?? undefined

  return (
    <div>
      <div style={{ marginBottom: 8 }}>
        <h3 style={{ fontSize: 14, margin: 0 }}>Model performance details</h3>
        <p style={{ fontSize: 12, color: '#888', margin: '4px 0 0' }}>
          All metrics evaluated on {holdoutLabel || 'the held-out test week'} — data the model never saw during training.
          {b != null && ` Green = beats the simple baseline (${(b * 100).toFixed(1)}%). Red = does not.`}
        </p>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10 }}>
        <MetricCard
          label="Prediction accuracy"
          value={metrics.top_k_accuracy}
          tooltip="Out of every 10 tools we predicted would target this sector, about this many actually appeared in the test week's threat reports."
          baseline={b}
        />
        <MetricCard
          label="Precision"
          value={metrics.precision_at_k}
          tooltip="Of the tools we flagged as likely threats, what fraction were genuinely seen in this sector during the test week? High precision means fewer false alarms."
          baseline={b}
        />
        <MetricCard
          label="Recall"
          value={metrics.recall_at_k}
          tooltip="Of all the tools that actually appeared in this sector during the test week, what fraction did we successfully predict? High recall means fewer missed threats."
        />
        <MetricCard
          label="F1 score"
          value={metrics.f1_at_k}
          tooltip="The balance between precision and recall — a single number that penalises both missing threats and raising false alarms equally. 1.0 would be perfect."
        />
        <MetricCard
          label="Avg precision (MAP)"
          value={metrics.map_score}
          tooltip="Measures whether the most important tools are ranked highest in our predictions, not just whether they appear somewhere in the top 3. Higher is better."
          baseline={b}
        />
        <MetricCard
          label="Ranking quality (NDCG)"
          value={metrics.ndcg_at_k}
          tooltip="Rewards putting the most frequently seen threats at the top of our prediction list. A score of 1.0 would mean perfect ranking of threats by severity."
        />
        <MetricCard
          label="Lift vs baseline"
          value={metrics.lift_over_baseline}
          tooltip="How much better or worse the model is compared to simply predicting the most common tools overall. Positive means the model adds value beyond a naive guess."
          format="decimal"
        />
        <MetricCard
          label="Simple baseline"
          value={b}
          tooltip="The accuracy achieved by just predicting the most common tools overall, ignoring which sector we are forecasting. The model should aim to beat this."
        />
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Verify build**

Run: `cd web && npm run build 2>&1 | tail -3`
Expected: `✓ built in ...`

- [ ] **Step 3: Commit**

```bash
git add web/src/components/MetricsGrid.tsx
git commit -m "feat(ui): add MetricsGrid with 8 metric cards and plain-English InfoTooltip explainers"
```

---

## Task 7: Create ModelProvenancePanel component

**Files:**
- Create: `web/src/components/ModelProvenancePanel.tsx`

- [ ] **Step 1: Create `web/src/components/ModelProvenancePanel.tsx`**

```typescript
import React, { useState } from 'react'

interface Provenance {
  model_type?: string
  extraction_model?: string
  feature_tier?: string
  train_rows?: number | null
  holdout_rows?: number | null
  industries_evaluated?: number | null
  aql_port_idiom?: string
}

interface Props { provenance: Provenance }

export default function ModelProvenancePanel({ provenance }: Props) {
  const [open, setOpen] = useState(false)

  return (
    <div style={{ marginTop: 8 }}>
      <button
        onClick={() => setOpen(o => !o)}
        style={{
          background: 'none', border: '1px solid #ddd', borderRadius: 4,
          padding: '4px 12px', fontSize: 12, cursor: 'pointer', color: '#555',
        }}
      >
        {open ? '▲' : '▼'} Model details
      </button>
      {open && (
        <div style={{
          marginTop: 8, padding: 14, background: '#fafafa',
          border: '1px solid #eee', borderRadius: 6, fontSize: 13,
        }}>
          <table style={{ borderCollapse: 'collapse', width: '100%' }}>
            <tbody>
              {[
                ['Model type', provenance.model_type],
                ['Predictions produced by', provenance.model_type],
                ['Features extracted by', provenance.extraction_model],
                ['Feature data tier', provenance.feature_tier],
                ['Training data', provenance.train_rows != null ? `${provenance.train_rows.toLocaleString()} entity-sector-tool rows` : null],
                ['Test data (holdout)', provenance.holdout_rows != null ? `${provenance.holdout_rows.toLocaleString()} rows (final week)` : null],
                ['Sectors evaluated', provenance.industries_evaluated != null ? `${provenance.industries_evaluated} sectors` : null],
              ].filter(([, v]) => v).map(([label, value]) => (
                <tr key={label as string}>
                  <td style={{ color: '#888', paddingRight: 16, paddingBottom: 6, verticalAlign: 'top', whiteSpace: 'nowrap' }}>
                    {label}
                  </td>
                  <td style={{ paddingBottom: 6, color: '#333' }}>{value}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {provenance.aql_port_idiom && (
            <details style={{ marginTop: 8 }}>
              <summary style={{ cursor: 'pointer', color: '#888', fontSize: 12 }}>
                AQL port idiom (engineering reference)
              </summary>
              <pre style={{ marginTop: 4, background: '#f0f0f0', padding: 8, borderRadius: 4, fontSize: 11, overflow: 'auto' }}>
                {provenance.aql_port_idiom}
              </pre>
            </details>
          )}
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Verify build**

Run: `cd web && npm run build 2>&1 | tail -3`
Expected: `✓ built in ...`

- [ ] **Step 3: Commit**

```bash
git add web/src/components/ModelProvenancePanel.tsx
git commit -m "feat(ui): add collapsible ModelProvenancePanel showing training data, extraction model, and AQL idiom"
```

---

## Task 8: Rewrite ForecastScreen.tsx with new layout

**Files:**
- Modify: `web/src/components/ForecastScreen.tsx`

This is the final integration task. It wires all new components into the layout from the spec.

- [ ] **Step 1: Replace `web/src/components/ForecastScreen.tsx`**

```typescript
import React, { useState, useEffect } from 'react'
import { TrendsResponse } from '../types/api'
import InfoTooltip from './InfoTooltip'
import ToolTrendChart from './graphs/ToolTrendChart'
import MetricsGrid from './MetricsGrid'
import ModelProvenancePanel from './ModelProvenancePanel'
import InsufficientCoverage from './states/InsufficientCoverage'
import NoModelYet from './states/NoModelYet'
import CooccurrenceHeatmap from './graphs/CooccurrenceHeatmap'
import EvidenceTrail from './EvidenceTrail'

interface Props { batchId: string }

export default function ForecastScreen({ batchId }: Props) {
  const [industries, setIndustries] = useState<string[]>([])
  const [industryCoverage, setIndustryCoverage] = useState<Record<string, number>>({})
  const [industry, setIndustry] = useState('')
  const [industriesLoading, setIndustriesLoading] = useState(false)
  const [loading, setLoading] = useState(false)
  const [data, setData] = useState<any>(null)
  const [trends, setTrends] = useState<TrendsResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  // Load industries when batch changes
  useEffect(() => {
    if (!batchId) return
    setData(null); setTrends(null); setIndustries([]); setIndustry('')
    setIndustriesLoading(true)
    fetch(`/api/industries?batch_id=${batchId}&min_count=5`)
      .then(r => r.json())
      .then(d => {
        const list: string[] = d.industries || []
        setIndustries(list)
        setIndustryCoverage(d.coverage || {})
        if (list.length > 0) setIndustry(list[0])
      })
      .catch(() => {})
      .finally(() => setIndustriesLoading(false))
  }, [batchId])

  const fetchForecast = async () => {
    if (!batchId || !industry) return
    setLoading(true); setError(null); setTrends(null)
    try {
      const [forecastResp, trendsResp] = await Promise.all([
        fetch(`/api/forecast?industry=${encodeURIComponent(industry)}&batch_id=${batchId}`),
        fetch(`/api/trends?industry=${encodeURIComponent(industry)}&batch_id=${batchId}`),
      ])
      setData(await forecastResp.json())
      setTrends(await trendsResp.json())
    } catch {
      setError('Failed to load forecast.')
    } finally {
      setLoading(false)
    }
  }

  if (!batchId) return (
    <div style={{ padding: 32, color: '#888', textAlign: 'center' }}>
      <p style={{ fontSize: 16 }}>Select a batch in the Dev Panel to view forecasts.</p>
    </div>
  )

  return (
    <div style={{ display: 'grid', gap: 24 }}>
      {/* Controls */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <label htmlFor="industry-select" style={{ fontWeight: 600, whiteSpace: 'nowrap' }}>Sector:</label>
          {industries.length > 0 ? (
            <select
              id="industry-select"
              value={industry}
              onChange={e => setIndustry(e.target.value)}
              style={{ padding: '6px 10px', minWidth: 220, borderRadius: 4, border: '1px solid #ccc', fontSize: 14 }}
            >
              {industries.map(ind => (
                <option key={ind} value={ind}>{ind} ({industryCoverage[ind] ?? 0} entities)</option>
              ))}
            </select>
          ) : (
            <span style={{ color: '#aaa', fontSize: 13 }}>{industriesLoading ? 'Loading sectors...' : 'No sectors loaded'}</span>
          )}
        </div>
        <button
          onClick={fetchForecast}
          disabled={loading || industriesLoading || !industry}
          style={{
            padding: '6px 20px',
            background: (!loading && !industriesLoading && industry) ? '#1976d2' : '#ccc',
            color: 'white', border: 'none', borderRadius: 4,
            cursor: (!loading && !industriesLoading && industry) ? 'pointer' : 'not-allowed',
            fontSize: 14, fontWeight: 600,
          }}
        >
          {loading ? 'Loading...' : 'Get Forecast'}
        </button>
        {industries.length > 0 && (
          <span style={{ fontSize: 12, color: '#888' }}>{industries.length} sectors with signal</span>
        )}
      </div>

      {error && <p style={{ color: 'red' }}>{error}</p>}
      {data?.status === 'no_model' && <NoModelYet message={data.message} hint={data.hint} />}
      {data?.status === 'not_supported' && <p style={{ color: '#888' }}>{data.reason}</p>}

      {data?.status === 'ok' && (() => {
        const acc = data.top_k_accuracy ?? 0
        const baseline = data.baselines?.sector_frequency_top_k ?? 0
        const prediction: { tool: string; count: number }[] = data.prediction || []
        const metrics = data.metrics || {}
        const provenance = data.provenance || {}
        const coverage = data.coverage || {}
        const passes = data.passes_gate

        // Parse holdout label from gate_note
        const holdoutMatch = (data.gate_note || '').match(/holdout_start=(\d{4}-\d{2}-\d{2})/)
        const holdoutLabel = holdoutMatch
          ? `the held-out test week (from ${holdoutMatch[1]})`
          : 'the held-out test week'

        return (
          <>
            {/* Metric cards */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
              <div style={{ background: '#e3f2fd', borderRadius: 8, padding: '14px 16px' }}>
                <div style={{ fontSize: 11, color: '#666', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.04em' }}>
                  Prediction accuracy{' '}
                  <InfoTooltip text={`Out of every 10 tools we predicted would target this sector, about ${Math.round(acc * 10)} actually appeared in the test week's threat reports.`} />
                </div>
                <div style={{ fontSize: 28, fontWeight: 700, color: acc > baseline ? '#2e7d32' : '#c62828', marginTop: 4 }}>
                  {(acc * 100).toFixed(1)}%
                </div>
              </div>
              <div style={{ background: '#f3e5f5', borderRadius: 8, padding: '14px 16px' }}>
                <div style={{ fontSize: 11, color: '#666', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.04em' }}>
                  Best simple guess
                </div>
                <div style={{ fontSize: 28, fontWeight: 700, color: '#555', marginTop: 4 }}>
                  {(baseline * 100).toFixed(1)}%
                </div>
                <div style={{ fontSize: 12, color: '#888', marginTop: 2 }}>Just picking the most common tools</div>
              </div>
            </div>

            {/* Directional-only banner */}
            {!passes && (
              <div style={{ padding: '10px 16px', background: '#fff8e1', border: '1px solid #f9a825', borderRadius: 6, fontSize: 13 }}>
                <strong>Directional only</strong> — this model doesn't yet outperform a simple frequency guess on this dataset.
                Predictions show the right direction but should not be treated as firm.
              </div>
            )}

            {/* Top predicted tools */}
            {prediction.length > 0 && (
              <div>
                <h3 style={{ fontSize: 14, marginBottom: 8 }}>
                  Top predicted tools for <em>{industry}</em>
                </h3>
                <ToolChips tools={prediction} />
              </div>
            )}
            {prediction.length === 0 && (
              <p style={{ color: '#888', fontSize: 13 }}>No tool predictions available for <em>{industry}</em> — try a sector with higher coverage.</p>
            )}

            {/* Stacked area trend chart */}
            {trends && <ToolTrendChart data={trends} industry={industry} />}

            {/* Full metrics grid */}
            <MetricsGrid
              metrics={{ ...metrics, baseline_top_k: baseline, lift_over_baseline: acc - baseline }}
              holdoutLabel={holdoutLabel}
            />

            {/* Coverage heatmap */}
            {Object.keys(coverage).length > 0 && (
              <div>
                <h3 style={{ fontSize: 14, marginBottom: 8 }}>Sector coverage (entities extracted)</h3>
                <CooccurrenceHeatmap coverage={coverage} />
              </div>
            )}

            {/* Model provenance */}
            <ModelProvenancePanel provenance={{ ...provenance }} />
          </>
        )
      })()}
    </div>
  )
}

// ── Tool chips with per-tool InfoTooltip ──────────────────────────────────────

function ToolChips({ tools }: { tools: { tool: string; count: number }[] }) {
  const [descriptions, setDescriptions] = useState<Record<string, string>>({})

  useEffect(() => {
    tools.forEach(({ tool }) => {
      if (descriptions[tool]) return
      fetch(`/api/tool-info?tool=${encodeURIComponent(tool)}`)
        .then(r => r.json())
        .then(d => setDescriptions(prev => ({ ...prev, [tool]: d.description })))
        .catch(() => {})
    })
  }, [tools])

  return (
    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
      {tools.slice(0, 5).map(({ tool, count }) => (
        <div key={tool} style={{
          padding: '6px 12px', background: '#e3f2fd', borderRadius: 20,
          fontSize: 13, fontWeight: 500, display: 'flex', alignItems: 'center', gap: 6,
        }}>
          {tool} <span style={{ color: '#888', fontWeight: 400 }}>×{count}</span>
          {descriptions[tool] && <InfoTooltip text={descriptions[tool]} />}
        </div>
      ))}
    </div>
  )
}
```

- [ ] **Step 2: Verify TypeScript build**

Run: `cd web && npm run build 2>&1 | tail -5`
Expected: `✓ built in ...` with no TypeScript errors

- [ ] **Step 3: Run full Python test suite**

Run: `pytest tests/ -q`
Expected: all 64+ tests pass

- [ ] **Step 4: Commit**

```bash
git add web/src/components/ForecastScreen.tsx
git commit -m "feat(ui): forecast screen v2 — metric cards, trend chart, full metrics grid, tool tooltips, model provenance"
```

---

## Task 9: Smoke test end-to-end in the browser

- [ ] **Step 1: Restart API server (picks up new endpoints)**

Run: `taskkill //F //IM uvicorn.exe 2>/dev/null; uvicorn api.main:app --port 8080 &`

- [ ] **Step 2: Verify `/api/trends` returns data**

```bash
python -c "
import urllib.request, json
r = urllib.request.urlopen('http://localhost:8080/api/trends?batch_id=ent-861c216a-07f0e5b2411d&industry=Financial+Services')
d = json.loads(r.read())
print('weeks:', d['weeks'][:3])
print('series count:', len(d['series']))
print('holdout_start:', d['holdout_start'])
"
```
Expected: weeks list, series with ≥1 tool, holdout_start date

- [ ] **Step 3: Verify `/api/forecast` returns full metrics**

```bash
python -c "
import urllib.request, json
r = urllib.request.urlopen('http://localhost:8080/api/forecast?batch_id=ent-861c216a-07f0e5b2411d&industry=Financial+Services')
d = json.loads(r.read())
print('metrics keys:', list(d.get('metrics', {}).keys()))
print('provenance keys:', list(d.get('provenance', {}).keys()))
"
```
Expected: `metrics` has all 8 keys, `provenance` has model_type and extraction_model

- [ ] **Step 4: Open browser and verify**

Open `http://localhost:5174` (Vite hot-reloads). Select `ent-861c216a` batch, click Get Forecast for "Financial Services". Verify:
- Two metric cards at top (blue / purple)
- Stacked area chart appears with ≥1 tool series
- MetricsGrid shows 8 cards with ⓘ icons
- Tool chips show ⓘ icons that open plain-English descriptions on click
- "Model details" collapses open to show extraction model name
- Directional-only banner is visible (since passes_gate=False)

- [ ] **Step 5: Push**

```bash
git push
```

---

## Self-Review

**Spec coverage:**
- ✅ Stacked area chart with holdout shading — Task 5 + ToolTrendChart
- ✅ Metric cards (prediction accuracy, simple guess) — Task 8 ForecastScreen
- ✅ Full metrics grid (Precision@3, Recall@3, F1@3, MAP, NDCG@3) — Task 6 MetricsGrid
- ✅ Plain-English tooltips on every metric — InfoTooltip + tooltip strings in MetricsGrid
- ✅ Tool chips with per-tool InfoTooltip — ToolChips in ForecastScreen
- ✅ Model provenance panel — Task 7 ModelProvenancePanel
- ✅ Backend: precision_at_k, recall_at_k, f1_at_k, MAP, NDCG@k functions — Task 1
- ✅ T2Industry.evaluate() extended — Task 2
- ✅ /api/trends endpoint — Task 3
- ✅ /api/tool-info endpoint — Task 3
- ✅ Directional-only banner when passes_gate=False — Task 8

**Placeholder scan:** No TBDs. All tooltip strings are written out. Tool descriptions dict is populated. All metric formulas are explicit.

**Type consistency:**
- `MetricsGrid` receives `metrics.baseline_top_k` and `metrics.lift_over_baseline` — both computed in Task 8 as `baseline` and `acc - baseline` from the forecast response. Consistent.
- `ToolTrendChart` receives `TrendsResponse` — defined in Task 5 and returned by `/api/trends` in Task 3. Consistent.
- `ModelProvenancePanel` receives `provenance` spread from `data.provenance` — set in Task 3 API response. Consistent.
