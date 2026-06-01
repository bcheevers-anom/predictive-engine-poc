import pytest
import numpy as np
from pte.predict.baselines import EpssBaseline, FrequencyBaseline
from pte.evaluate.splits import time_split, rolling_window_split

def test_epss_baseline_ranks_higher_epss_first():
    data = [
        {"entity_id": "v1", "epss_score": 0.02, "exploited": 0},
        {"entity_id": "v2", "epss_score": 0.45, "exploited": 1},
        {"entity_id": "v3", "epss_score": 0.10, "exploited": 0},
    ]
    baseline = EpssBaseline()
    ranked = baseline.rank(data)
    assert ranked[0]["entity_id"] == "v2"

def test_frequency_baseline_ranks_by_count():
    data = [
        {"entity_id": "t1", "tool": "Cobalt Strike", "count": 10},
        {"entity_id": "t2", "tool": "Mimikatz", "count": 3},
        {"entity_id": "t3", "tool": "PsExec", "count": 7},
    ]
    baseline = FrequencyBaseline(field="count")
    ranked = baseline.rank(data)
    assert ranked[0]["entity_id"] == "t1"

def test_time_split():
    dates = ["2025-01-01", "2025-02-01", "2025-03-01", "2025-04-01", "2025-05-01"]
    records = [{"id": str(i), "ts": d} for i, d in enumerate(dates)]
    train, test = time_split(records, ts_field="ts", holdout_days=60)
    test_dates = {r["ts"] for r in test}
    assert "2025-05-01" in test_dates
    assert "2025-01-01" not in test_dates

from pte.predict.t1_vuln_exploit import T1VulnExploit

def test_t1_fits_and_predicts(tmp_path):
    from pte.features.store import FeatureStore
    store = FeatureStore(base_dir=str(tmp_path / "features"))
    records = [
        {"entity_id": f"cve-{i}", "epss_score": 0.01 * i, "cvss_score": float(i % 10), "tag_count": i % 5, "tier": "OBSERVED", "exploited": int(i > 8)}
        for i in range(1, 20)
    ]
    store.write("batch001", "vulnerability_features", records)

    t1 = T1VulnExploit(batch_id="batch001", data_dir=str(tmp_path))
    t1.fit()
    report = t1.evaluate()
    assert "pr_auc" in report
    assert "epss_baseline_pr_auc" in report
    assert report["pr_auc"] >= 0.0

def test_t1_aql_port_idiom_recorded():
    assert "LogisticRegression" in T1VulnExploit.aql_port_idiom or "RandomForest" in T1VulnExploit.aql_port_idiom

from pte.predict.t2_industry import T2Industry

def test_t2_industry_produces_ranked_forecast(tmp_path):
    from pte.features.store import FeatureStore
    store = FeatureStore(base_dir=str(tmp_path / "features"))
    records = [
        {"entity_id": f"e{i}", "industry": "Oil and Gas", "tool": "Cobalt Strike", "tactic": "Lateral Movement", "corroboration_score": 0.5, "tier": "LLM_EXTRACTED"}
        for i in range(30)
    ] + [
        {"entity_id": f"f{i}", "industry": "Finance", "tool": "Mimikatz", "tactic": "Credential Access", "corroboration_score": 0.4, "tier": "LLM_EXTRACTED"}
        for i in range(10)
    ]
    store.write("batch001", "industry_tool_cooccur", records)

    t2 = T2Industry(batch_id="batch001", data_dir=str(tmp_path))
    t2.fit()
    report = t2.evaluate()
    assert "top_k_accuracy" in report
    assert report.get("coverage_reported") is True

def test_t2_industry_aql_port_idiom():
    assert "RandomForest" in T2Industry.aql_port_idiom
