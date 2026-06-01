import hashlib
import json
import uuid

def make_run_id() -> str:
    return uuid.uuid4().hex

def config_hash(config: dict) -> str:
    serialised = json.dumps(config, sort_keys=True).encode()
    return hashlib.sha256(serialised).hexdigest()[:12]

def stamp_provenance(record: dict, *, run_id: str, tier: str, skill_version: str, endpoint: str = "", extra: dict | None = None) -> dict:
    record["provenance"] = {
        "run_id": run_id,
        "tier": tier,
        "skill_version": skill_version,
        "endpoint": endpoint,
        **(extra or {}),
    }
    return record
