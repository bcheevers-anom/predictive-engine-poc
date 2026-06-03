from fastapi import APIRouter, Query
import json
from pathlib import Path

router = APIRouter()


@router.get("/trends")
async def get_trends(
    batch_id: str = Query(...),
    industry: str = Query(...),
    data_dir: str = "data",
    top_n: int = 5,
):
    """Weekly tool count series for a given sector — powers the stacked area chart."""
    import pyarrow.parquet as pq
    from datetime import datetime, timedelta
    from collections import defaultdict, Counter
    import re

    feat_path = Path(data_dir) / "features" / batch_id / "industry_tool_cooccur.parquet"
    if not feat_path.exists():
        return {"weeks": [], "series": [], "holdout_start": None}

    rows = pq.read_table(str(feat_path)).to_pylist()
    sector_rows = [r for r in rows if r.get("industry") == industry and r.get("tool") and r.get("created_ts")]
    if not sector_rows:
        return {"weeks": [], "series": [], "holdout_start": None}

    # Get holdout_start from the model report
    report_path = Path(data_dir) / "models" / batch_id / "t2ind_report.json"
    holdout_start = None
    if report_path.exists():
        report = json.loads(report_path.read_text())
        note = report.get("eval_note", "")
        m = re.search(r"holdout_start=(\d{4}-\d{2}-\d{2})", note)
        if m:
            holdout_start = m.group(1)

    def week_start(date_str: str) -> str:
        d = datetime.fromisoformat(date_str[:10])
        return (d - timedelta(days=d.weekday())).strftime("%Y-%m-%d")

    tool_totals: Counter = Counter(r["tool"] for r in sector_rows)
    top_tools = [t for t, _ in tool_totals.most_common(top_n)]

    weekly: dict[str, Counter] = defaultdict(Counter)
    for r in sector_rows:
        w = week_start(r["created_ts"])
        weekly[w][r["tool"]] += 1

    weeks = sorted(weekly.keys())
    series = [
        {"tool": tool, "counts": [weekly[w].get(tool, 0) for w in weeks]}
        for tool in top_tools
    ]
    return {"weeks": weeks, "series": series, "holdout_start": holdout_start}
