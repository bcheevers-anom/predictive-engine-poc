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
