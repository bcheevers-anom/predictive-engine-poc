import json
from pathlib import Path
from pte.features.store import FeatureStore
from pte.schema.models import PTEEntity


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
                    "tier": "OBSERVED",
                })
        self._store.write(self._batch_id, "vulnerability_features", vuln_features)

        # Industry-tool co-occurrence features (Tier: LLM_EXTRACTED)
        industry_tool = []
        for e in entities:
            if e.industry and e.tool:
                for ind in e.industry:
                    industry_tool.append({
                        "entity_id": e.entity_id,
                        "industry": ind,
                        "tool": e.tool,   # scalar string
                        "tactic": e.tactic or "",
                        "corroboration_score": e.corroboration_score,
                        "tier": "LLM_EXTRACTED",
                    })
        self._store.write(self._batch_id, "industry_tool_cooccur", industry_tool)
