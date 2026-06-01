import asyncio
import json
from pathlib import Path

from pte.convert.discovery import DiscoveryRunner
from pte.gateway.llm_client import LLMClient
from pte.ingest.raw_store import RawStore


class ConversionPipeline:
    def __init__(self, batch_id: str, data_dir: str = "data"):
        self._batch_id = batch_id
        self._data_dir = Path(data_dir)
        self._llm = LLMClient()
        self._store = RawStore(base_dir=str(self._data_dir / "raw"))

    async def run_discovery(self) -> None:
        from pte.common.provenance import make_run_id
        run_id = make_run_id()
        runner = DiscoveryRunner(llm_client=self._llm, data_dir=str(self._data_dir), run_id=run_id)
        observables = self._store.read(self._batch_id, "observable")
        by_feed: dict[str, list[str]] = {}
        for obs in observables:
            feed = obs.get("source_feed", obs.get("source", "unknown"))
            blob = obs.get("description", obs.get("value", ""))
            by_feed.setdefault(feed, []).append(blob)

        tasks = []
        for feed, blobs in by_feed.items():
            tasks.append(runner.run_slice(
                batch_id=self._batch_id,
                feed=feed,
                entity_type="observable",
                blobs=blobs,
            ))
        await asyncio.gather(*tasks)

    async def run_extraction(self) -> None:
        from pte.convert.extraction import ExtractionRunner
        runner = ExtractionRunner(
            llm_client=self._llm,
            data_dir=str(self._data_dir),
            batch_id=self._batch_id,
        )
        await runner.run()
