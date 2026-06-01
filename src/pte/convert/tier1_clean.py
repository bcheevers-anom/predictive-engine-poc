from pte.convert.normalize_tags import normalize_tags
from pte.convert.quarantine import Quarantine
from pte.convert.refang import refang
from pte.schema.models import PTEEntity, ProvenanceRecord

SKILL_VERSION = "tier1_clean-v1"


class Tier1Cleaner:
    def __init__(self, run_id: str, quarantine: Quarantine | None = None):
        self._run_id = run_id
        self._q = quarantine or Quarantine()

    def clean_observable(self, raw: dict) -> PTEEntity | None:
        try:
            value = refang(raw.get("value", ""))
            feed = raw.get("source") or raw.get("source_feed", "")
            tags_raw = raw.get("tags", [])
            if tags_raw and isinstance(tags_raw[0], dict):
                tags_raw = [t.get("name", "") for t in tags_raw]
            tags = normalize_tags(tags_raw)

            entity = PTEEntity(
                entity_id=str(raw["id"]),
                entity_type=raw.get("itype", "observable"),
                source_feed=feed,
                source_confidence=raw.get("confidence"),
                observed_ts=raw.get("created_ts"),
                created_ts=raw.get("created_ts"),
                modified_ts=raw.get("modified_ts"),
                first_seen=raw.get("first_seen"),
                last_seen=raw.get("last_seen"),
                observable={"value": value, "type": raw.get("itype", "")},
                indicator_type=raw.get("itype"),
                severity=raw.get("severity"),
                confidence=raw.get("confidence"),
                tags=tags,
                validation_status="ok",
                provenance=ProvenanceRecord(
                    run_id=self._run_id,
                    tier="OBSERVED",
                    skill_version=SKILL_VERSION,
                    endpoint="/api/v2/intelligence/",
                ),
            )
            return entity
        except Exception as exc:
            self._q.add(str(raw.get("id", "?")), str(exc), {"raw_keys": list(raw.keys())})
            return None

    def clean_many(self, raws: list[dict]) -> tuple[list[PTEEntity], Quarantine]:
        entities = []
        for raw in raws:
            e = self.clean_observable(raw)
            if e:
                entities.append(e)
        return entities, self._q
