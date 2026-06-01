import asyncio
from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel

router = APIRouter()


class BatchRequest(BaseModel):
    from_date: str
    to_date: str
    feeds: list[str] | None = None
    ingest_only: bool = False


@router.post("/devpanel/batch")
async def trigger_batch(req: BatchRequest, background_tasks: BackgroundTasks):
    from dotenv import load_dotenv
    load_dotenv()
    from pte.gateway.threatstream import ThreatStreamClient
    from pte.ingest.frozen_batch import FrozenBatchRunner

    ts = ThreatStreamClient()
    runner = FrozenBatchRunner(ts_client=ts)

    async def run():
        batch_id = await runner.run(from_date=req.from_date, to_date=req.to_date, feeds=req.feeds)
        if not req.ingest_only:
            from pte.convert.pipeline import ConversionPipeline
            pipeline = ConversionPipeline(batch_id=batch_id)
            await pipeline.run_discovery()
            await pipeline.run_extraction()
            from pte.features.build import FeatureBuilder
            builder = FeatureBuilder(batch_id=batch_id)
            await builder.build()
        return batch_id

    background_tasks.add_task(lambda: asyncio.run(run()))
    return {"status": "started", "from_date": req.from_date, "to_date": req.to_date}


@router.get("/devpanel/batches")
async def list_batches(data_dir: str = "data"):
    import json
    from pathlib import Path
    frozen_dir = Path(data_dir) / "frozen"
    if not frozen_dir.exists():
        return {"batches": []}
    batches = []
    for batch_dir in frozen_dir.iterdir():
        manifest_path = batch_dir / "manifest.json"
        if manifest_path.exists():
            batches.append(json.loads(manifest_path.read_text()))
    return {"batches": sorted(batches, key=lambda b: b.get("run_id", ""), reverse=True)}


@router.get("/devpanel/cost")
async def get_cost(data_dir: str = "data", batch_id: str | None = None):
    return {"message": "Cost data available after a pipeline run via the LLMClient.cost_summaries()"}
