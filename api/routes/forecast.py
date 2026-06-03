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


_TOOL_DESCRIPTIONS: dict[str, str] = {
    "powershell": "Microsoft's scripting language, frequently abused by attackers to run commands and download malware without triggering antivirus.",
    "cobalt strike": "Commercial penetration testing tool widely used by attackers as a command-and-control framework after gaining initial access.",
    "mimikatz": "A credential-dumping tool that extracts passwords and tokens from Windows memory.",
    "lockbit": "A ransomware family that encrypts victim files and demands payment — one of the most prolific ransomware groups globally.",
    "ngrok": "A tunnelling tool that creates temporary public URLs — used legitimately by developers, abused by attackers to bypass firewalls.",
    "anydesk": "Remote desktop software — legitimate tool sometimes abused by attackers to maintain persistent access.",
    "impacket": "A Python library for network protocols, used by attackers for lateral movement and credential theft.",
    "powerstats": "A PowerShell-based backdoor associated with Iranian threat actors, used for command-and-control.",
    "powgoop": "A PowerShell downloader associated with Iranian state-linked threat actors.",
    "moriagent": "A backdoor used by Iranian APT groups for persistent access to compromised systems.",
    "beacon": "The payload component of Cobalt Strike — a stealthy implant used for command-and-control.",
    "metasploit": "A widely used penetration testing framework that also appears in real-world attacks.",
    "psexec": "A Microsoft Sysinternals tool for running processes remotely — frequently used by attackers for lateral movement.",
    "systembc": "A proxy malware used as a backdoor, often deployed alongside ransomware.",
    "remcos": "A commercial remote access tool frequently abused by attackers for surveillance and control.",
    "agenttesla": "An info-stealing malware that harvests credentials, keystrokes, and screenshots.",
}


@router.get("/tool-info")
async def get_tool_info(tool: str = Query(...)):
    """Return a plain-English one-sentence description for a named tool."""
    key = tool.lower().strip()
    if key in _TOOL_DESCRIPTIONS:
        return {"tool": tool, "description": _TOOL_DESCRIPTIONS[key]}
    for known, desc in _TOOL_DESCRIPTIONS.items():
        if known in key or key in known:
            return {"tool": tool, "description": desc}
    return {
        "tool": tool,
        "description": "A tool or malware family observed in threat intelligence reports for this sector.",
    }


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
        "top_k_accuracy": report.get("top_k_accuracy", 0.0),
        "metrics": {
            "precision_at_k": report.get("precision_at_k"),
            "recall_at_k": report.get("recall_at_k"),
            "f1_at_k": report.get("f1_at_k"),
            "map_score": report.get("map_score"),
            "ndcg_at_k": report.get("ndcg_at_k"),
            "top_k_accuracy": report.get("top_k_accuracy"),
            "baseline_top_k": report.get("sector_frequency_baseline_top_k"),
            "lift_over_baseline": report.get("lift_over_baseline"),
        },
        "provenance": {
            "model_type": report.get("model_type", "Co-occurrence frequency ranking (top-k)"),
            "extraction_model": report.get("extraction_model", "Claude Opus 4.8 via AWS Bedrock"),
            "feature_tier": report.get("feature_tier", "LLM_EXTRACTED"),
            "train_rows": report.get("train_rows"),
            "holdout_rows": report.get("holdout_rows"),
            "industries_evaluated": report.get("industries_evaluated"),
            "aql_port_idiom": t.aql_port_idiom,
        },
        "baselines": {"sector_frequency_top_k": report.get("sector_frequency_baseline_top_k", 0)},
        "batch_id": batch_id,
    }
