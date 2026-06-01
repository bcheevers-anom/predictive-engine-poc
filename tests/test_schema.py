import pytest
from pte.schema.models import PTEEntity, SRO, Finding
from pte.schema.tiers import DataTier, TierPolicy

def test_pte_entity_requires_tier():
    e = PTEEntity(
        entity_id="test-1",
        entity_type="malware",
        source_feed="threatfox",
        validation_status="ok",
    )
    assert e.entity_id == "test-1"

def test_tier_policy_rejects_llm_extracted_for_t1():
    policy = TierPolicy(accepted_tiers=["OBSERVED", "DERIVED"])
    assert policy.accepts(DataTier.OBSERVED)
    assert not policy.accepts(DataTier.LLM_EXTRACTED)

def test_llm_extracted_field_has_confidence():
    e = PTEEntity(
        entity_id="test-2",
        entity_type="campaign",
        source_feed="gti",
        validation_status="ok",
        industry=["Oil and Gas"],
        llm_extraction_confidence=0.72,
    )
    assert e.llm_extraction_confidence == 0.72

def test_finding_ocsf_shape():
    f = Finding(
        title="Sector Threat Forecast — Oil & Gas",
        type_name="PTE/T2-Industry",
        severity="high",
        confidence=0.68,
        time_window={"start": "2026-06-01", "end": "2026-09-01"},
        run_id="abc123",
    )
    assert f.category_name == "Findings"
    assert f.class_name == "Detection Finding"
