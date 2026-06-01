def l1_dedup_batch(records: list[dict]) -> list[dict]:
    """Stub — deduplicates observable records. Full implementation in Task 10."""
    seen = set()
    result = []
    for r in records:
        key = f"{r.get('value', '')}::{r.get('itype', '')}"
        if key not in seen:
            seen.add(key)
            r.setdefault("dedup_status", "singleton")
            r.setdefault("merged_from", [r.get("id", "")])
            r.setdefault("source_feed_count", 1)
            result.append(r)
    return result
