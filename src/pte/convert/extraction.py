import asyncio
import json
import sys
import time
from pathlib import Path

from pte.convert.quarantine import Quarantine
from pte.common.logging import progress, structured_log
from pte.common.errors import RateLimitError
from pte.gateway.llm_client import LLMClient
from pte.schema.models import PTEEntity, ProvenanceRecord

PROMPT_PATH = Path(__file__).parents[3] / "prompts" / "entity_extraction_v1.txt"
SKILL_VERSION = "entity_extraction-v1"

# Dynamic concurrency state — shared across all extract_entity_type calls
_MIN_CONCURRENCY = 1
_RATE_LIMIT_BACKOFF_SECONDS = 30


def _rate_limit_banner(current_concurrency: int, new_concurrency: int) -> None:
    """Print a prominent warning when Bedrock rate limits."""
    print("\n" + "!" * 60, flush=True)
    print("!  BEDROCK RATE LIMIT HIT", flush=True)
    print(f"!  Dropping concurrency: {current_concurrency} -> {new_concurrency}", flush=True)
    print(f"!  Pausing {_RATE_LIMIT_BACKOFF_SECONDS}s before retrying...", flush=True)
    print("!" * 60 + "\n", flush=True)


class ExtractionRunner:
    def __init__(
        self,
        llm_client: LLMClient,
        data_dir: str = "data",
        batch_id: str = "",
        run_id: str = "",
        max_concurrency: int = 10,
    ):
        self._llm = llm_client
        self._data_dir = Path(data_dir)
        self._batch_id = batch_id
        self._run_id = run_id
        self._max_concurrency = max_concurrency
        self._current_concurrency = max_concurrency
        self.quarantine = Quarantine()

    def _checkpoint_dir(self, entity_type: str) -> Path:
        p = self._data_dir / "schema" / self._batch_id / "checkpoints" / entity_type
        p.mkdir(parents=True, exist_ok=True)
        return p

    def _already_done(self, entity_type: str) -> set[str]:
        d = self._checkpoint_dir(entity_type)
        return {f.stem for f in d.glob("*.json")}

    def _write_checkpoint(self, entity: PTEEntity, entity_type: str) -> None:
        p = self._checkpoint_dir(entity_type) / f"{entity.entity_id}.json"
        p.write_text(json.dumps(entity.model_dump(), indent=2))

    def load_checkpoints(self, entity_type: str) -> list[dict]:
        d = self._checkpoint_dir(entity_type)
        results = []
        for f in d.glob("*.json"):
            try:
                results.append(json.loads(f.read_text()))
            except json.JSONDecodeError:
                pass
        return results

    async def extract_one(self, raw: dict) -> PTEEntity | None:
        """Extract one entity. Returns None and quarantines on non-rate-limit errors.
        Raises RateLimitError so the caller can requeue and reduce concurrency."""
        entity_id = str(raw.get("id", "?"))
        try:
            prompt_template = PROMPT_PATH.read_text()
            prompt = prompt_template.format(
                entity_id=entity_id,
                entity_type=raw.get("entity_type", ""),
                source_feed=raw.get("source_feed", ""),
                stix_id=raw.get("stix_id", ""),
                description=raw.get("description", ""),
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
        except RateLimitError:
            raise  # caller handles requeue + concurrency drop
        except Exception as exc:
            self.quarantine.add(entity_id, str(exc), {"type": raw.get("entity_type", "")})
            return None

    async def extract_entity_type(
        self,
        records: list[dict],
        entity_type: str,
        resume: bool = True,
    ) -> list[PTEEntity]:
        """Extract all records with parallel workers and dynamic concurrency backoff.

        On RateLimitError:
          - requeues the failed record at the front of the pending list
          - drops concurrency by half (floor _MIN_CONCURRENCY)
          - waits _RATE_LIMIT_BACKOFF_SECONDS before retrying
          - prints a prominent banner so the operator sees it immediately

        Each successful extraction is checkpointed to disk immediately.
        """
        done_ids = self._already_done(entity_type) if resume else set()
        pending = [r for r in records if str(r.get("id", "?")) not in done_ids]

        if done_ids:
            progress(f"  {entity_type}: {len(done_ids)} already done, {len(pending)} remaining")
        else:
            progress(f"  {entity_type}: {len(pending)} to extract")

        extracted_now: list[PTEEntity] = []
        total_done = 0

        while pending:
            concurrency = self._current_concurrency
            sem = asyncio.Semaphore(concurrency)
            batch = pending[:concurrency]

            async def bounded_extract(record: dict) -> tuple[dict, PTEEntity | None, bool]:
                """Returns (record, result, rate_limited)."""
                async with sem:
                    try:
                        entity = await self.extract_one(record)
                        return (record, entity, False)
                    except RateLimitError:
                        return (record, None, True)

            results = await asyncio.gather(*[bounded_extract(r) for r in batch])

            rate_limited_records = []
            for record, entity, was_rate_limited in results:
                if was_rate_limited:
                    rate_limited_records.append(record)
                else:
                    pending.pop(0)  # successfully processed
                    total_done += 1
                    if entity:
                        self._write_checkpoint(entity, entity_type)
                        extracted_now.append(entity)

            if rate_limited_records:
                new_concurrency = max(_MIN_CONCURRENCY, self._current_concurrency // 2)
                _rate_limit_banner(self._current_concurrency, new_concurrency)
                self._current_concurrency = new_concurrency
                # Requeue at front — already removed successfully processed ones above
                # rate_limited_records are still in pending (we didn't pop them)
                await asyncio.sleep(_RATE_LIMIT_BACKOFF_SECONDS)
            else:
                # Successful batch — show progress every 10 entities
                if total_done % 10 == 0 or total_done <= concurrency:
                    progress(
                        f"  {entity_type} progress",
                        done=len(done_ids) + total_done,
                        total=len(records),
                        concurrency=self._current_concurrency,
                        quarantined=self.quarantine.count(),
                    )

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
        dest = self._data_dir / "schema" / self._batch_id
        dest.mkdir(parents=True, exist_ok=True)
        all_entities: list[dict] = []
        for et in entity_types:
            all_entities.extend(self.load_checkpoints(et))
        (dest / "extracted_entities.json").write_text(json.dumps(all_entities, indent=2))
        q_path = str(dest / "quarantine.json")
        self.quarantine.dump(q_path)
        progress(f"Consolidated {len(all_entities)} entities -> data/schema/{self._batch_id}/extracted_entities.json")
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
        self.quarantine.dump(str(dest / "quarantine.json"))
