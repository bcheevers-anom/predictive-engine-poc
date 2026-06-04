"""
Resumable entity extraction for the PTE PoC.

Run:               python run_extraction.py
Custom concurrency: python run_extraction.py --concurrency 5
Resume:             python run_extraction.py  (same command — skips already-done IDs)

Progress is checkpointed per entity after each LLM call.
Close the laptop any time — rerun to resume from where you left off.

On Bedrock rate limits:
  - A prominent !!!!! banner is printed
  - Concurrency is halved automatically
  - The failed entity is retried after a 30s pause
  - No data is lost
"""
from dotenv import load_dotenv
load_dotenv()

import argparse
import asyncio
import json
from pathlib import Path
from pte.convert.extraction import ExtractionRunner
from pte.gateway.llm_client import LLMClient
from pte.ingest.raw_store import RawStore
from pte.common.provenance import make_run_id
from pte.common.logging import progress

# Use the full 2.5yr batch if available, otherwise fall back to May 2026 entity batch
_STATE = Path("data/ingest_state.json")
ENTITY_BATCH = (
    json.loads(_STATE.read_text()).get("batch_id")
    if _STATE.exists()
    else "ent-861c216a-07f0e5b2411d"
)
ENTITY_TYPES = ["campaign", "actor", "malware"]
MAX_DESCRIPTION_CHARS = 4000


async def main(concurrency: int) -> None:
    llm = LLMClient()
    store = RawStore(base_dir="data/raw")
    runner = ExtractionRunner(
        llm_client=llm,
        data_dir="data",
        batch_id=ENTITY_BATCH,
        run_id=make_run_id(),
        max_concurrency=concurrency,
    )

    progress("=== PTE Entity Extraction (resumable) ===", batch_id=ENTITY_BATCH)
    progress(f"Concurrency: {concurrency} parallel Bedrock calls")
    progress("Interrupt any time — progress is checkpointed per entity.")
    progress("Rate limits handled automatically — concurrency drops if needed.")
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
    progress("")
    progress("=== Extraction session complete ===",
             total_entities=len(all_entities),
             batch_id=ENTITY_BATCH)
    print(f"\nBATCH_ID={ENTITY_BATCH}")
    print(f"Entities on disk: {len(all_entities)}")
    print(f"Next step: pte features build --batch-id {ENTITY_BATCH}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Resumable PTE entity extraction")
    parser.add_argument(
        "--concurrency", "-c",
        type=int,
        default=10,
        help="Number of parallel Bedrock calls (default: 10). "
             "Drops automatically on rate limit. Safe range: 1-20.",
    )
    args = parser.parse_args()

    print(f"Starting extraction with concurrency={args.concurrency}")
    print(f"Batch: {ENTITY_BATCH}")
    print(f"Entity types: {', '.join(ENTITY_TYPES)}")
    print()

    asyncio.run(main(args.concurrency))
