import math


def build_canonical_record(records: list[dict], dedup_level: str = "L1", dedup_confidence: float | None = None) -> dict:
    """Merge a list of source records into one canonical record, non-destructively."""
    if not records:
        raise ValueError("Cannot build canonical from empty list")
    if len(records) == 1:
        r = dict(records[0])
        r.setdefault("dedup_status", "singleton")
        r.setdefault("merged_from", [r["id"]])
        r.setdefault("source_feed_count", 1)
        r.setdefault("distinct_event_count", 1)
        r.setdefault("corroboration_score", 0.0)
        return r

    # Use the record with the highest source_confidence as the base
    base = sorted(records, key=lambda r: r.get("source_confidence") or 0, reverse=True)[0]
    canonical = dict(base)
    canonical["canonical_id"] = f"canonical-{canonical['id']}"
    canonical["merged_from"] = [r["id"] for r in records]
    canonical["source_feed_count"] = len({r.get("source_feed", "") for r in records})
    canonical["distinct_event_count"] = len(records)
    canonical["dedup_status"] = "merged"
    canonical["dedup_confidence"] = dedup_confidence
    canonical["corroboration_score"] = min(1.0, math.log(canonical["source_feed_count"] + 1) / math.log(10))

    # For numeric fields, keep min/max/spread for model consumption
    for field in ("source_confidence",):
        vals = [r.get(field) for r in records if r.get(field) is not None]
        if vals and isinstance(vals[0], (int, float)):
            canonical[f"{field}_min"] = min(vals)
            canonical[f"{field}_max"] = max(vals)

    return canonical
