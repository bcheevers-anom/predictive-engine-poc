from fastapi import APIRouter, Query
from pte.predict.trends import TrendTask

router = APIRouter()

@router.get("/trends")
async def get_trends(batch_id: str = Query(...), data_dir: str = "data"):
    t = TrendTask(batch_id=batch_id, data_dir=data_dir)
    t.fit()
    return t.predict({})
