import json
import pytest
from pte.convert.refang import refang
from pte.convert.normalize_tags import normalize_tag, is_workflow_tag
from pte.convert.quarantine import Quarantine
from pte.convert.confidence import extraction_confidence

def test_refang_ip():
    assert refang("1.1.1[.]1") == "1.1.1.1"

def test_refang_url():
    assert refang("hxxp://evil[.]com/path") == "http://evil.com/path"

def test_refang_already_clean():
    assert refang("10.0.0.1") == "10.0.0.1"

def test_workflow_tag_excluded():
    assert is_workflow_tag("Ilamona_send_to_splunk") is True
    assert is_workflow_tag("PIR_energy_sector") is True
    assert is_workflow_tag("Oil and Gas") is False

def test_normalize_tag_maps_dialect():
    assert normalize_tag("win.cobalt_strike", dialect="generic") == "Cobalt Strike"
    assert normalize_tag("UNKNOWNTAG_XYZ", dialect="generic") == "UNKNOWNTAG_XYZ"

def test_quarantine_counts():
    q = Quarantine()
    q.add("record_001", "invalid_stix_id", {"field": "stix_id"})
    q.add("record_002", "missing_required_field", {"field": "entity_type"})
    assert q.count() == 2
    assert q.rate(total=100) == 0.02

def test_extraction_confidence_range():
    score = extraction_confidence(
        fields_extracted=["industry", "tool"],
        fields_attempted=["industry", "tool", "company", "tactic"],
        model_response_finishtype="end_turn",
    )
    assert 0.0 <= score <= 1.0


# Task 12: Tier-1 Clean tests
from pte.convert.tier1_clean import Tier1Cleaner
from pte.schema.models import PTEEntity

def test_tier1_cleans_observable():
    raw = {
        "id": "1001",
        "itype": "ip",
        "value": "1[.]1[.]1[.]1",
        "source": "threatfox",
        "confidence": 80,
        "tags": [{"name": "Ilamona_send_to_siem"}, {"name": "Cobalt Strike"}],
        "created_ts": "2026-01-15T00:00:00",
    }
    cleaner = Tier1Cleaner(run_id="test-run")
    entity = cleaner.clean_observable(raw)
    assert entity.entity_id == "1001"
    assert entity.observable["value"] == "1.1.1.1"
    assert "Ilamona_send_to_siem" not in entity.tags
    assert "Cobalt Strike" in entity.tags
    assert entity.validation_status == "ok"
    assert entity.provenance.tier == "OBSERVED"


# Task 14: Discovery pass tests
from unittest.mock import AsyncMock, MagicMock
from pte.convert.discovery import DiscoveryRunner

@pytest.mark.asyncio
async def test_discovery_emits_coverage_report(tmp_path):
    mock_llm = AsyncMock()
    mock_llm.complete.return_value = MagicMock(
        dimensions={
            "industry": {"presence_rate": 0.7, "mean_confidence": 0.65},
            "tool":     {"presence_rate": 0.9, "mean_confidence": 0.85},
            "tactic":   {"presence_rate": 0.6, "mean_confidence": 0.75},
            "technique":{"presence_rate": 0.5, "mean_confidence": 0.70},
            "company":  {"presence_rate": 0.2, "mean_confidence": 0.40},
            "date":     {"presence_rate": 0.3, "mean_confidence": 0.80},
        },
        quarantine_count=0,
        sample_size=10,
        notes="",
    )
    runner = DiscoveryRunner(llm_client=mock_llm, data_dir=str(tmp_path), run_id="test")
    await runner.run_slice(batch_id="batch001", feed="gti", entity_type="campaign", blobs=["blob1"] * 10)
    report_path = tmp_path / "coverage" / "batch001" / "discovery_gti_campaign.json"
    assert report_path.exists()
    data = json.loads(report_path.read_text())
    assert "dimensions" in data
    assert data["sample_size"] == 10
    assert 0.0 <= data["dimensions"]["industry"]["presence_rate"] <= 1.0
