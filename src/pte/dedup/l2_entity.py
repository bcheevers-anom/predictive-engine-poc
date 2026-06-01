from collections import defaultdict
from pte.dedup.alias_map import resolve_actor_alias, resolve_malware_alias
from pte.dedup.merge import build_canonical_record


def _canonical_bucket(entity: dict) -> str:
    name = entity.get("name", entity.get("value", entity.get("entity_id", "")))
    etype = entity.get("entity_type", "")
    if etype in ("actor", "threat-actor"):
        return resolve_actor_alias(name)
    if etype in ("malware", "tool"):
        return resolve_malware_alias(name)
    return name  # no alias map for this type — use raw name as bucket


def l2_entity_resolution(entities: list[dict]) -> list[dict]:
    """Resolve entity aliases into canonical buckets. O(n) on alias map lookups."""
    buckets: dict[str, list[dict]] = defaultdict(list)
    for entity in entities:
        key = _canonical_bucket(entity)
        buckets[key].append(entity)
    return [build_canonical_record(group, dedup_level="L2") for group in buckets.values()]
