"""
Non-interactive Dropbox OAuth finisher.

Usage:
    .venv/Scripts/python.exe dropbox_oauth_finish.py <auth_code>

Reads APP_KEY + APP_SECRET from .env, swaps the auth code for a
refresh token, updates .env in place. No prompts.
"""
from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from dotenv import load_dotenv
import os
import re

ENV_PATH = Path(__file__).parent / ".env"


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: dropbox_oauth_finish.py <auth_code>", file=sys.stderr)
        return 2

    auth_code = sys.argv[1].strip()
    load_dotenv(ENV_PATH, override=True)

    app_key    = os.environ.get("DROPBOX_APP_KEY", "").strip()
    app_secret = os.environ.get("DROPBOX_APP_SECRET", "").strip()
    if not app_key or not app_secret:
        print("ERROR: DROPBOX_APP_KEY and/or DROPBOX_APP_SECRET missing from .env",
              file=sys.stderr)
        return 1

    body = urllib.parse.urlencode({
        "code": auth_code,
        "grant_type": "authorization_code",
        "client_id": app_key,
        "client_secret": app_secret,
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.dropboxapi.com/oauth2/token",
        data=body,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        print(f"ERROR HTTP {e.code}: {err_body}", file=sys.stderr)
        return 1

    refresh_token = payload.get("refresh_token")
    access_token  = payload.get("access_token")
    if not refresh_token:
        print(f"ERROR: no refresh_token in response: {payload}", file=sys.stderr)
        return 1

    # Sanity check the new access token
    try:
        test_req = urllib.request.Request(
            "https://api.dropboxapi.com/2/users/get_current_account",
            method="POST",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        with urllib.request.urlopen(test_req, timeout=20) as resp:
            who = json.loads(resp.read().decode("utf-8"))
        name = (who.get("name") or {}).get("display_name", "(unknown)")
        email = who.get("email", "(no email)")
        print(f"Connected to Dropbox as: {name} <{email}>")
    except Exception as exc:
        print(f"WARNING API test failed: {exc}", file=sys.stderr)

    # Update .env in place: set DROPBOX_REFRESH_TOKEN, blank DROPBOX_ACCESS_TOKEN
    env_text = ENV_PATH.read_text(encoding="utf-8")
    # Replace the refresh-token line
    env_text = re.sub(
        r"^DROPBOX_REFRESH_TOKEN=.*$",
        f"DROPBOX_REFRESH_TOKEN={refresh_token}",
        env_text,
        flags=re.MULTILINE,
    )
    # Blank out the access-token line (no longer needed)
    env_text = re.sub(
        r"^DROPBOX_ACCESS_TOKEN=.*$",
        "DROPBOX_ACCESS_TOKEN=",
        env_text,
        flags=re.MULTILINE,
    )
    ENV_PATH.write_text(env_text, encoding="utf-8")
    print(f"Wrote refresh token to {ENV_PATH}")
    print(f"Refresh token (first 30 chars): {refresh_token[:30]}...")
    return 0


if __name__ == "__main__":
    sys.exit(main())
