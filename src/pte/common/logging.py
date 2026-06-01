import json
import sys

def structured_log(event: str, **fields) -> None:
    """Emit a JSON log line to stderr. Never log secrets or pre-signed URLs."""
    forbidden = {"api_key", "apikey", "token", "presigned", "password", "secret"}
    safe = {k: v for k, v in fields.items() if k.lower() not in forbidden}
    record = {"event": event, **safe}
    print(json.dumps(record), file=sys.stderr)
