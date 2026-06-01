import asyncio
import pytest
from unittest.mock import patch, MagicMock
from pte.gateway.rate_limit import TokenBucketLimiter
from pte.gateway.concurrency import WorkerPool
from pte.common.errors import AuthError

@pytest.mark.asyncio
async def test_rate_limiter_allows_burst():
    limiter = TokenBucketLimiter(tpm_limit=100000, rpm_limit=60)
    # Should not raise for a small request
    await limiter.acquire(input_tokens=100, output_tokens=50)

@pytest.mark.asyncio
async def test_worker_pool_processes_all():
    results = []
    async def job(x):
        results.append(x * 2)
    pool = WorkerPool(max_concurrency=4)
    await pool.map(job, list(range(10)))
    assert sorted(results) == [i * 2 for i in range(10)]

@pytest.mark.asyncio
async def test_worker_pool_keyed_output(tmp_path):
    pool = WorkerPool(max_concurrency=2)
    outputs = await pool.map_keyed(
        lambda item: (item["key"], {"result": item["key"] + "_done"}),
        [{"key": "a"}, {"key": "b"}],
    )
    assert outputs["a"] == {"result": "a_done"}
    assert outputs["b"] == {"result": "b_done"}


def test_cost_tracker_accumulates():
    from pte.gateway.cost import CostTracker
    tracker = CostTracker(backend="bedrock", model_id="us.anthropic.claude-haiku-4-5-20251001")
    tracker.record(input_tokens=1000, output_tokens=200)
    tracker.record(input_tokens=500, output_tokens=100)
    summary = tracker.summary()
    assert summary["total_input_tokens"] == 1500
    assert summary["total_output_tokens"] == 300
    assert summary["estimated_cost_usd"] > 0


def test_llm_client_fails_fast_without_session(monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "bedrock")
    import botocore.exceptions
    from pte.gateway.llm_client import LLMClient
    with patch("boto3.Session") as mock_session:
        mock_session.return_value.client.side_effect = (
            botocore.exceptions.NoCredentialsError()
        )
        client = LLMClient()
        with pytest.raises(AuthError):
            asyncio.run(client.complete(prompt="test", model_tier="fast"))


@pytest.mark.asyncio
async def test_read_only_guard():
    """Client must not expose any write methods."""
    from pte.gateway.threatstream import ThreatStreamClient
    client = ThreatStreamClient(api_user="test@test.com", api_key="key")
    assert not hasattr(client, "patch")
    assert not hasattr(client, "put")
    assert not hasattr(client, "delete")
    assert not hasattr(client, "post_intelligence")


def test_sha256_verification_pass(tmp_path):
    import hashlib
    from pte.gateway.snapshot import verify_sha256
    data = b"test payload"
    f = tmp_path / "chunk.json"
    f.write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    assert verify_sha256(str(f), digest) is True


def test_sha256_verification_fail(tmp_path):
    import hashlib
    from pte.gateway.snapshot import verify_sha256
    f = tmp_path / "chunk.json"
    f.write_bytes(b"bad data")
    assert verify_sha256(str(f), "0" * 64) is False
