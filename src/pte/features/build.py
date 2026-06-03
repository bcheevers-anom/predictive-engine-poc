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
