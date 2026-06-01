from pte.dedup.alias_map import MALWARE_ALIASES

_WORKFLOW_PREFIXES = ("Ilamona_", "PIR", "ilamona_", "pir")

_TAG_MAP: dict[str, str] = {k.lower(): v for k, v in MALWARE_ALIASES.items()}


def is_workflow_tag(tag: str) -> bool:
    return any(tag.startswith(p) for p in _WORKFLOW_PREFIXES)


def normalize_tag(tag: str, dialect: str = "generic") -> str:
    if is_workflow_tag(tag):
        return ""  # caller should filter empties
    canonical = _TAG_MAP.get(tag.lower())
    return canonical if canonical else tag  # unmapped -> return as-is, never drop


def normalize_tags(tags: list[str], dialect: str = "generic") -> list[str]:
    normalised = [normalize_tag(t, dialect) for t in tags]
    return [t for t in normalised if t]  # drop empty (workflow tags)
