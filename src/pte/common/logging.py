import json
import sys
import time

_START_TIME = time.monotonic()


def _elapsed() -> str:
    secs = int(time.monotonic() - _START_TIME)
    m, s = divmod(secs, 60)
    return f"{m:02d}:{s:02d}"


def structured_log(event: str, **fields) -> None:
    """Emit a JSON log line to stderr. Never log secrets or pre-signed URLs."""
    forbidden = {"api_key", "apikey", "token", "presigned", "password", "secret"}
    safe = {k: v for k, v in fields.items() if k.lower() not in forbidden}
    record = {"event": event, **safe}
    print(json.dumps(record), file=sys.stderr)


def progress(msg: str, **fields) -> None:
    """Print a human-readable progress line to stdout with elapsed time.

    Use for operations a human is watching. Does NOT log secrets.
    """
    forbidden = {"api_key", "apikey", "token", "presigned", "password", "secret"}
    suffix_parts = [f"{k}={v}" for k, v in fields.items() if k.lower() not in forbidden]
    suffix = "  " + "  ".join(suffix_parts) if suffix_parts else ""
    print(f"[{_elapsed()}] {msg}{suffix}", flush=True)
