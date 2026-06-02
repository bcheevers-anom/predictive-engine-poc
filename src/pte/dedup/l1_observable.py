from collections import defaultdict
from pte.dedup.merge import build_canonical_record


def normalise_observable_key(value: str, itype: str) -> str:
    """Normalise to (value, type) dedup key. Case-insensitive for domains/email/URLs; exact for IPs/hashes."""
    # ThreatStream itype values: mal_domain, mal_url, phish_url, c2_domain, compromised_domain etc.
    itype_lower = itype.lower()
    case_insensitive_types = {"domain", "email", "url", "hostname", "uri",
                              "mal_domain", "mal_url", "phish_url", "c2_domain",
                              "compromised_domain", "apt_domain", "hack_domain"}
    if itype_lower in case_insensitive_types:
        return f"{value.lower().strip()}::{itype_lower}"
    return f"{value.strip()}::{itype_lower}"


def l1_dedup_batch(records: list[dict]) -> list[dict]:
    """Deterministic dedup of observables by (value, itype). No LLM. O(n)."""
    buckets: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        key = normalise_observable_key(r.get("value", ""), r.get("itype", ""))
        buckets[key].append(r)
    return [build_canonical_record(group) for group in buckets.values()]
