import asyncio
import json
from pathlib import Path

from pte.convert.quarantine import Quarantine
from pte.common.logging import progress, structured_log
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
        self.quarantine = Quarantine()

    def _checkpoint_dir(self, entity_type: str) -> Path:
        """Directory where per-entity checkpoint files are written."""
        p = self._data_dir / "schema" / self._batch_id / "checkpoints" / entity_type
        p.mkdir(parents=True, exist_ok=True)
        return p

    def _already_done(self, entity_type: str) -> set[str]:
        """Return set of entity IDs already extracted (checkpoint files present)."""
        d = self._checkpoint_dir(entity_type)
        return {f.stem for f in d.glob("*.json")}

    def _write_checkpoint(self, entity: PTEEntity, entity_type: str) -> None:
        """Write a single extracted entity to its checkpoint file immediately."""
        p = self._checkpoint_dir(entity_type) / f"{entity.entity_id}.json"
        p.write_text(json.dumps(entity.model_dump(), indent=2))

    def load_checkpoints(self, entity_type: str) -> list[dict]:
        """Load all checkpointed entities for an entity type."""
        d = self._checkpoint_dir(entity_type)
        results = []
        for f in d.glob("*.json"):
            try:
                results.append(json.loads(f.read_text()))
            except json.JSONDecodeError:
                pass
        return results

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

    async def extract_entity_type(
        self,
        records: list[dict],
        entity_type: str,
        resume: bool = True,
    ) -> list[PTEEntity]:
        """Extract all records of a given entity type, with checkpoint/resume support.

        If resume=True (default), skips any entity_id already present as a
        checkpoint file, so the run can be interrupted and restarted safely.
        Each extraction is written to disk immediately after completion.
        """
        done_ids = self._already_done(entity_type) if resume else set()
        pending = [r for r in records if str(r.get("id", "?")) not in done_ids]

        if done_ids:
            progress(f"  {entity_type}: {len(done_ids)} already done, {len(pending)} remaining")
        else:
            progress(f"  {entity_type}: {len(pending)} to extract")

        extracted_now: list[PTEEntity] = []
        for i, record in enumerate(pending):
            entity = await self.extract_one(record)
            if entity:
                self._write_checkpoint(entity, entity_type)
                extracted_now.append(entity)
            if (i + 1) % 10 == 0 or i == 0:
                progress(
                    f"  {entity_type} progress",
                    done=len(done_ids) + i + 1,
                    total=len(records),
                    quarantined=self.quarantine.count(),
                )

        # Load all checkpoints (previously done + just done)
        all_checkpoints = self.load_checkpoints(entity_type)
        progress(
            f"  {entity_type} complete",
            total_on_disk=len(all_checkpoints),
            extracted_this_run=len(extracted_now),
            quarantined=self.quarantine.count(),
        )
        structured_log("extraction_entity_type_complete",
                       entity_type=entity_type,
                       total=len(all_checkpoints),
                       quarantined=self.quarantine.count())
        return [PTEEntity(**c) for c in all_checkpoints]

    def consolidate(self, entity_types: list[str]) -> list[dict]:
        """Merge all checkpoint files across entity types into extracted_entities.json."""
        dest = self._data_dir / "schema" / self._batch_id
        dest.mkdir(parents=True, exist_ok=True)
        all_entities: list[dict] = []
        for et in entity_types:
            all_entities.extend(self.load_checkpoints(et))
        (dest / "extracted_entities.json").write_text(json.dumps(all_entities, indent=2))
        q_path = str(dest / "quarantine.json")
        self.quarantine.dump(q_path)
        progress(f"Consolidated {len(all_entities)} entities → data/schema/{self._batch_id}/extracted_entities.json")
        return all_entities

    async def run(self) -> None:
        """Original run() for observable-based extraction — kept for backward compat."""
        from pte.ingest.raw_store import RawStore
        store = RawStore(base_dir=str(self._data_dir / "raw"))
        records = store.read(self._batch_id, "observable")

        dest = self._data_dir / "schema" / self._batch_id
        dest.mkdir(parents=True, exist_ok=True)
        entities = await self.extract_entity_type(records, "observable", resume=True)
        out = [e.model_dump() for e in entities]
        (dest / "extracted_entities.json").write_text(json.dumps(out, indent=2))
        q_path = str(dest / "quarantine.json")
        self.quarantine.dump(q_path)
