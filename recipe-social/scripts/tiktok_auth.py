#!/usr/bin/env python3
"""One-time TikTok authorization: exchange a login for a refresh token.

TikTok requires an HTTPS redirect URI, so a localhost callback server is not an
option. Instead the redirect points at docs/oauth.html on the GitHub Pages site,
which prints the authorization code for you to paste back here.

Run it once, put the refresh token in the TIKTOK_REFRESH_TOKEN secret, and the
daily job takes over — it refreshes and rotates the token from then on.

    python scripts/tiktok_auth.py
"""
from __future__ import annotations

import os
import secrets
import sys
import urllib.parse

import requests

AUTHORIZE_URL = "https://www.tiktok.com/v2/auth/authorize/"
TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"

# video.upload covers MEDIA_UPLOAD (drafts). Add video.publish only once you are
# going for the audit that enables fully automatic public posting.
DEFAULT_SCOPES = "user.info.basic,video.upload"


def main() -> int:
    client_key = os.environ.get("TIKTOK_CLIENT_KEY")
    client_secret = os.environ.get("TIKTOK_CLIENT_SECRET")
    pages_base = os.environ.get("PAGES_BASE_URL")

    missing = [
        name for name, value in (
            ("TIKTOK_CLIENT_KEY", client_key),
            ("TIKTOK_CLIENT_SECRET", client_secret),
            ("PAGES_BASE_URL", pages_base),
        ) if not value
    ]
    if missing:
        print(f"Set these first: {', '.join(missing)}")
        return 1

    redirect_uri = f"{pages_base.rstrip('/')}/oauth.html"
    scopes = os.environ.get("TIKTOK_SCOPES", DEFAULT_SCOPES)
    state = secrets.token_urlsafe(16)

    query = urllib.parse.urlencode(
        {
            "client_key": client_key,
            "scope": scopes,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "state": state,
        }
    )

    print("1. Confirm this exact redirect URI is registered on your TikTok app:\n")
    print(f"     {redirect_uri}\n")
    print("2. Open this URL, log in, and approve:\n")
    print(f"     {AUTHORIZE_URL}?{query}\n")
    print("3. You will land on a page showing an authorization code.\n")

    code = input("Paste the authorization code here: ").strip()
    if not code:
        print("No code entered.")
        return 1

    # The code arrives URL-encoded when copied straight from the address bar.
    code = urllib.parse.unquote(code)

    response = requests.post(
        TOKEN_URL,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "client_key": client_key,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        },
        timeout=30,
    )

    if response.status_code != 200:
        print(f"\nToken exchange failed ({response.status_code}):\n{response.text}")
        print(
            "\nCommon causes: the redirect URI does not match the one registered "
            "on the app exactly, or the code was already used (they are single-use "
            "— start again from step 2)."
        )
        return 1

    data = response.json()
    refresh_token = data.get("refresh_token")
    if not refresh_token:
        print(f"\nNo refresh_token in the response:\n{data}")
        return 1

    print("\nSuccess.\n")
    print(f"  Scopes granted : {data.get('scope')}")
    print(f"  Expires in     : {data.get('expires_in')}s (access token)")
    print("\nAdd this as the TIKTOK_REFRESH_TOKEN repository secret:\n")
    print(f"  {refresh_token}\n")
    print(
        "Treat it like a password — it is the standing credential for posting to "
        "your account. Do not commit it. After this, the daily job rotates it "
        "automatically."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
