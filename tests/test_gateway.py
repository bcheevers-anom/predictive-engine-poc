import asyncio
import pytest
from pte.gateway.rate_limit import TokenBucketLimiter
from pte.gateway.concurrency import WorkerPool

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
