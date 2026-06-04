"""
Resumable entity extraction for the PTE PoC.

Run:  python run_extraction.py
Resume after interruption: python run_extraction.py  (same command — it skips already-done IDs)

Progress is checkpointed per entity after each LLM call, so the laptop can be
closed or the process killed at any time without losing work.
"""
from dotenv import load_dotenv
load_dotenv()

import asyncio
import json
from pathlib import Path
from pte.convert.extraction import ExtractionRunner
from pte.gateway.llm_client import LLMClient
from pte.ingest.raw_store import RawStore
from pte.common.provenance import make_run_id
from pte.common.logging import progress

# Use the full 2.5yr batch if available, otherwise fall back to the May 2026 entity batch
_STATE = Path("data/ingest_state.json")
ENTITY_BATCH = (
    json.loads(_STATE.read_text()).get("batch_id")
    if _STATE.exists()
    else "ent-861c216a-07f0e5b2411d"
)
ENTITY_TYPES = ["campaign", "actor", "malware"]
MAX_DESCRIPTION_CHARS = 4000


async def main():
    llm = LLMClient()
    store = RawStore(base_dir="data/raw")
    runner = ExtractionRunner(
        llm_client=llm,
        data_dir="data",
        batch_id=ENTITY_BATCH,
        run_id=make_run_id(),
        max_concurrency=10,  # 10 parallel Bedrock calls — well within 60 RPM limit
    )

    progress("=== PTE Entity Extraction (resumable) ===", batch_id=ENTITY_BATCH)
    progress("Interrupt any time — progress is checkpointed per entity.")
    progress("Re-run the same command to resume from where you left off.")
    progress("")

    for entity_type in ENTITY_TYPES:
        records = store.read(ENTITY_BATCH, entity_type)
        records_with_desc = [
            {
                "id": str(r.get("id", f"{entity_type}-{i}")),
                "entity_type": entity_type,
                "source_feed": r.get("source") or r.get("source_feed", ""),
                "stix_id": r.get("uuid", ""),
                "description": (r.get("description") or "")[:MAX_DESCRIPTION_CHARS],
            }
            for i, r in enumerate(records)
            if (r.get("description") or "").strip()
        ]

        await runner.extract_entity_type(records_with_desc, entity_type, resume=True)

    # Consolidate all checkpoints into extracted_entities.json
    all_entities = runner.consolidate(ENTITY_TYPES)
    progress("", )
    progress("=== Extraction session complete ===",
             total_entities=len(all_entities),
             batch_id=ENTITY_BATCH)
    print(f"\nBATCH_ID={ENTITY_BATCH}")
    print(f"Entities on disk: {len(all_entities)}")
    print(f"Next step: python run_features_train.py")


if __name__ == "__main__":
    asyncio.run(main())
