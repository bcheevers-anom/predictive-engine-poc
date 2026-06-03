import json
from pathlib import Path
from pte.features.store import FeatureStore
from pte.schema.models import PTEEntity
from pte.ingest.raw_store import RawStore


class FeatureBuilder:
    def __init__(self, batch_id: str, data_dir: str = "data"):
        self._batch_id = batch_id
        self._data_dir = Path(data_dir)
        self._store = FeatureStore(base_dir=str(self._data_dir / "features"))

    async def build(self) -> None:
        schema_dir = self._data_dir / "schema" / self._batch_id
        entities_path = schema_dir / "extracted_entities.json"
        if not entities_path.exists():
            return

        entities = [PTEEntity(**e) for e in json.loads(entities_path.read_text())]

        # Build a lookup of entity_id -> created_ts from the raw store
        # so we can time-stamp feature rows for the train/eval split
        raw_store = RawStore(base_dir=str(self._data_dir / "raw"))
        ts_lookup: dict[str, str] = {}
        for entity_type in ("actor", "campaign", "malware", "vulnerability"):
            for raw in raw_store.read(self._batch_id, entity_type):
                eid = str(raw.get("id", ""))
                ts = raw.get("created_ts") or raw.get("source_created") or ""
                if eid and ts:
                    ts_lookup[eid] = ts[:10]  # date only

        # Vulnerability features (Tier: OBSERVED)
        vuln_features = []
        for e in entities:
            if e.entity_type in ("cve", "vulnerability") and e.observable:
                vuln_features.append({
                    "entity_id": e.entity_id,
                    "epss_score": e.observable.get("epss_score", 0.0),
                    "cvss_score": e.observable.get("cvss_score", 0.0),
                    "tag_count": len(e.tags),
                    "first_seen": e.first_seen,
                    "created_ts": ts_lookup.get(e.entity_id, ""),
                    "tier": "OBSERVED",
                })
        self._store.write(self._batch_id, "vulnerability_features", vuln_features)

        # Industry-tool co-occurrence features (Tier: LLM_EXTRACTED)
        # tool may be a JSON-serialised list string from the LLM — parse it
        industry_tool = []
        for e in entities:
            if not e.industry:
                continue

            # Parse tool — PTEEntity.tool is str|None but LLM often returns a list
            tools: list[str] = []
            if e.tool:
                raw_tool = e.tool
                if isinstance(raw_tool, str) and raw_tool.startswith("["):
                    try:
                        parsed = json.loads(raw_tool)
                        tools = [str(t) for t in parsed if t]
                    except json.JSONDecodeError:
                        tools = [raw_tool]
                elif isinstance(raw_tool, list):
                    tools = [str(t) for t in raw_tool if t]
                else:
                    tools = [raw_tool]

            if not tools:
                # Still emit an industry row with empty tool so sector coverage is recorded
                tools = [""]

            created_ts = ts_lookup.get(e.entity_id, "")
            for ind in e.industry:
                for tool_name in tools:
                    industry_tool.append({
                        "entity_id": e.entity_id,
                        "industry": ind,
                        "tool": tool_name,
                        "tactic": e.tactic or "",
                        "corroboration_score": e.corroboration_score,
                        "created_ts": created_ts,
                        "tier": "LLM_EXTRACTED",
                    })
        self._store.write(self._batch_id, "industry_tool_cooccur", industry_tool)

        # Tool weekly trend features for T2ToolTactic (ARIMA-equivalent time series)
        # Buckets industry_tool rows by ISO week so we have count-per-week per tool
        from collections import defaultdict as _dd
        from datetime import datetime as _dt, timedelta as _td

        def _week_start(date_str: str) -> str:
            try:
                d = _dt.fromisoformat(date_str[:10])
                return (d - _td(days=d.weekday())).strftime("%Y-%m-%d")
            except Exception:
                return ""

        weekly_counts: dict[str, dict[str, int]] = _dd(lambda: _dd(int))
        for row in industry_tool:
            tool = row.get("tool", "")
            ts = row.get("created_ts", "")
            if tool and ts:
                week = _week_start(ts)
                if week:
                    weekly_counts[tool][week] += 1

        tool_weekly_rows = []
        for tool, week_map in weekly_counts.items():
            for week, count in week_map.items():
                tool_weekly_rows.append({
                    "tool": tool,
                    "week_start": week,
                    "count": count,
                    "tier": "LLM_EXTRACTED",
                })
        self._store.write(self._batch_id, "tool_weekly_trends", tool_weekly_rows)

        # Vulnerability exploitation labels for T1
        # Build lookup from raw vulnerability records for fast access
        vuln_lookup: dict[str, dict] = {}
        for raw in raw_store.read(self._batch_id, "vulnerability"):
            vuln_lookup[str(raw.get("id", ""))] = raw

        vuln_labelled = []
        for e in entities:
            if e.entity_type not in ("cve", "vulnerability"):
                continue
            raw_vuln = vuln_lookup.get(e.entity_id, {})

            # Derive exploitation label from tags (the reliable signal for this data)
            # Positive signals: observed-in-the-wild:Yes, was-zero-day:Yes,
            #   exploitation-state:*, exploitation-consequence:* (non-trivial)
            # Negative signals: observed-in-the-wild:No, was-zero-day:No
            tags = [t.get("name", "") if isinstance(t, dict) else str(t)
                    for t in raw_vuln.get("tags", [])]
            tag_str = " ".join(tags).lower()

            exploited = 0
            if ("observed-in-the-wild:yes" in tag_str
                    or "was-zero-day:yes" in tag_str
                    or "exploitation-state:weaponized" in tag_str
                    or "exploitation-state:exploited" in tag_str):
                exploited = 1
            elif raw_vuln.get("epss_score", 0) and raw_vuln["epss_score"] > 0.1:
                # High EPSS as a secondary signal (>10th percentile probability of exploitation)
                exploited = 1

            epss = raw_vuln.get("epss_score") or 0.0
            cvss = raw_vuln.get("cvss3_score") or raw_vuln.get("cvss2_score") or 0.0
            vuln_labelled.append({
                "entity_id": e.entity_id,
                "epss_score": float(epss),
                "cvss_score": float(cvss),
                "epss_percentile": float(raw_vuln.get("epss_percentile") or 0.0),
                "tag_count": len(tags),
                "first_seen": e.first_seen,
                "created_ts": ts_lookup.get(e.entity_id, ""),
                "exploited": exploited,
                "tier": "OBSERVED",
            })
        # Overwrite vulnerability_features with labelled version
        self._store.write(self._batch_id, "vulnerability_features", vuln_labelled)

        # Company features for T3 (conditional on LLM extraction coverage)
        company_rows = []
        for e in entities:
            if not e.company:
                continue
            companies = e.company if isinstance(e.company, list) else [e.company]
            for c in companies:
                if not isinstance(c, dict):
                    continue
                company_name = c.get("name", "")
                stix_id = c.get("stix_id", "")
                conf = c.get("extraction_confidence") or e.llm_extraction_confidence or 0.0
                if company_name:
                    company_rows.append({
                        "entity_id": e.entity_id,
                        "company_name": company_name,
                        "company_stix_id": stix_id,
                        "industry": (e.industry or [""])[0],
                        "tool": (e.tool or "") if isinstance(e.tool, str) else "",
                        "extraction_confidence": conf,
                        "created_ts": ts_lookup.get(e.entity_id, ""),
                        "tier": "LLM_EXTRACTED",
                    })
        self._store.write(self._batch_id, "company_features", company_rows)
