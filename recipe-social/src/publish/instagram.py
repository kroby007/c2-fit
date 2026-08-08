"""Instagram carousel publishing via the Instagram Graph API.

Three steps, in order: an item container per image, a CAROUSEL parent container
holding their ids, then publish the parent. Requires an Instagram Business or
Creator account linked to a Facebook Page — the publishing API does not work on
personal accounts at any tier.

Unlike TikTok there is no domain verification: the image URLs only need to be
publicly reachable over HTTPS.
"""
from __future__ import annotations

import os

import requests

from ..recipes.schema import Post
from .base import PublishResult, Publisher

GRAPH = f"https://graph.facebook.com/{os.environ.get('META_API_VERSION', 'v21.0')}"
TIMEOUT = 60
# Instagram rejects a carousel with more than 10 items.
MAX_CAROUSEL_ITEMS = 10


class InstagramPublisher(Publisher):
    name = "instagram"

    def __init__(self) -> None:
        self.user_id = os.environ.get("IG_USER_ID")
        self.token = os.environ.get("META_ACCESS_TOKEN")
        if not (self.user_id and self.token):
            raise RuntimeError("IG_USER_ID and META_ACCESS_TOKEN must be set.")

    def _post(self, path: str, params: dict) -> dict:
        response = requests.post(
            f"{GRAPH}/{path}", data={**params, "access_token": self.token}, timeout=TIMEOUT
        )
        body = response.json() if response.content else {}
        if response.status_code != 200 or "error" in body:
            raise RuntimeError(f"Instagram {path} failed ({response.status_code}): {body}")
        return body

    def publish(self, post: Post, dry_run: bool = False) -> PublishResult:
        urls = post.slide_urls[:MAX_CAROUSEL_ITEMS]
        if not urls:
            return PublishResult(self.name, ok=False, message="No staged slide URLs to publish.")

        if dry_run:
            return PublishResult(
                self.name, ok=True,
                detail={"images": urls, "caption_chars": len(post.full_caption)},
                message=f"DRY RUN — would create {len(urls)} item containers then a CAROUSEL parent.",
            )

        try:
            children = [
                self._post(f"{self.user_id}/media", {"image_url": url, "is_carousel_item": "true"})["id"]
                for url in urls
            ]
            parent = self._post(
                f"{self.user_id}/media",
                {
                    "media_type": "CAROUSEL",
                    "children": ",".join(children),
                    "caption": post.full_caption,
                },
            )["id"]
            published = self._post(f"{self.user_id}/media_publish", {"creation_id": parent})
        except RuntimeError as exc:
            return PublishResult(self.name, ok=False, message=str(exc))

        return PublishResult(
            self.name, ok=True,
            detail={"media_id": published.get("id"), "children": children},
            message="Published to Instagram.",
        )
