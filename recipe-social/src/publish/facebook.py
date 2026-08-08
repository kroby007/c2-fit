"""Facebook Page multi-photo publishing.

Upload each photo unpublished to collect its id, then create one feed post that
attaches them all — that is what produces a single multi-photo post rather than
three separate ones.
"""
from __future__ import annotations

import json
import os

import requests

from ..recipes.schema import Post
from .base import PublishResult, Publisher

GRAPH = f"https://graph.facebook.com/{os.environ.get('META_API_VERSION', 'v21.0')}"
TIMEOUT = 60


class FacebookPublisher(Publisher):
    name = "facebook"

    def __init__(self) -> None:
        self.page_id = os.environ.get("FB_PAGE_ID")
        # A Page access token, not a user token — see README.
        self.token = os.environ.get("FB_PAGE_ACCESS_TOKEN") or os.environ.get("META_ACCESS_TOKEN")
        if not (self.page_id and self.token):
            raise RuntimeError("FB_PAGE_ID and FB_PAGE_ACCESS_TOKEN must be set.")

    def _post(self, path: str, params: dict) -> dict:
        response = requests.post(
            f"{GRAPH}/{path}", data={**params, "access_token": self.token}, timeout=TIMEOUT
        )
        body = response.json() if response.content else {}
        if response.status_code != 200 or "error" in body:
            raise RuntimeError(f"Facebook {path} failed ({response.status_code}): {body}")
        return body

    def publish(self, post: Post, dry_run: bool = False) -> PublishResult:
        urls = post.slide_urls
        if not urls:
            return PublishResult(self.name, ok=False, message="No staged slide URLs to publish.")

        if dry_run:
            return PublishResult(
                self.name, ok=True, detail={"images": urls},
                message=f"DRY RUN — would upload {len(urls)} unpublished photos then one feed post.",
            )

        try:
            photo_ids = [
                self._post(f"{self.page_id}/photos", {"url": url, "published": "false"})["id"]
                for url in urls
            ]
            feed = self._post(
                f"{self.page_id}/feed",
                {
                    "message": post.full_caption,
                    "attached_media": json.dumps([{"media_fbid": pid} for pid in photo_ids]),
                },
            )
        except RuntimeError as exc:
            return PublishResult(self.name, ok=False, message=str(exc))

        return PublishResult(
            self.name, ok=True,
            detail={"post_id": feed.get("id"), "photo_ids": photo_ids},
            message="Published to the Facebook Page.",
        )
