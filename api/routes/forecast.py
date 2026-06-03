from fastapi import APIRouter, HTTPException, Query
from pte.predict.base import get_task
from pte.explain.contributions import feature_contributions
import json
from pathlib import Path

router = APIRouter()


@router.get("/industries")
async def get_industries(batch_id: str = Query(...), data_dir: str = "data", min_count: int = 5):
    """Return sorted list of industries with enough signal to forecast."""
    report_path = Path(data_dir) / "models" / batch_id / "t2ind_report.json"
    if not report_path.exists():
        return {"industries": []}
    report = json.loads(report_path.read_text())
    coverage = report.get("coverage_per_industry", {})
    industries = sorted(
        [ind for ind, count in coverage.items() if count >= min_count],
        key=lambda i: coverage[i],
        reverse=True,
    )
    return {"industries": industries, "coverage": {i: coverage[i] for i in industries}}


@router.get("/forecast")
async def get_forecast(
    batch_id: str = Query(...),
    industry: str | None = None,
    company: str | None = None,
    task: str = "t2-industry",
    data_dir: str = "data",
):
    if company:
        return {"status": "not_supported", "reason": "Company-level signal sparse for this batch. Use sector-level forecast instead."}

    try:
        t = get_task(task, batch_id=batch_id, data_dir=data_dir)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    model_dir = Path(data_dir) / "models" / batch_id
    # t2_industry writes t2ind_report.json; t1_vuln_exploit writes t1_report.json
    report_filename = {"t2_industry": "t2ind_report.json"}.get(t.task_id, f"{t.task_id}_report.json")
    report_path = model_dir / report_filename
    if not report_path.exists():
        return {
            "status": "no_model",
            "message": "This forecast hasn't been generated for the current batch yet.",
            "hint": "Use the dev panel to run the pipeline for this batch.",
        }

    report = json.loads(report_path.read_text())
    passes = report.get("passes_gate", False)

    prediction = t.predict(industry or "")
    explanation = t.explain({"industry": industry})
    contribs = feature_contributions(explanation.get("feature_importance", {})) if "feature_importance" in explanation else []

    return {
        "status": "ok",
        "passes_gate": passes,
        "gate_note": report.get("eval_note", ""),
        "finding": {
            "title": f"Sector Threat Forecast — {industry or 'All'}",
            "type_name": "PTE/T2-Industry",
            "confidence": report.get("top_k_accuracy", 0.0),
            "viz_type": "classification",
        },
        "prediction": prediction,
        "feature_contributions": contribs,
        "coverage": report.get("coverage_per_industry", {}),
        "baselines": {"sector_frequency_top_k": report.get("sector_frequency_baseline_top_k", 0)},
        "aql_port_idiom": t.aql_port_idiom,
        "batch_id": batch_id,
        "top_k_accuracy": report.get("top_k_accuracy", 0.0),
    }
