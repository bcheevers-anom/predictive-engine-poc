import asyncio
import time
from dataclasses import dataclass, field

@dataclass
class TokenBucketLimiter:
    tpm_limit: int          # tokens per minute
    rpm_limit: int          # requests per minute
    _token_bucket: float = field(init=False, default=0.0)
    _request_bucket: float = field(init=False, default=0.0)
    _last_refill: float = field(init=False, default=0.0)
    _lock: asyncio.Lock = field(init=False, default=None)

    def __post_init__(self):
        self._token_bucket = float(self.tpm_limit)
        self._request_bucket = float(self.rpm_limit)
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._token_bucket = min(
            float(self.tpm_limit),
            self._token_bucket + elapsed * (self.tpm_limit / 60.0),
        )
        self._request_bucket = min(
            float(self.rpm_limit),
            self._request_bucket + elapsed * (self.rpm_limit / 60.0),
        )
        self._last_refill = now

    async def acquire(self, input_tokens: int = 0, output_tokens: int = 0) -> None:
        total = input_tokens + output_tokens
        async with self._lock:
            while True:
                self._refill()
                if self._token_bucket >= total and self._request_bucket >= 1:
                    self._token_bucket -= total
                    self._request_bucket -= 1
                    return
                # Wait for ~100ms then retry
                await asyncio.sleep(0.1)
