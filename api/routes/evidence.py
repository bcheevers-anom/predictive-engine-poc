from fastapi import APIRouter, Query, HTTPException
from pathlib import Path

router = APIRouter()

@router.get("/evidence/{source_id}")
async def get_evidence(source_id: str, batch_id: str = Query(...), data_dir: str = "data"):
    from pte.ingest.raw_store import RawStore
    store = RawStore(base_dir=str(Path(data_dir) / "raw"))
    records = store.read(batch_id, "observable")
    match = next((r for r in records if str(r.get("id")) == source_id), None)
    if not match:
        raise HTTPException(status_code=404, detail=f"Source {source_id} not found in batch {batch_id}")
    return match
