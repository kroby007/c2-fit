"""OAuth token handling.

TikTok rotates the refresh token on every refresh: the old one stops working the
moment you use it. On an ephemeral Actions runner that means the new value has to
be written back to a durable store or the next scheduled run cannot authenticate.
We write it into the repository's Actions secrets via the GitHub API (libsodium
sealed box, as GitHub requires).

Refresh tokens are never logged. If write-back is not configured, the new token
is saved to a gitignored local file and the run warns — recoverable by hand,
rather than silently lost.
"""
from __future__ import annotations

import base64
import os

import requests

from .. import config

TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
TIMEOUT = 30

# Where a rotated token goes when GitHub write-back is unavailable.
FALLBACK_PATH = config.STATE_DIR / "tiktok_refresh_token.local"


def _update_github_secret(name: str, value: str) -> bool:
    """Store `value` as an Actions secret. Returns False if not configured."""
    pat = os.environ.get("GH_PAT")
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not pat or not repo:
        return False

    from nacl import encoding, public

    headers = {
        "Authorization": f"Bearer {pat}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    key_response = requests.get(
        f"https://api.github.com/repos/{repo}/actions/secrets/public-key",
        headers=headers, timeout=TIMEOUT,
    )
    key_response.raise_for_status()
    key_data = key_response.json()

    sealed = public.SealedBox(
        public.PublicKey(key_data["key"].encode(), encoding.Base64Encoder())
    ).encrypt(value.encode())

    put = requests.put(
        f"https://api.github.com/repos/{repo}/actions/secrets/{name}",
        headers=headers,
        json={
            "encrypted_value": base64.b64encode(sealed).decode(),
            "key_id": key_data["key_id"],
        },
        timeout=TIMEOUT,
    )
    put.raise_for_status()
    return True


def _persist_refresh_token(token: str) -> None:
    if _update_github_secret("TIKTOK_REFRESH_TOKEN", token):
        print("Rotated TikTok refresh token written back to Actions secrets.")
        return
    FALLBACK_PATH.parent.mkdir(parents=True, exist_ok=True)
    FALLBACK_PATH.write_text(token)
    print(
        "WARNING: TikTok issued a new refresh token but GH_PAT/GITHUB_REPOSITORY "
        f"are not set, so it could not be stored. It is in {FALLBACK_PATH} — copy it "
        "into the TIKTOK_REFRESH_TOKEN secret before the next run, or that run will "
        "fail to authenticate."
    )


def tiktok_access_token() -> str:
    """Exchange the stored refresh token for an access token, persisting rotation."""
    client_key = os.environ.get("TIKTOK_CLIENT_KEY")
    client_secret = os.environ.get("TIKTOK_CLIENT_SECRET")
    refresh_token = os.environ.get("TIKTOK_REFRESH_TOKEN")
    if not (client_key and client_secret and refresh_token):
        raise RuntimeError(
            "TIKTOK_CLIENT_KEY, TIKTOK_CLIENT_SECRET, and TIKTOK_REFRESH_TOKEN "
            "must all be set. See recipe-social/README.md for how to obtain them."
        )

    response = requests.post(
        TOKEN_URL,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "client_key": client_key,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
        timeout=TIMEOUT,
    )
    if response.status_code != 200:
        raise RuntimeError(f"TikTok token refresh failed ({response.status_code}): {response.text}")

    data = response.json()
    if "access_token" not in data:
        raise RuntimeError(f"TikTok token refresh returned no access_token: {data}")

    new_refresh = data.get("refresh_token")
    if new_refresh and new_refresh != refresh_token:
        _persist_refresh_token(new_refresh)

    return data["access_token"]


def local_fallback_token() -> str | None:
    """Read a rotated token that a previous run could not write back."""
    return FALLBACK_PATH.read_text().strip() if FALLBACK_PATH.exists() else None
