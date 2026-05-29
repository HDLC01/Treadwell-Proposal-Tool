"""
Dropbox OAuth helper — one-time script to turn App Key + App Secret
into a refresh token.

Usage:
    .venv/Scripts/python.exe dropbox_oauth_setup.py

What it does:
  1. Asks for your App Key + App Secret.
  2. Prints an authorization URL you click in your browser.
  3. You sign into Dropbox, click "Allow".
  4. Dropbox shows you a one-time auth code.
  5. You paste the code back here.
  6. Script swaps the code for a refresh token (the long-lived one
     we put in the Railway env var).
  7. Script tests the refresh token by listing your Dropbox root.

After this, you'll have THREE values to give the server:
    DROPBOX_APP_KEY=<from step 1>
    DROPBOX_APP_SECRET=<from step 1>
    DROPBOX_REFRESH_TOKEN=<output of this script>

You only run this ONCE per Dropbox app.
"""
from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request


def prompt(label: str) -> str:
    while True:
        v = input(f"{label}: ").strip()
        if v:
            return v
        print("  (required) please paste a value")


def main() -> int:
    print("=" * 70)
    print(" Dropbox OAuth setup — one-time refresh-token generator")
    print("=" * 70)
    print()
    print("  Tip: paste the values from your Dropbox app at")
    print("       https://www.dropbox.com/developers/apps")
    print()
    app_key    = prompt("App Key")
    app_secret = prompt("App Secret")

    # Step 1 — build authorization URL with offline access (=> refresh token)
    auth_url = (
        "https://www.dropbox.com/oauth2/authorize"
        f"?client_id={urllib.parse.quote(app_key)}"
        f"&response_type=code"
        f"&token_access_type=offline"
    )

    print()
    print("=" * 70)
    print(" STEP 1 — Click this URL in your browser:")
    print("=" * 70)
    print()
    print(f"  {auth_url}")
    print()
    print("  Sign in if needed, then click 'Allow'.")
    print("  Dropbox will show you a SHORT auth code (no slashes, ~40 chars).")
    print()

    auth_code = prompt("Paste the auth code here").strip()

    # Step 2 — POST the code + secret to exchange for a refresh token
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
        print()
        print("=" * 70)
        print(f" ✗ Dropbox rejected the exchange: HTTP {e.code}")
        print(f"   {e.read().decode('utf-8', errors='replace')}")
        print()
        print(" Common causes:")
        print("   • Auth code was already used (each one is single-use)")
        print("   • App Secret typo")
        print("   • Authorization URL didn't include token_access_type=offline")
        print()
        return 1

    refresh_token = payload.get("refresh_token")
    access_token  = payload.get("access_token")
    if not refresh_token:
        print(f" ✗ No refresh_token in response. Got: {payload}")
        return 1

    # Step 3 — sanity-check by listing the Dropbox root
    print()
    print("=" * 70)
    print(" STEP 2 — Testing the refresh token...")
    print("=" * 70)
    # Use the short-lived access_token we just got to confirm we have API access
    test_req = urllib.request.Request(
        "https://api.dropboxapi.com/2/users/get_current_account",
        method="POST",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    try:
        with urllib.request.urlopen(test_req, timeout=20) as resp:
            who = json.loads(resp.read().decode("utf-8"))
        name = (who.get("name") or {}).get("display_name", "(unknown)")
        email = who.get("email", "(no email)")
        print(f"   ✓ Connected to Dropbox as: {name} <{email}>")
    except Exception as exc:
        print(f"   ✗ API test failed: {exc}")

    # Step 4 — print env vars to copy
    print()
    print("=" * 70)
    print(" STEP 3 — Copy these 3 values into Railway env vars")
    print("         (or paste into your local .env for testing)")
    print("=" * 70)
    print()
    print(f"   DROPBOX_APP_KEY={app_key}")
    print(f"   DROPBOX_APP_SECRET={app_secret}")
    print(f"   DROPBOX_REFRESH_TOKEN={refresh_token}")
    print()
    print(" After Railway picks these up, the tool will auto-refresh")
    print(" its access token every ~4 hours. No further action needed.")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
