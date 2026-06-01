import asyncio
import json
from pathlib import Path

from pte.convert.quarantine import Quarantine
from pte.gateway.concurrency import WorkerPool
from pte.gateway.llm_client import LLMClient
from pte.schema.models import PTEEntity, ProvenanceRecord

PROMPT_PATH = Path(__file__).parents[3] / "prompts" / "entity_extraction_v1.txt"
SKILL_VERSION = "entity_extraction-v1"


class ExtractionRunner:
    def __init__(
        self,
        llm_client: LLMClient,
        data_dir: str = "data",
        batch_id: str = "",
        run_id: str = "",
        max_concurrency: int = 8,
    ):
        self._llm = llm_client
        self._data_dir = Path(data_dir)
        self._batch_id = batch_id
        self._run_id = run_id
        self._pool = WorkerPool(max_concurrency=max_concurrency)
        self.quarantine = Quarantine()

    async def extract_one(self, raw: dict) -> PTEEntity | None:
        entity_id = str(raw.get("id", "?"))
        try:
            prompt_template = PROMPT_PATH.read_text()
            description = raw.get("description", "")
            prompt = prompt_template.format(
                entity_id=entity_id,
                entity_type=raw.get("entity_type", ""),
                source_feed=raw.get("source_feed", ""),
                stix_id=raw.get("stix_id", ""),
                description=description,
            )
            result: PTEEntity = await self._llm.complete(
                prompt=prompt,
                model_tier="strong",
                schema=PTEEntity,
            )
            result.provenance = ProvenanceRecord(
                run_id=self._run_id,
                tier="LLM_EXTRACTED",
                skill_version=SKILL_VERSION,
            )
            result.entity_id = entity_id
            result.source_feed = raw.get("source_feed", "")
            return result
        except Exception as exc:
            self.quarantine.add(entity_id, str(exc), {"type": raw.get("entity_type", "")})
            return None

    async def run(self) -> None:
        from pte.ingest.raw_store import RawStore
        store = RawStore(base_dir=str(self._data_dir / "raw"))
        records = store.read(self._batch_id, "observable")

        async def process(raw: dict) -> PTEEntity | None:
            return await self.extract_one(raw)

        results = await self._pool.map(process, records)
        entities = [r for r in results if r is not None]

        dest = self._data_dir / "schema" / self._batch_id
        dest.mkdir(parents=True, exist_ok=True)
        out = [e.model_dump() for e in entities]
        (dest / "extracted_entities.json").write_text(json.dumps(out, indent=2))

        q_path = str(dest / "quarantine.json")
        self.quarantine.dump(q_path)
