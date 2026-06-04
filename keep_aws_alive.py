"""
AWS Bedrock SSO Session Keeper
===============================
Runs in the background and keeps your AWS SSO session alive by
refreshing the token before it expires. Like Caffeine but for AWS.

Run in a separate terminal and leave it open:
    python keep_aws_alive.py

How it works:
  1. Reads the SSO cache file to find when the token expires
  2. Wakes up 30 minutes before expiry and triggers a refresh
  3. Opens a browser tab for you to approve the SSO login
  4. Loops indefinitely — close the terminal to stop it

Requirements:
  - AWS CLI installed and on PATH
  - Profile 'staging' configured in ~/.aws/config
"""

import glob
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

AWS_PROFILE = os.environ.get("AWS_PROFILE", "staging")
REFRESH_BEFORE_EXPIRY_SECONDS = 6 * 60 * 60  # refresh 6 hours before expiry
CHECK_INTERVAL_SECONDS = 5 * 60           # check every 5 minutes
SSO_CACHE_DIR = Path.home() / ".aws" / "sso" / "cache"


def _banner(msg: str, level: str = "INFO") -> None:
    icons = {"INFO": "  ", "WARN": "⚠ ", "OK": "✓ ", "ERROR": "✗ ", "ACTION": ">>> "}
    icon = icons.get(level, "  ")
    now = datetime.now().strftime("%H:%M:%S")
    print(f"[{now}] {icon}{msg}", flush=True)


def find_valid_token() -> dict | None:
    """Find the most recent valid SSO access token in the cache."""
    if not SSO_CACHE_DIR.exists():
        return None
    best = None
    for f in SSO_CACHE_DIR.glob("*.json"):
        try:
            data = json.loads(f.read_text())
            if not data.get("accessToken"):
                continue
            expiry_str = data.get("expiresAt", "")
            if not expiry_str:
                continue
            # Parse ISO8601 expiry
            expiry = datetime.fromisoformat(expiry_str.replace("Z", "+00:00"))
            if best is None or expiry > best["expiry"]:
                best = {"expiry": expiry, "file": f, "data": data}
        except Exception:
            continue
    return best


def seconds_until_expiry(token: dict) -> float:
    now = datetime.now(timezone.utc)
    return (token["expiry"] - now).total_seconds()


def refresh_session() -> bool:
    """Trigger aws sso login. Opens browser for approval. Returns True if successful."""
    _banner(f"Triggering SSO login for profile '{AWS_PROFILE}'...", "ACTION")
    _banner("A browser tab will open — approve the login.", "ACTION")
    try:
        result = subprocess.run(
            ["aws", "sso", "login", "--profile", AWS_PROFILE],
            timeout=300,   # 5 minute window to approve in browser
        )
        if result.returncode == 0:
            _banner("SSO login successful — session refreshed.", "OK")
            return True
        else:
            _banner(f"SSO login failed (exit code {result.returncode}).", "ERROR")
            return False
    except subprocess.TimeoutExpired:
        _banner("SSO login timed out — browser approval not received within 5 minutes.", "ERROR")
        return False
    except FileNotFoundError:
        _banner("'aws' command not found — is AWS CLI installed and on PATH?", "ERROR")
        return False


def check_and_validate() -> tuple[bool, float]:
    """Check if session is valid. Returns (is_valid, seconds_remaining)."""
    token = find_valid_token()
    if token is None:
        return False, 0.0
    remaining = seconds_until_expiry(token)
    return remaining > 0, remaining


def main():
    print()
    print("=" * 55)
    print("  AWS Bedrock SSO Session Keeper")
    print(f"  Profile: {AWS_PROFILE}")
    print(f"  Refreshes 6 hours before expiry (every ~2hrs on 8hr tokens)")
    print(f"  Checks every {CHECK_INTERVAL_SECONDS // 60} minutes")
    print("  Close this terminal to stop")
    print("=" * 55)
    print()

    consecutive_failures = 0

    while True:
        is_valid, remaining = check_and_validate()

        if not is_valid:
            _banner("No valid SSO token found — attempting login now.", "WARN")
            success = refresh_session()
            if not success:
                consecutive_failures += 1
                wait = min(60 * consecutive_failures, 600)
                _banner(f"Will retry in {wait}s (attempt {consecutive_failures}).", "WARN")
                time.sleep(wait)
                continue
            consecutive_failures = 0

        elif remaining < REFRESH_BEFORE_EXPIRY_SECONDS:
            mins = int(remaining / 60)
            _banner(f"Token expires in {mins} minutes — refreshing now.", "WARN")
            success = refresh_session()
            if not success:
                consecutive_failures += 1
            else:
                consecutive_failures = 0

        else:
            mins = int(remaining / 60)
            hrs = mins // 60
            mins_rem = mins % 60
            time_str = f"{hrs}h {mins_rem}m" if hrs > 0 else f"{mins_rem}m"
            _banner(f"Session valid — expires in {time_str}", "OK")
            consecutive_failures = 0

        time.sleep(CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nSession keeper stopped.")
        sys.exit(0)
