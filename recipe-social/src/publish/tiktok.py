"""TikTok photo carousel publishing via the Content Posting API.

Two modes, selected by TIKTOK_POST_MODE:

  MEDIA_UPLOAD (default) — the carousel lands in the account's drafts. You open
      TikTok, pick a trending sound, and post. This is the only way to control
      which song a post carries: no endpoint accepts a sound id, and
      auto_add_music merely lets TikTok's backend choose one for you. It also
      sidesteps the Content Posting API audit, which forces unaudited apps to
      SELF_ONLY visibility on direct posts.

  DIRECT_POST — fully automatic, with auto_add_music so TikTok attaches a
      trending sound of its own choosing. Requires the audit to have passed;
      until then posts are visible only to the creator.

Photos are PULL_FROM_URL only — there is no byte-upload path for carousels — so
the slide URLs must sit under a prefix verified in the developer portal. An
unverified prefix fails with url_ownership_unverified.
"""
from __future__ import annotations

import os
import time

import requests

from ..recipes.schema import Post
from ..state import tokens
from .base import PublishResult, Publisher

API = "https://open.tiktokapis.com/v2"
TIMEOUT = 60
# TikTok caps the caption at 2200 characters, same as the quality gate enforces.
MAX_TITLE = 90


class TikTokPublisher(Publisher):
    name = "tiktok"

    def __init__(self) -> None:
        self.post_mode = os.environ.get("TIKTOK_POST_MODE", "MEDIA_UPLOAD").upper()
        if self.post_mode not in ("MEDIA_UPLOAD", "DIRECT_POST"):
            raise ValueError(f"TIKTOK_POST_MODE must be MEDIA_UPLOAD or DIRECT_POST, got {self.post_mode!r}")
        # Only meaningful for DIRECT_POST; unaudited apps are forced to SELF_ONLY
        # regardless of what is requested here.
        self.privacy_level = os.environ.get("TIKTOK_PRIVACY_LEVEL", "PUBLIC_TO_EVERYONE")
        self.auto_add_music = os.environ.get("TIKTOK_AUTO_ADD_MUSIC", "true").lower() == "true"

    def _payload(self, post: Post) -> dict:
        caption = post.full_caption
        post_info = {
            # TikTok shows `title` as the post text for photo posts; description
            # carries the rest. Splitting keeps the hook prominent.
            "title": post.recipe.hook[:MAX_TITLE],
            "description": caption,
            "disable_comment": False,
        }
        if self.post_mode == "DIRECT_POST":
            post_info["privacy_level"] = self.privacy_level
            post_info["auto_add_music"] = self.auto_add_music

        return {
            "post_mode": self.post_mode,
            "media_type": "PHOTO",
            "post_info": post_info,
            "source_info": {
                "source": "PULL_FROM_URL",
                "photo_cover_index": 0,
                "photo_images": post.slide_urls,
            },
        }

    def _creator_info(self, access_token: str) -> dict:
        """Required before posting; also surfaces the account's allowed privacy options."""
        response = requests.post(
            f"{API}/post/publish/creator_info/query/",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json; charset=UTF-8",
            },
            timeout=TIMEOUT,
        )
        response.raise_for_status()
        return response.json().get("data", {})

    def publish(self, post: Post, dry_run: bool = False) -> PublishResult:
        if not post.slide_urls:
            return PublishResult(self.name, ok=False, message="No staged slide URLs to publish.")

        payload = self._payload(post)

        if dry_run:
            return PublishResult(
                self.name, ok=True, detail={"payload": payload},
                message=f"DRY RUN — would POST {self.post_mode} to {API}/post/publish/content/init/",
            )

        access_token = tokens.tiktok_access_token()
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=UTF-8",
        }

        creator = self._creator_info(access_token)
        allowed = creator.get("privacy_level_options") or []
        if self.post_mode == "DIRECT_POST" and allowed and self.privacy_level not in allowed:
            # TikTok requires the app to respect the account's available options
            # rather than forcing a level it has not granted.
            payload["post_info"]["privacy_level"] = allowed[0]

        response = requests.post(
            f"{API}/post/publish/content/init/", headers=headers, json=payload, timeout=TIMEOUT
        )
        body = response.json() if response.content else {}
        error = (body.get("error") or {}).get("code", "ok")

        if response.status_code != 200 or error not in ("ok", ""):
            hint = ""
            if "url_ownership_unverified" in str(body):
                hint = (
                    " — the slide URL prefix is not verified in the TikTok developer "
                    "portal. Verify PAGES_BASE_URL under Manage URL properties."
                )
            return PublishResult(
                self.name, ok=False, detail=body,
                message=f"TikTok init failed ({response.status_code}): {body}{hint}",
            )

        publish_id = body.get("data", {}).get("publish_id")
        status = self._await_status(publish_id, headers) if publish_id else {}

        drafted = self.post_mode == "MEDIA_UPLOAD"
        return PublishResult(
            self.name, ok=True,
            detail={"publish_id": publish_id, "status": status},
            needs_manual_finish=drafted,
            message=(
                "Carousel is in your TikTok drafts — open the app, pick a trending "
                "sound, and post." if drafted else "Posted directly to TikTok."
            ),
        )

    def _await_status(self, publish_id: str, headers: dict, attempts: int = 6) -> dict:
        """Poll publish status briefly. TikTok downloads the images asynchronously,
        so a failure here (e.g. an unreachable URL) surfaces after init returns ok."""
        status: dict = {}
        for attempt in range(attempts):
            time.sleep(min(2 ** attempt, 15))
            response = requests.post(
                f"{API}/post/publish/status/fetch/",
                headers=headers, json={"publish_id": publish_id}, timeout=TIMEOUT,
            )
            if response.status_code != 200:
                continue
            status = response.json().get("data", {})
            if status.get("status") in ("PUBLISH_COMPLETE", "FAILED", "SEND_TO_USER_INBOX"):
                break
        return status
