def feature_contributions(importances: dict[str, float], top_n: int = 5) -> list[dict]:
    """Return top-N features ranked by importance, normalised to sum to 1."""
    total = sum(importances.values()) or 1.0
    ranked = sorted(importances.items(), key=lambda x: x[1], reverse=True)[:top_n]
    return [{"feature": k, "importance": v, "normalised": v / total} for k, v in ranked]
