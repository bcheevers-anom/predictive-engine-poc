import json
from pathlib import Path

import pytest
from pte.common.errors import AuthError, RateLimitError, ValidationError as PTEValidationError
from pte.common.provenance import make_run_id, stamp_provenance

FIXTURES_DIR = Path(__file__).parent / "fixtures"

def test_auth_error_message():
    err = AuthError("bedrock")
    assert "aws sso login" in str(err).lower()

def test_rate_limit_error():
    err = RateLimitError(backend="bedrock", retry_after=5.0)
    assert err.retry_after == 5.0

def test_stamp_provenance():
    record = {"entity_id": "x"}
    stamped = stamp_provenance(record, run_id="r1", tier="OBSERVED", skill_version="v1")
    assert stamped["provenance"]["run_id"] == "r1"
    assert stamped["provenance"]["tier"] == "OBSERVED"


@pytest.fixture
def observable_eventostotales():
    return json.loads((FIXTURES_DIR / "eventostotales_observable.json").read_text())


@pytest.fixture
def observable_threatfox_ip():
    return json.loads((FIXTURES_DIR / "threatfox_210_16_168_11.json").read_text())


@pytest.fixture
def cve_fixture():
    return json.loads((FIXTURES_DIR / "cve_2026_48522.json").read_text())


@pytest.fixture
def gti_campaign_html():
    return (FIXTURES_DIR / "gti_campaign_timeline.html").read_text()
