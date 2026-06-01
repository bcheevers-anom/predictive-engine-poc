import pytest
from pte.common.errors import AuthError, RateLimitError, ValidationError as PTEValidationError
from pte.common.provenance import make_run_id, stamp_provenance

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
