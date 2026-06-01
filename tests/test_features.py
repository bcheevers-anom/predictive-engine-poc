import pytest
import json
from pathlib import Path
from pte.features.store import FeatureStore
from pte.schema.tiers import DataTier, TierPolicy

def test_feature_store_writes_and_reads(tmp_path):
    store = FeatureStore(base_dir=str(tmp_path))
    records = [
        {"entity_id": "e1", "epss_score": 0.05, "cvss_score": 9.1, "tier": "OBSERVED"},
        {"entity_id": "e2", "epss_score": 0.12, "cvss_score": 7.5, "tier": "OBSERVED"},
    ]
    store.write("batch001", "vulnerability_features", records)
    rows = store.read("batch001", "vulnerability_features")
    assert len(rows) == 2
    assert rows[0]["entity_id"] in ("e1", "e2")

def test_feature_store_tier_filter(tmp_path):
    store = FeatureStore(base_dir=str(tmp_path))
    records = [
        {"entity_id": "e1", "industry": "Oil and Gas", "tier": "LLM_EXTRACTED"},
        {"entity_id": "e2", "industry": "Finance", "tier": "OBSERVED"},
    ]
    store.write("batch001", "industry_features", records)
    policy = TierPolicy(accepted_tiers=["OBSERVED"])
    rows = store.read("batch001", "industry_features", tier_policy=policy)
    assert len(rows) == 1
    assert rows[0]["entity_id"] == "e2"
