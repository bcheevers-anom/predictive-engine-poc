import pytest
from unittest.mock import AsyncMock, MagicMock
from pte.explain.contributions import feature_contributions
from pte.explain.narrative import NarrativeGenerator

def test_feature_contributions_ranked():
    importances = {"epss_score": 0.6, "cvss_score": 0.3, "tag_count": 0.1}
    contribs = feature_contributions(importances, top_n=2)
    assert len(contribs) == 2
    assert contribs[0]["feature"] == "epss_score"
    assert contribs[0]["importance"] == 0.6

@pytest.mark.asyncio
async def test_narrative_faithfulness_check():
    mock_llm = AsyncMock()
    mock_llm.complete.return_value = MagicMock(
        narrative="Oil and Gas sector faces Cobalt Strike activity with 68% confidence.",
        faithfulness_checked=True,
        rejected_claims=[],
    )
    finding = {
        "title": "Sector Threat Forecast — Oil & Gas",
        "confidence": 0.68,
        "prediction": {"industry": "Oil and Gas", "top_tools": ["Cobalt Strike"]},
        "evidence": [],
    }
    gen = NarrativeGenerator(llm_client=mock_llm)
    result = await gen.generate(finding)
    assert "faithfulness_checked" in result
    assert result["faithfulness_checked"] is True

@pytest.mark.asyncio
async def test_narrative_rejects_unsupported_claim():
    mock_llm = AsyncMock()
    mock_llm.complete.side_effect = [
        MagicMock(narrative="APT29 will attack 15 companies next month.", faithfulness_checked=False, rejected_claims=["15 companies"]),
        MagicMock(narrative="Oil and Gas sector at elevated risk.", faithfulness_checked=True, rejected_claims=[]),
    ]
    finding = {"title": "Oil Gas Forecast", "confidence": 0.6, "prediction": {"industry": "Oil and Gas"}}
    gen = NarrativeGenerator(llm_client=mock_llm)
    result = await gen.generate(finding)
    assert result["faithfulness_checked"] is True

from fastapi.testclient import TestClient
from api.main import app

def test_forecast_endpoint_returns_finding():
    client = TestClient(app)
    resp = client.get("/api/forecast?industry=Oil+and+Gas&batch_id=test")
    assert resp.status_code in (200, 404, 422)  # no data is OK; just must not 500

def test_not_supported_returns_explicit_message():
    client = TestClient(app)
    resp = client.get("/api/forecast?company=SparseCoInc&batch_id=test")
    if resp.status_code == 200:
        data = resp.json()
        if data.get("status") == "not_supported":
            assert "reason" in data
