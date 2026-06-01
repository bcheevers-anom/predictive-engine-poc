import asyncio
from typing import Callable

class WorkerPool:
    def __init__(self, max_concurrency: int = 8):
        self._sem = asyncio.Semaphore(max_concurrency)

    async def map(self, fn: Callable, items: list, **kwargs) -> list:
        """Run fn(item) for each item, bounded by max_concurrency. Returns results in input order."""
        async def bounded(item):
            async with self._sem:
                result = fn(item, **kwargs)
                if asyncio.iscoroutine(result):
                    return await result
                return result

        return await asyncio.gather(*[bounded(item) for item in items])

    async def map_keyed(self, fn: Callable, items: list) -> dict:
        """fn must return (key, value). Returns {key: value} dict."""
        async def bounded(item):
            async with self._sem:
                result = fn(item)
                if asyncio.iscoroutine(result):
                    return await result
                return result

        pairs = await asyncio.gather(*[bounded(item) for item in items])
        return dict(pairs)
